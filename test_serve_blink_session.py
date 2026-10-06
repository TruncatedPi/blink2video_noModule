"""Régressions de la passerelle synchrone vers la boucle Blink du serveur."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock


os.environ["BLINK_BOOTSTRAP"] = "none"
_TEST_HOME = tempfile.TemporaryDirectory(prefix="blink-session-")
os.environ["BLINK_HOME"] = _TEST_HOME.name

import serve  # noqa: E402 - environnement isolé avant import


class BlinkSessionTests(unittest.TestCase):
    def test_connexion_absente_ou_refusee_ferme_session_http_avant_reessai(self):
        for outcome in (None, RuntimeError("connexion refusée")):
            with self.subTest(outcome=outcome):
                session = serve.BlinkSession()
                clients = [SimpleNamespace(close=mock.AsyncMock()),
                           SimpleNamespace(close=mock.AsyncMock())]
                with mock.patch.object(serve.blink_auth, "session_http", side_effect=clients), \
                     mock.patch.object(serve.blink_auth, "connect_saved", new=mock.AsyncMock(
                         side_effect=outcome if isinstance(outcome, Exception) else None,
                         return_value=None)):
                    try:
                        for _ in range(2):
                            with self.assertRaises(RuntimeError):
                                session.call(mock.AsyncMock())
                        for client in clients:
                            client.close.assert_awaited_once()
                        self.assertIsNone(session.session)
                    finally:
                        if session.loop:
                            session.loop.call_soon_threadsafe(session.loop.stop)
                            deadline = time.monotonic() + 2
                            while session.loop.is_running() and time.monotonic() < deadline:
                                time.sleep(0.001)
                            session.loop.close()

    def test_timeout_annule_la_coroutine_avant_son_effet(self):
        session = serve.BlinkSession()
        session.blink = object()
        effet = threading.Event()

        async def operation(_blink):
            await asyncio.sleep(0.15)
            effet.set()

        try:
            with self.assertRaises(concurrent.futures.TimeoutError):
                session.call(lambda blink: operation(blink), timeout=0.01)
            time.sleep(0.2)
            self.assertFalse(effet.is_set())
        finally:
            if session.loop is not None:
                session.loop.call_soon_threadsafe(session.loop.stop)

    def test_module_xr_est_resolu_par_ids_du_registre(self):
        from test_xr_local_storage import compte_avec_stockage_local

        blink, ancien_appareil = compte_avec_stockage_local()
        module = serve.BlinkSession().find_sync_module(
            blink,
            {"network_id": "7", "sync_id": "900", "camera": "Porte d'entrée"},
        )

        self.assertIsNot(module, ancien_appareil)
        self.assertEqual(str(module.sync_id), "900")
        self.assertEqual(str(module.network_id), "7")

    def test_nom_duplique_n_est_jamais_resolu_arbitrairement(self):
        camera_a = object()
        camera_b = object()
        blink = SimpleNamespace(sync={
            "Maison": SimpleNamespace(cameras={"Entrée": camera_a}),
            "Garage": SimpleNamespace(cameras={"Entrée": camera_b}),
        })

        with self.assertRaisesRegex(RuntimeError, "ambigu"):
            serve.BlinkSession().find_camera(blink, "Entrée")


if __name__ == "__main__":
    unittest.main()
