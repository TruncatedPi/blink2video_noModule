"""Contrôle des processus sans dépendance à PowerShell sur Windows 7."""

from __future__ import annotations

import json
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import runtime
import blink_cli


class TestsIdentitesInstances(unittest.TestCase):
    def setUp(self) -> None:
        self.temporaire = tempfile.TemporaryDirectory(prefix="blink-controle-")
        self.controle = Path(self.temporaire.name)
        self.patch_controle = mock.patch.object(
            runtime, "_dossier_controle", return_value=self.controle)
        self.patch_controle.start()
        self.patch_env = mock.patch.dict(os.environ, {}, clear=False)
        self.patch_env.start()
        os.environ.pop(runtime.INSTANCE_PID_ENV, None)

    def tearDown(self) -> None:
        self.patch_controle.stop()
        self.patch_env.stop()
        self.temporaire.cleanup()

    def test_inscription_memorise_pid_et_creation_de_tous_les_membres(self):
        with mock.patch.object(runtime, "identite_processus",
                               side_effect=lambda pid: f"creation-{pid}"):
            fiche = runtime.inscrire_instance([["serve"]], [222, 333])
        donnees = json.loads(fiche.read_text(encoding="utf-8"))
        self.assertEqual(donnees["identites"][str(os.getpid())],
                         f"creation-{os.getpid()}")
        self.assertEqual(donnees["identites"]["222"], "creation-222")
        self.assertEqual(donnees["identites"]["333"], "creation-333")
        self.assertEqual(os.environ[runtime.INSTANCE_PID_ENV], str(os.getpid()))

    def test_serve_direct_est_inscrit_meme_avec_pid_herite_perime(self):
        os.environ[runtime.INSTANCE_PID_ENV] = "111"
        fiche = runtime.assurer_instance([["serve", "--port", "9000"]])
        donnees = json.loads(fiche.read_text(encoding="utf-8"))
        self.assertEqual(donnees["pid"], os.getpid())
        self.assertEqual(donnees["verbes"], [["serve", "--port", "9000"]])
        self.assertEqual(os.environ[runtime.INSTANCE_PID_ENV], str(os.getpid()))

    def test_serve_enfant_conserve_la_fiche_et_les_travailleurs_du_parent(self):
        pid = os.getpid()
        fiche = self._ecrire_fiche()
        donnees = json.loads(fiche.read_text(encoding="utf-8"))
        donnees.update(enfants=[pid], travailleurs=[333], identites={
            "111": "creation-111", str(pid): "creation-enfant", "333": "ffmpeg"})
        fiche.write_text(json.dumps(donnees), encoding="utf-8")
        with mock.patch.object(runtime, "identite_processus", side_effect=lambda p: {
                111: "creation-111", pid: "creation-enfant", 333: "ffmpeg"}.get(p)), \
             mock.patch.object(runtime, "inscrire_instance") as inscrire:
            self.assertEqual(runtime.assurer_instance([["serve"]]), fiche)
        inscrire.assert_not_called()
        self.assertEqual(os.environ[runtime.INSTANCE_PID_ENV], "111")
        self.assertEqual(json.loads(fiche.read_text())["travailleurs"], [333])

    def test_serve_deja_inscrit_ne_double_pas_sa_fiche(self):
        fiche = runtime.inscrire_instance([["serve"]])
        with mock.patch.object(runtime, "inscrire_instance") as inscrire:
            self.assertEqual(runtime.assurer_instance([["serve"]]), fiche)
        inscrire.assert_not_called()

    def _ecrire_fiche(self, identite="creation-111") -> Path:
        dossier = self.controle / runtime.INSTANCES
        dossier.mkdir(exist_ok=True)
        fiche = dossier / "111.json"
        fiche.write_text(json.dumps({
            "pid": 111, "enfants": [], "travailleurs": [],
            "identites": {"111": identite}, "verbes": [["serve"]],
        }), encoding="utf-8")
        return fiche

    def test_lecture_utilise_creation_native_sans_ligne_de_commande(self):
        self._ecrire_fiche()
        with mock.patch.object(runtime, "identite_processus",
                               return_value="creation-111"), \
             mock.patch.object(runtime, "ligne_de_commande") as ligne:
            instances = runtime.lire_instances()
        self.assertEqual(len(instances), 1)
        ligne.assert_not_called()

    def test_pid_recycle_est_ecarte_par_sa_creation(self):
        fiche = self._ecrire_fiche()
        with mock.patch.object(runtime, "identite_processus",
                               return_value="creation-autre"):
            self.assertEqual(runtime.lire_instances(), [])
        self.assertFalse(fiche.exists())

    def test_identite_illisible_d_un_pid_vivant_conserve_la_fiche(self):
        fiche = self._ecrire_fiche()
        with mock.patch.object(runtime, "identite_processus", return_value=None), \
             mock.patch.object(runtime, "processus_vivant", return_value=True):
            instances = runtime.lire_instances()
        self.assertEqual(len(instances), 1)
        self.assertTrue(fiche.exists())

    def test_travailleur_enfant_enrichit_la_fiche_du_superviseur(self):
        dossier = self.controle / runtime.INSTANCES
        dossier.mkdir()
        fiche = dossier / "111.json"
        fiche.write_text(json.dumps({
            "pid": 111, "enfants": [222], "travailleurs": [],
            "identites": {"111": "parent", "222": "enfant"},
        }), encoding="utf-8")
        os.environ[runtime.INSTANCE_PID_ENV] = "111"
        with mock.patch.object(runtime, "identite_processus",
                               return_value="ffmpeg-creation"):
            runtime.inscrire_travailleur(333)
        donnees = json.loads(fiche.read_text(encoding="utf-8"))
        self.assertEqual(donnees["travailleurs"], [333])
        self.assertEqual(donnees["identites"]["333"], "ffmpeg-creation")

    def test_fiche_ancienne_reste_lisible_sous_powershell_2(self):
        resultat = mock.Mock(stdout="commande blink2video", returncode=0)
        with mock.patch.object(runtime.os, "name", "nt"), \
             mock.patch.object(runtime, "lancer", return_value=resultat) as lancer:
            self.assertEqual(runtime.ligne_de_commande(123), "commande blink2video")
        script = lancer.call_args[0][0][-1]
        self.assertIn("Get-WmiObject", script)
        self.assertIn("Get-Command Get-CimInstance", script)


