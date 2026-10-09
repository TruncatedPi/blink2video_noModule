"""Armer une caméra depuis la page laissait son bouton rouge, alors que celui du
hub passait au vert (constaté en réel le 2026-10-05, caméra « Salon »).

Cause : describe_camera() lit camera.motion_enabled, que blinkpy ne met pas à
jour après async_arm() et que system_state() ne rafraîchit plus depuis son
allègement du 2026-09-03. set_armed() suit maintenant la commande et pose la
valeur confirmée. Fausse caméra et fausse session : aucun appel réel à Blink."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ["BLINK_BOOTSTRAP"] = "none"
_TEST_HOME = tempfile.TemporaryDirectory(prefix="blink-armement-camera-")
os.environ["BLINK_HOME"] = _TEST_HOME.name

import serve  # noqa: E402


class FausseCamera:
    network_id = "7"
    attributes: dict = {}

    def __init__(self, reponse, motion_enabled=False):
        self.reponse = reponse
        self.motion_enabled = motion_enabled
        self.appels = []

    async def async_arm(self, valeur):
        self.appels.append(valeur)
        return self.reponse


class FauxSysteme:
    def __init__(self):
        self.appels = []

    async def async_arm(self, valeur):
        self.appels.append(valeur)


def faux_blink():
    return SimpleNamespace(sync={})


class _Base(unittest.TestCase):
    def setUp(self):
        self.handler = serve.Handler.__new__(serve.Handler)
        self.blink = faux_blink()

        def appeler(factory, timeout=60.0):
            return asyncio.run(factory(self.blink))

        for cible, valeur in (("call", appeler),):
            patcher = mock.patch.object(serve.BLINK, cible, side_effect=valeur)
            patcher.start()
            self.addCleanup(patcher.stop)

    def installer(self, camera):
        patcher = mock.patch.object(serve.BLINK, "find_camera", return_value=(None, camera))
        patcher.start()
        self.addCleanup(patcher.stop)

    def commande(self, retour=True, **kw):
        """Remplace blinkpy.api.wait_for_command."""
        patcher = mock.patch("blinkpy.api.wait_for_command", new=mock.AsyncMock(return_value=retour, **kw))
        faux = patcher.start()
        self.addCleanup(patcher.stop)
        return faux


class ArmementDUneCamera(_Base):
    REPONSE = {"id": 4242, "network_id": 7}

    def test_le_cas_du_rapport_la_camera_apparait_armee_apres_l_avoir_armee(self):
        camera = FausseCamera(self.REPONSE, motion_enabled=False)
        self.installer(camera)
        self.commande(True)
        avant = self.handler.describe_camera("Salon", camera, {})["armed"]
        self.handler.set_armed("camera", "cle-salon", True)
        apres = self.handler.describe_camera("Salon", camera, {})["armed"]
        self.assertIs(avant, False)
        self.assertIs(apres, True, "le bouton doit passer au vert")
        self.assertEqual(camera.appels, [True])

    def test_desarmer_met_aussi_l_etat_a_jour(self):
        camera = FausseCamera(self.REPONSE, motion_enabled=True)
        self.installer(camera)
        self.commande(True)
        self.handler.set_armed("camera", "cle-salon", False)
        self.assertIs(camera.motion_enabled, False)

    def test_la_commande_est_suivie_avec_son_identifiant(self):
        camera = FausseCamera({"id": 4242}, motion_enabled=False)
        self.installer(camera)
        faux = self.commande(True)
        self.handler.set_armed("camera", "cle-salon", True)
        faux.assert_awaited_once()
        envoye = faux.await_args.args[1]
        self.assertEqual(envoye["id"], 4242)
        self.assertEqual(envoye["network_id"], "7", "repli sur le reseau de la camera")

    def test_blink_ne_confirme_pas_l_etat_reste_et_l_erreur_est_lisible(self):
        camera = FausseCamera(self.REPONSE, motion_enabled=False)
        self.installer(camera)
        self.commande(False)
        with self.assertRaises(RuntimeError) as erreur:
            self.handler.set_armed("camera", "cle-salon", True)
        self.assertIn("n'a pas confirmé", str(erreur.exception))
        self.assertIs(camera.motion_enabled, False, "pas d'etat affirme sans confirmation")

    def test_confirmation_trop_lente_est_une_erreur_pas_un_blocage(self):
        camera = FausseCamera(self.REPONSE, motion_enabled=False)
        self.installer(camera)

        async def jamais(*_args, **_kwargs):
            await asyncio.sleep(30)
            return True

        patcher = mock.patch("blinkpy.api.wait_for_command", new=jamais)
        patcher.start()
        self.addCleanup(patcher.stop)
        with mock.patch.object(serve, "DELAI_CONFIRMATION_ARMEMENT", 0.05):
            with self.assertRaises(RuntimeError) as erreur:
                self.handler.set_armed("camera", "cle-salon", True)
        self.assertIn("n'a pas confirmé", str(erreur.exception))
        self.assertIs(camera.motion_enabled, False)

    def test_commande_refusee_sans_identifiant(self):
        for refus in (None, False, {}, {"message": "System is busy"}, "texte"):
            with self.subTest(refus=refus):
                camera = FausseCamera(refus, motion_enabled=False)
                self.installer(camera)
                faux = self.commande(True)
                with self.assertRaises(RuntimeError) as erreur:
                    self.handler.set_armed("camera", "cle-salon", True)
                self.assertIn("refusé", str(erreur.exception))
                faux.assert_not_awaited()
                self.assertIs(camera.motion_enabled, False)


class ArmementDUnSysteme(_Base):
    def test_le_hub_garde_son_chemin_sans_attente_de_commande(self):
        systeme = FauxSysteme()
        with mock.patch.object(serve.BLINK, "find_system", return_value=systeme):
            faux = self.commande(True)
            self.handler.set_armed("system", "cle-hub", True)
        self.assertEqual(systeme.appels, [True])
        faux.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
