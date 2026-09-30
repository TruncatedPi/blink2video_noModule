"""Validation MP4 rapide pour les listings, approfondie pour l'ingestion."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import merge_daily


def boite(nom: bytes, contenu: bytes = b"") -> bytes:
    return (len(contenu) + 8).to_bytes(4, "big") + nom + contenu


FTYP = boite(b"ftyp", b"isom\x00\x00\x02\x00isomiso2")
MP4_STRUCTUREL = FTYP + boite(b"moov") + boite(b"mdat", b"paquet-video")
FMP4_STRUCTUREL = (
    FTYP + boite(b"moov") + boite(b"moof", b"fragment")
    + boite(b"mdat", b"paquet-fragmente")
)


class TestsValidMp4(unittest.TestCase):
    def setUp(self) -> None:
        self.temporaire = tempfile.TemporaryDirectory(prefix="blink_valid_mp4_")
        self.racine = Path(self.temporaire.name)

    def tearDown(self) -> None:
        self.temporaire.cleanup()

    def test_mp4_classique_est_reconnu_structurellement(self):
        chemin = self.racine / "video.mp4"
        chemin.write_bytes(MP4_STRUCTUREL)
        self.assertTrue(merge_daily.valid_mp4(chemin))

    def test_mp4_fragmente_est_reconnu_structurellement(self):
        chemin = self.racine / "video-fragmente.mp4"
        chemin.write_bytes(FMP4_STRUCTUREL)
        self.assertTrue(merge_daily.valid_mp4(chemin))

    def test_ftyp_seul_meme_long_n_est_jamais_valide(self):
        chemin = self.racine / "tronque.mp4"
        chemin.write_bytes(FTYP + b"\x00" * 100)
        self.assertFalse(merge_daily.valid_mp4(chemin))

    def test_boite_declaree_plus_longue_que_le_fichier_est_rejetee(self):
        chemin = self.racine / "mdat-tronque.mp4"
        chemin.write_bytes(
            FTYP + boite(b"moov") + (4096).to_bytes(4, "big") + b"mdat" + b"court",
        )
        self.assertFalse(merge_daily.valid_mp4(chemin))

    def test_fichier_sans_ftyp_n_est_pas_valide(self):
        chemin = self.racine / "video.mp4"
        chemin.write_bytes(b"\x00" * 64)
        self.assertFalse(merge_daily.valid_mp4(chemin))

    def test_fichier_vide_n_est_pas_valide(self):
        chemin = self.racine / "video.mp4"
        chemin.touch()
        self.assertFalse(merge_daily.valid_mp4(chemin))

    def test_fichier_absent_n_est_pas_valide(self):
        self.assertFalse(merge_daily.valid_mp4(self.racine / "absent.mp4"))

    def test_ne_lit_pas_le_fichier_entier(self):
        """Bug corrigé le 18 août 2026 : l'ancienne implémentation
        (``read_bytes()[:64]``) chargeait le fichier entier en mémoire avant
        de ne garder que les 64 premiers octets — invisible sur un clip,
        coûteux sur une vidéo assemblée de plusieurs centaines de Mo à
        quelques Go (vu en vrai : /api/videos passait de plus de 60 s à
        moins de 3 s sur les mêmes 19 fichiers après ce correctif, sans
        rapport avec ffmpeg — le sondage de durée, déjà en cache, n'était
        pas la cause). Vérifié ici en s'assurant qu'aucune lecture totale
        n'a lieu, quelle que soit la taille réelle du fichier de test."""
        chemin = self.racine / "video.mp4"
        chemin.write_bytes(MP4_STRUCTUREL)
        with mock.patch.object(Path, "read_bytes") as lecture_totale:
            self.assertTrue(merge_daily.valid_mp4(chemin))
        lecture_totale.assert_not_called()

    def test_listing_structurel_ne_lance_aucun_sous_processus(self):
        chemin = self.racine / "video.mp4"
        chemin.write_bytes(FMP4_STRUCTUREL)
        with mock.patch.object(merge_daily.runtime, "lancer") as lancer:
            self.assertTrue(merge_daily.valid_mp4(chemin))
        lancer.assert_not_called()

    def test_validation_complete_exige_une_sonde_sans_erreur(self):
        chemin = self.racine / "video.mp4"
        chemin.write_bytes(MP4_STRUCTUREL)
        succes = SimpleNamespace(returncode=0, stdout="3\n", stderr="")
        with mock.patch.object(
            merge_daily, "_outil_validation_media", return_value=("ffprobe", "ffprobe"),
        ), mock.patch.object(merge_daily.runtime, "lancer", return_value=succes) as lancer:
            self.assertTrue(merge_daily.valid_mp4_complet(chemin))
        self.assertIn("-count_packets", lancer.call_args.args[0])

        tronque = SimpleNamespace(returncode=1, stdout="", stderr="partial file")
        with mock.patch.object(
            merge_daily, "_outil_validation_media", return_value=("ffprobe", "ffprobe"),
        ), mock.patch.object(merge_daily.runtime, "lancer", return_value=tronque):
            self.assertFalse(merge_daily.valid_mp4_complet(chemin))

    def _sonde(self, stdout: str, stderr: str, returncode: int = 0) -> bool:
        chemin = self.racine / "clip.mp4"
        chemin.write_bytes(MP4_STRUCTUREL)
        reponse = SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
        with mock.patch.object(
            merge_daily, "_outil_validation_media", return_value=("ffprobe", "ffprobe"),
        ), mock.patch.object(merge_daily.runtime, "lancer", return_value=reponse):
            return merge_daily.valid_mp4_complet(chemin)

    # Lignes réelles, capturées le 2026-09-30 avec le ffprobe du paquet Linux
    # 0.15.4 sur de vrais clips Blink (issue #49).

    def test_clip_usb_intact_accepte_malgre_le_bruit_de_l_analyseur_h264(self):
        # Chaque clip USB du Sync Module : 922 paquets lus, code 0, et cette
        # seule ligne. Refusée, elle faisait rejeter tous les clips USB.
        self.assertTrue(self._sonde(
            "922\n", "[h264 @ 0x5df4102b1480] missing picture in access unit with size 9\n"))

    def test_bruit_repete_ou_venu_de_l_analyseur_reste_du_bruit(self):
        self.assertTrue(self._sonde(
            "331\n",
            "[NULL @ 0x63ed87021880] missing picture in access unit with size 9\n"
            "    Last message repeated 2 times\n"))

    def test_clip_tronque_reste_refuse_meme_avec_le_bruit_connu(self):
        # Copie coupée à 50 % : le même bruit, plus la vraie trace de la coupure.
        self.assertFalse(self._sonde(
            "369\n",
            "[NULL @ 0x599bb886b880] missing picture in access unit with size 9\n"
            "[h264 @ 0x59c11469e880] Invalid NAL unit size (3302 > 762).\n"))

    def test_une_erreur_repetee_reste_une_erreur(self):
        self.assertFalse(self._sonde(
            "299\n",
            "[h264 @ 0x5d890c6e7880] Invalid NAL unit size (2246 > 1500).\n"
            "    Last message repeated 3 times\n"))

    def test_toute_autre_ligne_d_erreur_fait_toujours_refuser(self):
        # Échec fermé : seul le bruit connu est toléré, jamais une ligne inconnue.
        self.assertFalse(self._sonde(
            "451\n",
            "[mov,mp4,m4a,3gp,3g2,mj2 @ 0x5d07d1bef880] stream 0, offset 0x2a3f1: partial file\n"))


if __name__ == "__main__":
    unittest.main()
