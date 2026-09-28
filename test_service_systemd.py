"""Non-régression de l'issue #35 (2026-09-27, MarkusKress) : sous le service
systemd utilisateur posé par « autostart on », une mise à jour lancée depuis
la page, comme Appliquer dans les réglages, laissait blink2video arrêté.
La seconde étape (finaliseur de « update », « restart --finaliser ») restait
dans le cgroup de l'unité malgré start_new_session ; quand « stop » faisait
sortir le processus principal, systemd tuait tout le cgroup avec lui, avant
toute relance.

Désormais la seconde étape se relance hors de l'unité (systemd-run --user
--scope), puis relance le service par « systemctl --user start ». Ces tests
simulent /proc/self/cgroup et les commandes : ils tournent sur tous les OS,
la preuve sur un vrai systemd restant l'expérience sur runner Ubuntu."""
from __future__ import annotations

import contextlib
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import autostart
import blink_cli
import maj

UNITE = "blink2video-start.service"
ENV = {"XDG_RUNTIME_DIR": "/run/user/1000", "PATH": "/usr/bin"}


def _cgroup(texte: str) -> Path:
    fichier = Path(tempfile.mkdtemp()) / "cgroup"
    fichier.write_text(texte, encoding="utf-8")
    return fichier


class TestsUniteSystemd(unittest.TestCase):
    def _unite(self, texte, plateforme="linux"):
        with mock.patch.object(autostart.sys, "platform", plateforme):
            return autostart.unite_systemd(_cgroup(texte))

    def test_cgroup_v2_dans_l_unite(self):
        self.assertEqual(self._unite(
            "0::/user.slice/user-1000.slice/user@1000.service/app.slice/"
            "blink2video-start.service\n"), UNITE)

    def test_cgroup_v1_lignes_nommees(self):
        self.assertEqual(self._unite(
            "12:pids:/user.slice/user-1000.slice/user@1000.service/"
            "blink2video-serve.service\n"
            "1:name=systemd:/user.slice/user-1000.slice/user@1000.service/"
            "blink2video-serve.service\n"), "blink2video-serve.service")

    def test_hors_d_une_unite_blink2video(self):
        for texte in ("0::/user.slice/user-1000.slice/session-3.scope\n",
                      "0::/user.slice/user-1000.slice/user@1000.service/app.slice/"
                      "autre.service\n",
                      "0::/user.slice/user-1000.slice/user@1000.service/app.slice/"
                      "run-r1234.scope\n"):
            with self.subTest(texte=texte):
                self.assertEqual(self._unite(texte), "")

    def test_cgroup_illisible_ou_autre_os(self):
        with mock.patch.object(autostart.sys, "platform", "linux"):
            self.assertEqual(autostart.unite_systemd(Path(tempfile.mkdtemp()) / "absent"), "")
        self.assertEqual(self._unite(
            "0::/user.slice/blink2video-start.service\n", plateforme="darwin"), "")


class TestsSortirDuService(unittest.TestCase):
    def _sortir(self, unite=UNITE, essai=0, environ=None, erreur=None):
        lancer = mock.Mock(return_value=types.SimpleNamespace(returncode=essai))
        if erreur is not None:
            lancer.side_effect = erreur
        with mock.patch.object(autostart, "unite_systemd", return_value=unite), \
                mock.patch.object(autostart.runtime, "lancer", lancer), \
                mock.patch.object(autostart.runtime, "demarrer") as demarrer:
            resultat = autostart.sortir_du_service(
                ["blink2video", "restart", "--finaliser"], environ or dict(ENV))
        return resultat, lancer, demarrer

    def test_dans_l_unite_relance_hors_du_cgroup(self):
        resultat, lancer, demarrer = self._sortir()
        self.assertTrue(resultat)
        # Un essai à vide d'abord : sans lui, un systemd-run en échec après
        # notre départ ne laisserait personne pour finir le travail.
        self.assertEqual(lancer.call_args[0][0][-1], "true")
        commande = demarrer.call_args[0][0]
        self.assertEqual(commande[:5], ["systemd-run", "--user", "--scope", "--quiet", "--"])
        self.assertEqual(commande[5:], ["blink2video", "restart", "--finaliser"])
        self.assertEqual(demarrer.call_args[1]["env"][autostart.UNITE_ENV], UNITE)

    def test_hors_d_une_unite_rien_ne_change(self):
        resultat, lancer, demarrer = self._sortir(unite="")
        self.assertFalse(resultat)
        lancer.assert_not_called()
        demarrer.assert_not_called()

    def test_deja_sorti_ne_boucle_pas(self):
        resultat, _, demarrer = self._sortir(
            environ=dict(ENV, **{autostart.UNITE_ENV: UNITE}))
        self.assertFalse(resultat)
        demarrer.assert_not_called()

    def test_systemd_run_en_echec_ou_absent(self):
        for options in ({"essai": 1}, {"erreur": FileNotFoundError("systemd-run")},
                        {"erreur": subprocess.TimeoutExpired("systemd-run", 30)}):
            with self.subTest(**{k: str(v) for k, v in options.items()}):
                resultat, _, demarrer = self._sortir(**options)
                self.assertFalse(resultat)
                demarrer.assert_not_called()


