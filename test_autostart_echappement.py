"""Audit du 26/09/2026, B07 et B08 : chemins et arguments contenant des
espaces, &, <, %, $, un guillemet ou un antislash dans les fichiers de
démarrage automatique de Linux (service systemd) et de macOS (agent launchd).

Rien n'est installé pour de vrai : dossier personnel temporaire, systemctl et
launchctl simulés."""

import contextlib
import io
import os
import plistlib
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TEST_HOME = tempfile.TemporaryDirectory(prefix="blink-autostart-echap-")
os.environ["BLINK_HOME"] = _TEST_HOME.name

import autostart  # noqa: E402 - environnement isolé avant import

COMMANDE = ["/home/moi/Blink & Videos/blink2video", "start",
            "--note=50% <test>", "--dossier=$HOME", 'a"b', "c\\d"]
DOSSIER = Path("/home/moi/Blink & Videos/100% $donnees")
SESSION = {"XDG_RUNTIME_DIR": "/run/user/1000"}


def _lancer_reussi(commande, **_options):
    return subprocess.CompletedProcess(commande, 0)


class Echappements(unittest.TestCase):
    def _installer(self, fonction, *, commande=COMMANDE, lancer=_lancer_reussi,
                   env=SESSION):
        with tempfile.TemporaryDirectory(prefix="blink-home-") as home, \
                mock.patch.object(autostart.Path, "home", return_value=Path(home)), \
                mock.patch.object(autostart, "commande", return_value=list(commande)), \
                mock.patch.object(autostart.runtime, "app_dir", return_value=DOSSIER), \
                mock.patch.object(autostart, "env_systemctl", return_value=dict(env)), \
                mock.patch.object(autostart.runtime, "lancer", side_effect=lancer), \
                contextlib.redirect_stdout(io.StringIO()) as sortie:
            code = fonction("on", False)
            fichiers = sorted(Path(home).rglob("*.plist")) + sorted(Path(home).rglob("*.service"))
            contenu = fichiers[0].read_text(encoding="utf-8") if fichiers else None
        return code, contenu, sortie.getvalue()

    def test_B07_execstart_garde_chaque_argument_intact(self):
        code, contenu, _ = self._installer(autostart._linux)

        self.assertEqual(code, 0)
        ligne = next(ligne for ligne in contenu.splitlines()
                     if ligne.startswith("ExecStart="))
        # shlex, en mode POSIX, lit guillemets et antislashs comme systemd ;
        # restent les doublements propres à systemd, %% et $$.
        arguments = [argument.replace("%%", "%").replace("$$", "$")
                     for argument in shlex.split(ligne[len("ExecStart="):])]
        self.assertEqual(arguments, COMMANDE)
        self.assertIn(f"WorkingDirectory={str(DOSSIER).replace('%', '%%')}\n", contenu)

    def test_B07_refus_de_systemctl_n_est_plus_annonce_comme_reussi(self):
        def lancer(commande, **_options):
            return subprocess.CompletedProcess(commande, 1 if "enable" in commande else 0)

        code, _, sortie = self._installer(autostart._linux, lancer=lancer)

        self.assertEqual(code, 1)
        self.assertIn("enable --now", sortie)

    def test_B07_sans_session_systemd_l_avertissement_reste(self):
        def lancer(commande, **_options):
            return subprocess.CompletedProcess(commande, 1)

        code, _, sortie = self._installer(autostart._linux, lancer=lancer, env={})

        self.assertEqual(code, 0)
        self.assertIn("loginctl enable-linger", sortie)

    def test_B08_plist_relu_a_l_identique(self):
        code, contenu, _ = self._installer(autostart._macos)

        self.assertEqual(code, 0)
        agent = plistlib.loads(contenu.encode("utf-8"))
        self.assertEqual(agent["ProgramArguments"], COMMANDE)
        self.assertEqual(agent["WorkingDirectory"], str(DOSSIER))

    def test_B08_plist_invalide_jamais_ecrit(self):
        # Un caractère de contrôle n'a pas de forme en XML 1.0 : l'agent
        # serait refusé par launchd, il n'est donc pas écrit du tout.
        code, contenu, sortie = self._installer(
            autostart._macos, commande=["/opt/blink\x01/blink2video", "start"])

        self.assertEqual(code, 1)
        self.assertIsNone(contenu)
        self.assertIn("plist", sortie)


if __name__ == "__main__":
    unittest.main()
