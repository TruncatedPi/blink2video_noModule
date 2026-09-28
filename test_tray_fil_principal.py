"""Non-regression de l'issue #31 (2026-09-27, macOS 27.2) : « start »
lancait le serveur puis mourait cinq secondes plus tard (SIGTRAP, code
133). Le rapport de plantage de macOS designait un thread secondaire dans
-[NSStatusItem setMenu:] : le thread de rafraichissement du menu
(rafraichir(), tray.py) appelait icon.update_menu(), que pystray transmet
tel quel a AppKit, lequel n'admet les changements d'interface que depuis
le thread principal.

Sous macOS, l'appel passe desormais par PyObjCTools.AppHelper.callAfter,
qui le confie a la boucle principale ; ailleurs, il reste direct. Ces tests
simulent la plateforme et AppHelper, et tournent donc partout : la preuve
sur un vrai Mac reste celle de l'issue."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

os.environ["BLINK_BOOTSTRAP"] = "none"
_TEST_HOME = tempfile.TemporaryDirectory(prefix="blink-tray-fil-")
os.environ["BLINK_HOME"] = _TEST_HOME.name

try:
    import pystray  # noqa: E402
except ImportError:
    pystray = None
try:
    # Menu, rafraîchissement et fil principal vivent dans la bibliothèque
    # commune depuis qu'elle est née de tray.py : c'est elle qu'on patche.
    from nico579_commons import tray as commun  # noqa: E402
except ImportError:
    commun = None
import tray  # noqa: E402


def _faux_pyobjctools(confies, signal=None):
    """Un paquet PyObjCTools dont AppHelper.callAfter note ce qu'on lui
    confie, sans l'executer : il n'y a pas de boucle principale AppKit ici."""
    def call_after(fonction, *args, **kwargs):
        confies.append(fonction)
        if signal is not None:
            signal.set()

    apphelper = types.ModuleType("PyObjCTools.AppHelper")
    apphelper.callAfter = call_after
    paquet = types.ModuleType("PyObjCTools")
    paquet.AppHelper = apphelper
    return {"PyObjCTools": paquet, "PyObjCTools.AppHelper": apphelper}


@unittest.skipIf(commun is None, "nico579_commons indisponible dans cet environnement")
class SurLeFilPrincipalTests(unittest.TestCase):
    def test_macos_confie_l_appel_a_la_boucle_principale(self) -> None:
        confies, faits = [], []

        def fonction():
            faits.append(threading.current_thread().name)

        with mock.patch.dict(sys.modules, _faux_pyobjctools(confies)):
            commun.sur_le_fil_principal(fonction, "darwin")()

        self.assertEqual(faits, [], "appel fait directement, hors de la boucle principale")
        self.assertEqual(confies, [fonction])

    def test_ailleurs_l_appel_reste_direct(self) -> None:
        def fonction():
            return None

        for plateforme in ("win32", "linux"):
            with self.subTest(plateforme=plateforme):
                self.assertIs(commun.sur_le_fil_principal(fonction, plateforme), fonction)


@unittest.skipUnless(tray.disponible(), "pystray indisponible dans cet environnement")
class RafraichissementDuMenuTests(unittest.TestCase):
    """rafraichir(), le thread d'executer(), face a une icone factice."""

    def _executer(self, plateforme: str):
        confies, icones = [], []
        agi = threading.Event()

        class FauxIcon:
            def __init__(self, name, icon_img, title, menu=None):
                self.directs = []
                icones.append(self)

            def stop(self):
                pass

            def update_menu(self):
                self.directs.append(threading.current_thread() is threading.main_thread())
                agi.set()

            def run(self):
                agi.wait(timeout=5)

        vrai = commun.sur_le_fil_principal
        arret = threading.Event()
        try:
            with mock.patch.object(pystray, "Icon", FauxIcon), \
                    mock.patch.object(commun, "CADENCE_MENU", 0.01), \
                    mock.patch.object(commun, "sur_le_fil_principal",
                                      lambda fonction: vrai(fonction, plateforme)), \
                    mock.patch.dict(sys.modules, _faux_pyobjctools(confies, agi)):
                tray.executer(8765, arret, lambda: None)
        finally:
            arret.set()
        self.assertTrue(agi.is_set(), "le thread de rafraichissement n'a jamais agi")
        return icones[0], confies

    def test_macos_ne_touche_jamais_le_menu_hors_du_thread_principal(self) -> None:
        icone, confies = self._executer("darwin")
        self.assertEqual(icone.directs, [])
        self.assertIn(icone.update_menu, confies)

    def test_windows_rafraichit_directement(self) -> None:
        icone, confies = self._executer("win32")
        self.assertEqual(confies, [])
        self.assertTrue(icone.directs)


if __name__ == "__main__":
    unittest.main()