class TestsRelancerService(unittest.TestCase):
    def _relancer(self, environ, code=0, erreur=None):
        lancer = mock.Mock(return_value=types.SimpleNamespace(returncode=code))
        if erreur is not None:
            lancer.side_effect = erreur
        with mock.patch.object(autostart.runtime, "lancer", lancer):
            return autostart.relancer_service(environ), lancer

    def test_relance_l_unite_quittee(self):
        unite, lancer = self._relancer(dict(ENV, **{autostart.UNITE_ENV: UNITE}))
        self.assertEqual(unite, UNITE)
        self.assertEqual(lancer.call_args[0][0], ["systemctl", "--user", "start", UNITE])

    def test_sans_unite_quittee_rien_a_relancer(self):
        unite, lancer = self._relancer(dict(ENV))
        self.assertEqual(unite, "")
        lancer.assert_not_called()

    def test_refus_de_systemctl(self):
        for options in ({"code": 5}, {"erreur": FileNotFoundError("systemctl")}):
            with self.subTest(**{k: str(v) for k, v in options.items()}):
                unite, _ = self._relancer(dict(ENV, **{autostart.UNITE_ENV: UNITE}), **options)
                self.assertEqual(unite, "")


class TestsBranchements(unittest.TestCase):
    """La seconde étape de « update » et de « restart » passe par ces deux
    fonctions, dans le bon ordre."""

    def test_finaliseur_de_mise_a_jour_sort_du_service_avant_tout(self):
        cible = Path(tempfile.mkdtemp())
        with mock.patch.object(autostart, "sortir_du_service", return_value=True) as sortir, \
                mock.patch.object(maj, "_finaliser") as finaliser:
            self.assertEqual(maj.finaliser(cible), 0)
        finaliser.assert_not_called()
        # Figé : « blink2video update --finaliser … » ; depuis les sources,
        # self_command lance directement le programme du verbe (maj.py).
        self.assertEqual(sortir.call_args[0][0][-2:], ["--finaliser", str(cible)])

    def test_relance_de_la_mise_a_jour_par_le_service(self):
        installe = Path(tempfile.mkdtemp())
        with mock.patch.object(autostart, "relancer_service", return_value=UNITE), \
                mock.patch.object(maj, "_relancer") as relancer:
            maj._relancer_tout(installe, [[["start"]]])
        relancer.assert_not_called()
        with mock.patch.object(autostart, "relancer_service", return_value=""), \
                mock.patch.object(maj, "_relancer") as relancer:
            maj._relancer_tout(installe, [[["start"]], [["serve"]]])
        self.assertEqual(relancer.call_count, 2)

    def test_restart_sort_du_service_avant_d_arreter(self):
        with mock.patch.object(autostart, "sortir_du_service", return_value=True) as sortir, \
                mock.patch.object(blink_cli, "_arreter_instances") as arreter:
            code = blink_cli.redemarrer(["--finaliser", "--delai", "0.75"])
        self.assertEqual(code, 0)
        arreter.assert_not_called()
        self.assertEqual(sortir.call_args[0][0][-4:],
                         ["restart", "--finaliser", "--delai", "0.75"])

    def _second_temps(self, unite_relancee):
        with mock.patch.object(autostart, "sortir_du_service", return_value=False), \
                mock.patch.object(autostart, "relancer_service", return_value=unite_relancee), \
                mock.patch.object(blink_cli, "_arreter_instances", return_value=0), \
                mock.patch.object(blink_cli.runtime, "lire_instances", return_value=[]), \
                mock.patch.object(blink_cli.runtime, "verrou_controle",
                                  return_value=contextlib.nullcontext()), \
                mock.patch.object(blink_cli.runtime, "demarrer") as demarrer:
            self.assertEqual(blink_cli.redemarrer(["--finaliser"]), 0)
        return demarrer

    def test_restart_relance_par_le_service_sinon_detache(self):
        self._second_temps(UNITE).assert_not_called()
        demarrer = self._second_temps("")
        demarrer.assert_called_once()
        self.assertIn("start", demarrer.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
