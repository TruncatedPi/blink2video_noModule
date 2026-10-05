"""FFmpeg du paquet Linux : version figée et empreinte vérifiée (issue #49).

Avant, build.py téléchargeait à chaque construction la compilation nocturne de
BtbN (adresse « latest ») et l'embarquait sans la vérifier : deux releases
construites à un jour d'écart pouvaient livrer deux FFmpeg différents."""

from __future__ import annotations

import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build


class ConstantesFigees(unittest.TestCase):
    def test_l_adresse_vise_une_construction_datee_et_une_archive_precise(self):
        self.assertIn("/releases/download/autobuild-", build.FFMPEG_SECOURS)
        self.assertNotIn("/download/latest/", build.FFMPEG_SECOURS)
        self.assertTrue(build.FFMPEG_SECOURS.endswith(build.FFMPEG_SECOURS_ARCHIVE))
        self.assertIn(build.FFMPEG_SECOURS_TAG, build.FFMPEG_SECOURS)

    def test_branche_stable_et_pas_la_branche_de_developpement(self):
        # « master » et « latest » changent chaque nuit ; une branche de
        # version (nX.Y) ne reçoit que des correctifs.
        self.assertRegex(build.FFMPEG_SECOURS_ARCHIVE, r"^ffmpeg-n\d+\.\d+\.\d+-")
        self.assertNotIn("master", build.FFMPEG_SECOURS_ARCHIVE)

    def test_l_empreinte_est_un_sha256_complet_en_minuscules(self):
        self.assertRegex(build.FFMPEG_SECOURS_SHA256, r"^[0-9a-f]{64}$")


class VerificationDeLEmpreinte(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory(prefix="blink_ffmpeg_")
        self.addCleanup(self.dossier.cleanup)
        self.chemin = Path(self.dossier.name) / "archive.tar.xz"
        self.chemin.write_bytes(b"contenu de test" * 100_000)
        self.attendue = hashlib.sha256(self.chemin.read_bytes()).hexdigest()

    def test_empreinte_correcte_acceptee_meme_en_majuscules(self):
        self.assertTrue(build.verifier_empreinte(self.chemin, self.attendue))
        self.assertTrue(build.verifier_empreinte(self.chemin, self.attendue.upper()))

    def test_un_octet_change_est_refuse(self):
        donnees = bytearray(self.chemin.read_bytes())
        donnees[1234] ^= 1
        self.chemin.write_bytes(bytes(donnees))
        self.assertFalse(build.verifier_empreinte(self.chemin, self.attendue))

    def test_une_archive_tronquee_est_refusee(self):
        self.chemin.write_bytes(self.chemin.read_bytes()[:-1])
        self.assertFalse(build.verifier_empreinte(self.chemin, self.attendue))


class TelechargementVerifie(unittest.TestCase):
    """La branche de secours Linux de ffmpeg_utilisable(), sans réseau."""

    def appeler(self, contenu_telecharge: bytes | None, deja_la: bytes | None = None):
        dossier = tempfile.TemporaryDirectory(prefix="blink_ffmpeg_")
        self.addCleanup(dossier.cleanup)
        travail = Path(dossier.name)
        archive = travail / "ffmpeg-linux.tar.xz"
        if deja_la is not None:
            archive.write_bytes(deja_la)
        telechargements = []

        def faux_urlretrieve(url, cible):
            telechargements.append(url)
            Path(cible).write_bytes(contenu_telecharge)

        # sait_ecrire() ne doit jamais lancer le faux binaire, et python n'est
        # pas requis : on arrête la fonction juste après la vérification.
        python = Path(dossier.name) / "faux-python"
        with mock.patch("sys.platform", "linux"), \
             mock.patch("urllib.request.urlretrieve", faux_urlretrieve), \
             mock.patch.object(build.subprocess, "run", side_effect=OSError("pas ici")):
            try:
                build.ffmpeg_utilisable(python, travail)
            except SystemExit as erreur:
                return telechargements, str(erreur), archive
            except Exception as erreur:  # tar illisible : la vérification a passé
                return telechargements, "tar:" + type(erreur).__name__, archive
        return telechargements, "", archive

    def test_une_archive_qui_n_a_pas_la_bonne_empreinte_arrete_la_construction(self):
        telechargements, message, archive = self.appeler(b"pas la bonne archive")
        self.assertEqual(telechargements, [build.FFMPEG_SECOURS])
        self.assertIn("pas l'empreinte attendue", message)
        self.assertIn(build.FFMPEG_SECOURS_SHA256, message)
        self.assertFalse(archive.exists(), "l'archive refusée ne doit pas rester")

    def test_une_copie_en_cache_de_mauvaise_empreinte_est_retelechargee(self):
        telechargements, message, _ = self.appeler(b"toujours faux", deja_la=b"ancienne version")
        self.assertEqual(telechargements, [build.FFMPEG_SECOURS])
        self.assertIn("pas l'empreinte attendue", message)

    def test_la_bonne_archive_passe_la_verification(self):
        # Une archive qui a l'empreinte épinglée passe ; ici on la fabrique en
        # substituant l'empreinte, jamais en affaiblissant le contrôle.
        contenu = b"archive reputee valide"
        with mock.patch.object(build, "FFMPEG_SECOURS_SHA256",
                               hashlib.sha256(contenu).hexdigest()):
            _, message, _ = self.appeler(contenu)
        self.assertNotIn("pas l'empreinte attendue", message)


if __name__ == "__main__":
    unittest.main()
