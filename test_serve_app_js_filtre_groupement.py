"""« Grouper par » survit au rechargement de la page, donc au redémarrage de
blink2video (issue #36) : le vrai code de serve_app.js, exécuté par node
avec un faux document et un faux localStorage.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).parent


def extraire(source: str, motif: str) -> str:
    trouve = re.search(motif, source, re.DOTALL | re.MULTILINE)
    if trouve is None:
        raise AssertionError(f"introuvable dans serve_app.js : {motif}")
    return trouve.group(0)


class TestsGroupementRetenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("node introuvable")
        source = (RACINE / "serve_app.js").read_text(encoding="utf-8")
        cls.code = "\n".join([
            extraire(source, r'^const CLE_FILTRE = .*?;$'),
            extraire(source, r'^const GROUPEMENTS = .*?;$'),
            extraire(source, r'^function sauvegarderFiltre\(\) \{.*?^\}'),
            extraire(source, r'^function restaurerGroupement\(filtre\) \{.*?^\}'),
        ])

    def executer(self, corps: str) -> dict:
        script = (
            "const stockage = {};\n"
            "globalThis.localStorage = {getItem: (c) => stockage[c] ?? null,"
            " setItem: (c, v) => { stockage[c] = String(v); }};\n"
            "const champs = {camera: {value: 'Salon'}, groupBy: {value: 'camera'}};\n"
            "const $ = (id) => champs[id];\n"
            "let plageClips = {preset: 'week'};\n"
            + self.code + "\n" + corps + "\n"
            "console.log(JSON.stringify({stockage, groupBy: champs.groupBy.value}));\n"
        )
        resultat = subprocess.run([self.node, "-e", script], capture_output=True,
                                  text=True, encoding="utf-8", check=True)
        return json.loads(resultat.stdout)

    def test_le_choix_est_enregistre_avec_le_reste_du_filtre(self):
        sortie = self.executer("champs.groupBy.value = 'day'; sauvegarderFiltre();")
        filtre = json.loads(sortie["stockage"]["blink2video.filtre"])
        self.assertEqual(filtre, {"camera": "Salon", "plage": {"preset": "week"},
                                  "groupBy": "day"})

    def test_le_choix_retenu_est_repose_au_chargement(self):
        for choix in ("day", "camera"):
            with self.subTest(choix=choix):
                sortie = self.executer(
                    f"champs.groupBy.value = '{'camera' if choix == 'day' else 'day'}';"
                    f" restaurerGroupement({{groupBy: '{choix}'}});")
                self.assertEqual(sortie["groupBy"], choix)

    def test_valeur_inconnue_ou_filtre_ancien_sans_effet(self):
        # Un filtre enregistré par la 0.14.4 n'a pas de groupBy.
        for filtre in ("null", "{camera: 'Salon'}", "{groupBy: 'semaine'}"):
            with self.subTest(filtre=filtre):
                sortie = self.executer(f"restaurerGroupement({filtre});")
                self.assertEqual(sortie["groupBy"], "camera")

    def test_le_chargement_repose_le_choix(self):
        source = (RACINE / "serve_app.js").read_text(encoding="utf-8")
        self.assertIn("restaurerGroupement(_filtrePersiste);", source)


class TestsBoutonVerifierMaj(unittest.TestCase):
    def test_bouton_route_et_libelles_dans_les_deux_langues(self):
        page = (RACINE / "serve.py").read_text(encoding="utf-8")
        script = (RACINE / "serve_app.js").read_text(encoding="utf-8")
        self.assertIn('id="verifierMajButton"', page)
        self.assertIn('route == "/api/maj/verifier"', page)
        self.assertIn('$("verifierMajButton").onclick', script)
        self.assertIn('fetch("/api/maj/verifier"', script)
        for cle in ("reglages.checkUpdates", "reglages.checkUpdates.none",
                    "reglages.checkUpdates.found", "reglages.checkUpdates.offline"):
            self.assertEqual(script.count(f'"{cle}":'), 2, cle)


if __name__ == "__main__":
    unittest.main()
