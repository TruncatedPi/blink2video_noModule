"""Régressions du moniteur réel, avec réponses Blink brutes sans compte/caméra."""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
import os
import queue
import tempfile
import threading
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

os.environ["BLINK_BOOTSTRAP"] = "none"
_TEST_HOME = tempfile.TemporaryDirectory(prefix="blink-event-poll-")
os.environ["BLINK_HOME"] = _TEST_HOME.name

import blink_events
import serve


class DoorbellPollingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 8, 12, tzinfo=dt.timezone.utc)
        self.home = {
            "doorbells": [
                dict(id=12, network_id=7, name="Front Door", enabled=True,
                     status="online", updated_at=self.now.isoformat()),
                dict(id=13, network_id=8, name="Side Door", enabled=True,
                     status="online", updated_at=self.now.isoformat()),
            ],
            "networks": [dict(id=7, armed=True), dict(id=8, armed=True)],
        }
        self.blink = SimpleNamespace(homescreen=copy.deepcopy(self.home), sync={})
        for db in self.home["doorbells"]:
            camera = SimpleNamespace(device_id=str(db["id"]), network_id=str(db["network_id"]),
                                     attributes={"camera_id": db["id"]})
            self.blink.sync[str(db["network_id"])] = SimpleNamespace(
                network_id=str(db["network_id"]), cameras={db["name"]: camera})

        async def refresh():
            self.blink.homescreen = copy.deepcopy(self.home)

        self.blink.get_homescreen = mock.AsyncMock(side_effect=refresh)
        self.networks = {"7": {"event": []}, "8": {"event": []}}
        self.media = []
        self.request_events = mock.AsyncMock(side_effect=lambda blink, network: self.networks[network])
        self.request_media = mock.AsyncMock(
            side_effect=lambda blink, time, page: {"media": self.media if page == 1 else []})
        self.jobs = queue.Queue()
        self.settings = dict(doorbell_alerts_enabled=True, doorbell_auto_record=True,
                             doorbell_auto_record_seconds=30, doorbell_poll_interval_seconds=6)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for target, attribute, value in (
            (blink_events.api, "request_sync_events", self.request_events),
            (blink_events, "request_event_media", self.request_media),
            (serve, "DOORBELL_EVENTS", []),
            (serve, "DOORBELL_SEEN_EVENTS", {}),
            (serve, "DOORBELL_RECORD_QUEUE", self.jobs),
            (serve, "DOORBELL_MONITOR_ERROR", ""),
            (serve, "MODULE_SLOT_INFO", {}),
        ):
            stack.enter_context(mock.patch.object(target, attribute, value))
        stack.enter_context(mock.patch.object(blink_events.time, "time", side_effect=lambda: self.now.timestamp()))
        stack.enter_context(mock.patch.object(serve, "_sauvegarder_evenements_sonnette"))
        stack.enter_context(mock.patch.object(serve.runtime, "lire_reglages", return_value=self.settings))
        self.stack = stack

    def advance(self, seconds):
        self.now += dt.timedelta(seconds=seconds)
        for db in self.home["doorbells"]:
            db["updated_at"] = self.now.isoformat()

    def raw_event(self, camera=12, network=7, source="pir", **changes):
        event = dict(device_id=camera, network_id=network, type="video", source=source,
                     created_at=self.now.isoformat())
        event.update(changes)
        return event

    async def poll_and_publish(self):
        events = await serve._poll_doorbells_async(self.blink)
        serve._publier_evenements_sonnette(events, self.settings)
        return events

    async def test_heartbeat_horaire_et_reglages_ne_creent_ni_alerte_ni_video(self):
        self.assertEqual(await self.poll_and_publish(), [])
        # Fresh hourly heartbeat while armed used to be classified as motion.
        self.advance(3600)
        self.assertEqual(await self.poll_and_publish(), [])
        for armed in (False, True):
            self.advance(15)
            for db in self.home["doorbells"]:
                db["enabled"] = armed
            for network in self.home["networks"]:
                network["armed"] = armed
            self.assertEqual(await self.poll_and_publish(), [])
        self.assertEqual(serve.DOORBELL_EVENTS, [])
        self.assertTrue(self.jobs.empty())

    async def test_bouton_arme_et_mouvement_apres_desarmement_gardent_type_explicite(self):
        self.networks["7"]["event"] = [self.raw_event(source="button")]
        self.assertEqual((await self.poll_and_publish())[0]["type"], "ring")
        self.advance(5)
        self.home["doorbells"][0]["enabled"] = False
        self.home["networks"][0]["armed"] = False
        self.networks["7"]["event"] = [self.raw_event()]
        self.assertEqual((await self.poll_and_publish())[0]["type"], "motion")
        self.assertEqual([e["type"] for e in serve.DOORBELL_EVENTS], ["ring", "motion"])
        self.assertEqual(self.jobs.qsize(), 2)
        for event in serve.DOORBELL_EVENTS:
            self.assertTrue(event["camera_key"].startswith("camera-"))
            self.assertEqual(event["recording_status"], "pending")

    async def test_direct_et_reveil_ne_masquent_pas_les_evenements_distincts(self):
        for activity, camera in (("direct MSE", "Side Door"), ("direct MSE", "Front Door"),
                                 ("direct WebRTC", "Side Door"), ("reveil", "Front Door"),
                                 ("snapshot", "Side Door")):
            with self.subTest(activity=activity, camera=camera):
                self.advance(5)
                serve.MODULE_SLOT_INFO.update(quoi=activity, camera=camera)
                self.networks["7"]["event"] = [self.raw_event(source="button")]
                self.assertEqual(len(await self.poll_and_publish()), 1)
                await self.poll_and_publish()  # Replay must not queue a second job.
        self.assertEqual(len(serve.DOORBELL_EVENTS), 5)
        self.assertEqual(self.jobs.qsize(), 5)

    async def test_releve_puis_evenement_reseau_media_meme_date_ne_filment_qu_une_fois(self):
        await self.poll_and_publish()
        self.advance(15)
        self.home["doorbells"][0]["updated_at"] = self.now.isoformat().replace("+00:00", "Z")
        # A wakeup alone must not manufacture a first job before the real event arrives.
        self.assertEqual(await self.poll_and_publish(), [])
        event = self.raw_event(created_at=self.home["doorbells"][0]["updated_at"])
        self.networks["7"]["event"] = [event]
        self.media = [dict(event, created_at=self.now.isoformat(), id=999)]
        events = await self.poll_and_publish()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["timestamp"], self.now.isoformat())
        await self.poll_and_publish()
        self.assertEqual(len(serve.DOORBELL_EVENTS), 1)
        self.assertEqual(self.jobs.qsize(), 1)

    async def test_evenement_premier_reseau_ne_prive_pas_autre_sonnette_du_repli_media(self):
        self.networks["7"]["event"] = [self.raw_event()]
        self.networks["8"] = None  # Standalone setup lacks a network event inventory.
        self.assertEqual(len(await self.poll_and_publish()), 1)
        self.advance(15)
        self.media = [self.raw_event(camera=13, network=8, source="button")]
        events = await self.poll_and_publish()
        self.assertEqual({e["camera"] for e in events}, {"Front Door", "Side Door"})
        self.assertEqual(len(serve.DOORBELL_EVENTS), 2)
        self.assertEqual(self.jobs.qsize(), 2)
        self.assertEqual(serve.DOORBELL_EVENTS[1]["type"], "ring")
        self.assertNotEqual(serve.DOORBELL_EVENTS[0]["camera_key"],
                            serve.DOORBELL_EVENTS[1]["camera_key"])
        self.request_events.assert_any_await(self.blink, "8")

    async def test_erreur_homescreen_ne_reutilise_pas_releve_cache(self):
        await self.poll_and_publish()
        self.advance(15)
        self.blink.homescreen = copy.deepcopy(self.home)
        self.blink.get_homescreen.side_effect = OSError("Blink connection lost")
        self.request_events.reset_mock()
        self.request_media.reset_mock()
        with self.assertRaisesRegex(OSError, "Blink connection lost"):
            await self.poll_and_publish()
        self.request_events.assert_not_awaited()
        self.request_media.assert_not_awaited()
        self.assertTrue(self.jobs.empty())

    async def test_inventaires_invalides_restent_une_erreur_du_moniteur(self):
        self.networks.update({"7": None, "8": None})
        self.request_media.side_effect = None
        self.request_media.return_value = None
        with self.assertRaisesRegex(RuntimeError, "aucun inventaire"):
            await self.poll_and_publish()
        self.assertTrue(self.jobs.empty())

    async def test_moniteur_affiche_erreur_de_connexion(self):
        self.blink.get_homescreen.side_effect = OSError("Blink connection lost")
        stop = threading.Event()
        blink_worker = SimpleNamespace(call=lambda factory, timeout: asyncio.run(factory(self.blink)))
        with mock.patch.object(stop, "wait", side_effect=lambda interval: stop.set()), \
             mock.patch.object(serve, "DOORBELL_MONITOR_STOP", stop), \
             mock.patch.object(serve, "BLINK", blink_worker):
            await asyncio.to_thread(serve._doorbell_monitor_loop)
        self.assertIn("Blink connection lost", serve.DOORBELL_MONITOR_ERROR)
        self.request_events.assert_not_awaited()
        self.assertEqual(serve.DOORBELL_EVENTS, [])
        self.assertTrue(self.jobs.empty())


if __name__ == "__main__":
    unittest.main()
