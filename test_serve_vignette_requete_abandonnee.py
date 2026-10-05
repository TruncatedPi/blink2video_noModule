"""Test à froid de Joël sur la PR #59 : 359 requêtes de vignettes annulées par le
navigateur pendant un défilement rapide, que le serveur fabriquait quand même
par ffmpeg. Une requête dont le client est parti ne doit plus lancer ffmpeg.
Vraies connexions (paire de sockets), ffmpeg simulé."""

from __future__ import annotations

import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["BLINK_BOOTSTRAP"] = "none"
_TEST_HOME = tempfile.TemporaryDirectory(prefix="blink-vignette-abandon-")
os.environ["BLINK_HOME"] = _TEST_HOME.name

import serve  # noqa: E402


class ClientParti(unittest.TestCase):
    def setUp(self):
        self.serveur, self.client = socket.socketpair()
        self.addCleanup(self.serveur.close)
        self.addCleanup(self.client.close)
        self.h = serve.Handler.__new__(serve.Handler)
        self.h.connection = self.serveur

    def test_connexion_ouverte_et_silencieuse_n_est_pas_un_depart(self):
        self.assertFalse(self.h._client_parti())

    def test_connexion_fermee_par_le_navigateur_est_un_depart(self):
        self.client.close()
        self.assertTrue(self.h._client_parti())

    def test_requete_suivante_d_une_connexion_persistante_n_est_pas_un_depart(self):
        self.client.sendall(b"GET /autre HTTP/1.1\r\n")
        self.assertFalse(self.h._client_parti())
        # Et la requête suivante n'a pas été consommée par le contrôle.
        self.assertEqual(self.serveur.recv(4), b"GET ")

    def test_demi_fermeture_apres_envoi_est_un_depart(self):
        self.client.shutdown(socket.SHUT_WR)
        self.assertTrue(self.h._client_parti())

    def test_connexion_deja_fermee_cote_serveur_est_un_depart(self):
        self.serveur.close()
        self.assertTrue(self.h._client_parti())

    def test_sans_connexion_c_est_un_depart(self):
        self.h.connection = None
        self.assertTrue(self.h._client_parti())


class FabricationDesVignettes(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory(prefix="blink-vignette-")
        self.addCleanup(self.dossier.cleanup)
        racine = Path(self.dossier.name)
        self.source = racine / "clip.mp4"
        self.source.write_bytes(b"x" * 100)
        self.h = serve.Handler.__new__(serve.Handler)
        self.h.paths = {"thumbs": racine / "thumbs"}
        self.h.ffmpeg = "ffmpeg-simule"
        self.h.send_error = mock.Mock()
        self.h.send_response = mock.Mock()
        self.h.send_header = mock.Mock()
        self.h.end_headers = mock.Mock()
        self.h.wfile = mock.Mock()
        self.h.headers = {}
        self.h.close_connection = False
        self.lancements = []

        def faux_ffmpeg(commande, **_options):
            self.lancements.append(commande)
            Path(commande[-1]).write_bytes(b"jpeg")
            return mock.Mock(returncode=0)

        patcher = mock.patch.object(serve.runtime, "lancer", side_effect=faux_ffmpeg)
        patcher.start()
        self.addCleanup(patcher.stop)

    def vignette(self):
        return (self.h.paths["thumbs"] / "clip" / "id1").with_suffix(".jpg")

    def test_client_present_la_vignette_est_fabriquee_et_servie(self):
        self.h._client_parti = mock.Mock(return_value=False)
        self.h.send_thumb("clip/id1", self.source)
        self.assertEqual(len(self.lancements), 1)
        self.assertTrue(self.vignette().is_file())
        self.h.send_response.assert_called_with(200)

    def test_client_parti_pendant_la_file_ffmpeg_n_est_pas_lance(self):
        self.h._client_parti = mock.Mock(return_value=True)
        self.h.send_thumb("clip/id1", self.source)
        self.assertEqual(self.lancements, [], "aucun ffmpeg pour une requete abandonnee")
        self.assertFalse(self.vignette().exists())
        self.assertTrue(self.h.close_connection)
        self.h.send_response.assert_not_called()
        self.h.send_error.assert_not_called()

    def test_une_vignette_deja_fabriquee_ne_demande_meme_pas_si_le_client_est_la(self):
        self.vignette().parent.mkdir(parents=True)
        self.vignette().write_bytes(b"jpeg")
        self.h._client_parti = mock.Mock(return_value=True)
        self.h.send_thumb("clip/id1", self.source)
        self.h._client_parti.assert_not_called()
        self.assertEqual(self.lancements, [])
        self.h.send_response.assert_called_with(200)

    def test_le_creneau_est_rendu_quand_le_client_est_parti(self):
        self.h._client_parti = mock.Mock(return_value=True)
        for _ in range(serve.THUMB_SLOTS._value + 3):
            self.h.send_thumb("clip/id1", self.source)
        # Si un creneau fuyait, ces appels bloqueraient ; on le verifie en prenant
        # tous les creneaux disponibles sans attendre.
        pris = 0
        while serve.THUMB_SLOTS.acquire(blocking=False):
            pris += 1
        for _ in range(pris):
            serve.THUMB_SLOTS.release()
        self.assertEqual(pris, min(8, os.cpu_count() or 4))


if __name__ == "__main__":
    unittest.main()
