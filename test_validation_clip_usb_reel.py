"""Issue #49 : un VRAI clip USB de Sync Module dans la suite de tests.

Le défaut de #49 (chaque clip USB rejeté en silence par la validation de
ffprobe, depuis la 0.12.29) a échappé à la CI parce qu'elle n'avait que des clips
fabriqués par FFmpeg, et des tests qui simulaient la réponse de ffprobe. Ce
clip, enregistré sur une vraie clé USB, déclenche la ligne
« missing picture in access unit with size 9 » : la vraie validation doit
l'accepter, avec l'outil que la machine fournit (ffprobe, sinon ffmpeg).

Sautés sans ffprobe ni ffmpeg ; la CI Linux (job « chaîne vidéo ») installe
FFmpeg, donc y tourne."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

import merge_daily

CLIP = Path(__file__).parent / "fixtures" / "clip_usb_reel_neutre.mp4"
# Empreinte du clip tel que publié : un clip retouché, ou converti par une fin
# de ligne, ne prouverait plus rien.
SHA256 = "0089741365600fa231020176f3d761ce07e8f56a9dfbfde422a2ad204afd8aee"


class ClipUsbReel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CLIP.is_file():
            raise unittest.SkipTest("clip de test absent")
        if merge_daily._outil_validation_media() is None:
            raise unittest.SkipTest("ni ffprobe ni ffmpeg disponibles")
        cls.genre, cls.exe = merge_daily._outil_validation_media()

    def test_le_fichier_publie_est_intact(self):
        self.assertEqual(hashlib.sha256(CLIP.read_bytes()).hexdigest(), SHA256,
                         "le clip de test a ete modifie")

    def test_c_est_bien_un_clip_usb_a_un_seul_bloc_de_donnees(self):
        # Structure des clips USB : ftyp, moov, un seul mdat (pas fragmenté comme
        # un enregistrement du direct).
        donnees = CLIP.read_bytes()
        genres, pos = [], 0
        while pos + 8 <= len(donnees):
            taille = int.from_bytes(donnees[pos:pos + 4], "big")
            genres.append(donnees[pos + 4:pos + 8].decode("latin-1"))
            if taille < 8:
                break
            pos += taille
        self.assertEqual(genres, ["ftyp", "moov", "mdat"])
        self.assertEqual(donnees[8:12], b"isom")

    def test_la_vraie_validation_accepte_le_clip(self):
        self.assertTrue(merge_daily.valid_mp4_complet(CLIP), merge_daily.raison_refus_mp4(CLIP))

    def test_la_sortie_de_ffprobe_ne_laisse_rien_de_refusable(self):
        if self.genre != "ffprobe":
            self.skipTest("la sonde de cette machine est ffmpeg")
        resultat = subprocess.run(
            [self.exe, "-v", "error", "-select_streams", "v:0", "-count_packets",
             "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(CLIP)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(resultat.returncode, 0)
        self.assertGreater(int(resultat.stdout.split()[0]), 0)
        # Selon la version de FFmpeg, la ligne de #49 est émise ou non ; dans
        # tous les cas, le filtre n'en doit rien garder. L'ancienne règle
        # (« toute ligne d'erreur = refus ») rejetait ce clip dès qu'elle l'était.
        self.assertEqual(merge_daily._erreurs_ffprobe(resultat.stderr), [])

    def test_des_copies_tronquees_du_vrai_clip_sont_refusees(self):
        donnees = CLIP.read_bytes()
        with tempfile.TemporaryDirectory(prefix="blink_clip_usb_") as dossier:
            for part in (0.5, 0.9, 0.999):
                copie = Path(dossier) / f"coupe_{int(part * 1000)}.mp4"
                copie.write_bytes(donnees[: int(len(donnees) * part)])
                with self.subTest(part=part):
                    self.assertFalse(merge_daily.valid_mp4_complet(copie))


if __name__ == "__main__":
    unittest.main()
