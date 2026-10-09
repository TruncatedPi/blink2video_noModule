"""Aucun remplacement ni redémarrage tant que l'arrêt n'est pas confirmé."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import maj


class TestFinaliserArret(unittest.TestCase):
    def setUp(self):
        temporaire = tempfile.TemporaryDirectory(prefix="blink-finaliser-arret-")
        self.addCleanup(temporaire.cleanup)
        donnees = Path(temporaire.name) / "donnees"
        controle = Path(temporaire.name) / "controle"
        donnees.mkdir()
        controle.mkdir()
        environnement = mock.patch.dict(os.environ, {
            "BLINK_HOME": str(donnees),
            "BLINK_CONTROL_HOME": str(controle),
        })
        environnement.start()
        self.addCleanup(environnement.stop)

    def executer(self, code_arret, vivants):
        fiches = [{"pid": 123, "verbes": [["serve"]]}]
        with tempfile.TemporaryDirectory() as dossier, \
                mock.patch.object(maj.runtime, "frozen", return_value=False), \
                mock.patch.object(maj.runtime, "lire_instances", side_effect=[
                    fiches, *[fiches if vivant else [] for vivant in vivants]]), \
                mock.patch.object(maj.runtime, "lancer", return_value=mock.Mock(
                    returncode=code_arret)), \
                mock.patch.object(maj.time, "sleep"), \
                mock.patch.object(maj, "_permuter", return_value=True) as permuter, \
                mock.patch.object(maj, "_relancer") as relancer:
            code = maj.finaliser(Path(dossier))
        return code, permuter, relancer

    def test_arret_echoue_ne_remplace_et_ne_relance_pas(self):
        code, permuter, relancer = self.executer(1, [True] * 20)
        self.assertEqual(code, 1)
        permuter.assert_not_called()
        relancer.assert_not_called()
        travail = maj.runtime.travail_affichable()
        self.assertEqual(travail["cle"], "phase.update_noop")
        self.assertEqual(travail["quoi"], maj.msg("arret_echoue"))
        self.assertTrue(travail["termine"])
        self.assertFalse(travail["actif"])

    def test_arret_reussi_mais_instance_survivante_refuse_la_mise_a_jour(self):
        code, permuter, relancer = self.executer(0, [True] * 20)
        self.assertEqual(code, 1)
        permuter.assert_not_called()
        relancer.assert_not_called()
        travail = maj.runtime.travail_affichable()
        self.assertEqual(travail["cle"], "phase.update_noop")
        self.assertEqual(travail["quoi"], maj.msg("instance_encore_active"))
        self.assertTrue(travail["termine"])
        self.assertFalse(travail["actif"])

    def test_arret_confirme_apres_attente_autorise_la_mise_a_jour(self):
        code, permuter, relancer = self.executer(0, [True, True, False])
        self.assertEqual(code, 0)
        permuter.assert_called_once()
        relancer.assert_called_once()
        self.assertEqual(maj.runtime.travail_affichable(), {})

    def test_parent_mort_mais_enfant_ou_travailleur_survivant_refuse_la_mise_a_jour(self):
        for champ in ("enfants", "travailleurs"):
            with self.subTest(champ=champ), tempfile.TemporaryDirectory() as dossier, \
                    mock.patch.object(maj.runtime, "frozen", return_value=False), \
                    mock.patch.object(maj.runtime, "lire_instances", return_value=[
                        {"pid": 123, champ: [456], "verbes": [["serve"]]}]), \
                    mock.patch.object(maj.runtime, "processus_vivant", side_effect=lambda pid: pid == 456), \
                    mock.patch.object(maj.runtime, "lancer", return_value=mock.Mock(returncode=0)), \
                    mock.patch.object(maj.time, "sleep"), \
                    mock.patch.object(maj, "_permuter") as permuter, \
                    mock.patch.object(maj, "_relancer") as relancer:
                code = maj.finaliser(Path(dossier))

                self.assertEqual(code, 1)
                permuter.assert_not_called()
                relancer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