class TestArretReelIsole(unittest.TestCase):
    def test_stop_retrouve_et_termine_un_processus_cooperatif(self):
        """Exerce le vrai PID/temps de création, sans compte Blink ni popup."""
        with tempfile.TemporaryDirectory(prefix="blink-stop-reel-") as dossier:
            environnement = dict(os.environ, BLINK_HOME=dossier, BLINK_CONTROL_HOME=dossier)
            code = (
                "import time, runtime; "
                "runtime.inscrire_instance([['watch', '--loop', '30']]); "
                "\nwhile not runtime.arret_demande(): time.sleep(0.05)"
            )
            processus = subprocess.Popen(
                [sys.executable, "-c", code], cwd=str(Path(__file__).resolve().parent),
                env=environnement, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                fiches = Path(dossier) / runtime.INSTANCES
                limite = time.monotonic() + 5
                while time.monotonic() < limite and not list(fiches.glob("*.json")):
                    if processus.poll() is not None:
                        self.fail("le processus isolé s'est arrêté avant son inscription")
                    time.sleep(0.05)
                self.assertTrue(list(fiches.glob("*.json")))

                with mock.patch.dict(os.environ, {"BLINK_HOME": dossier, "BLINK_CONTROL_HOME": dossier}, clear=False), \
                     contextlib.redirect_stdout(io.StringIO()):
                    resultat = blink_cli.arreter([])
                self.assertEqual(resultat, 0)
                processus.wait(timeout=5)
                self.assertIsNotNone(processus.returncode)
                self.assertEqual(list(fiches.glob("*.json")), [])
            finally:
                if processus.poll() is None:
                    processus.terminate()
                    processus.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
