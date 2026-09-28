"""« Direct continu » (demandé le 2026-09-28) : le choix par caméra est retenu,
et le budget de dix minutes des reprises ne s'applique plus tant que la case
est cochée. Le vrai code de serve_app.js, exécuté par node avec un faux
localStorage et de fausses minuteries.
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


class TestsDirectContinu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("node introuvable")
        cls.source = (RACINE / "serve_app.js").read_text(encoding="utf-8")
        debut = cls.source.index("const CLE_DIRECT_CONTINU")
        fin = cls.source.index("// Un seul identifiant par watchMse()", debut)
        cls.code = cls.source[debut:fin]

    def executer(self, corps: str, stockage: dict | None = None) -> dict:
        script = (
            f"const stockage = {json.dumps(stockage or {})};\n"
            "globalThis.localStorage = {getItem: (c) => stockage[c] ?? null,"
            " setItem: (c, v) => { stockage[c] = String(v); }};\n"
            "const minuteries = [];\n"
            "globalThis.setTimeout = (f, d) => { minuteries.push({f, d}); return minuteries.length; };\n"
            + self.code + "\n"
            "const sortie = {};\n" + corps + "\n"
            "console.log(JSON.stringify({stockage, sortie}));\n"
        )
        resultat = subprocess.run([self.node, "-e", script], capture_output=True,
                                  text=True, encoding="utf-8", check=True)
        return json.loads(resultat.stdout)

    def test_decochee_par_defaut_puis_retenue(self):
        sortie = self.executer(
            "sortie.avant = directContinu('Salon');"
            " choisirDirectContinu('Salon', true);"
            " sortie.apres = directContinu('Salon');"
            " sortie.autre = directContinu('Bureau');")
        self.assertEqual(sortie["sortie"], {"avant": False, "apres": True, "autre": False})
        self.assertEqual(json.loads(sortie["stockage"]["blink2video.directContinu"]), ["Salon"])

    def test_choix_relu_au_chargement_et_decoche(self):
        sortie = self.executer(
            "sortie.relu = directContinu('Salon');"
            " choisirDirectContinu('Salon', false);"
            " sortie.decoche = directContinu('Salon');",
            stockage={"blink2video.directContinu": '["Salon"]'})
        self.assertEqual(sortie["sortie"], {"relu": True, "decoche": False})
        self.assertEqual(json.loads(sortie["stockage"]["blink2video.directContinu"]), [])

    def test_stockage_illisible_ou_absent(self):
        for stockage in ({"blink2video.directContinu": "pas du json"},
                         {"blink2video.directContinu": '{"Salon": true}'}):
            with self.subTest(stockage=stockage):
                sortie = self.executer("sortie.v = directContinu('Salon');", stockage)
                self.assertFalse(sortie["sortie"]["v"])

    def test_budget_ordinaire_conclut_a_echeance(self):
        sortie = self.executer(
            "let fini = 0;"
            " armerBudget('Salon', 600000, () => { fini++; });"
            " sortie.premier = minuteries[0].d;"
            " minuteries[0].f();"
            " sortie.fini = fini; sortie.rearmees = minuteries.length - 1;")
        self.assertEqual(sortie["sortie"], {"premier": 600000, "fini": 1, "rearmees": 0})

    def test_direct_continu_sans_budget_puis_decoche(self):
        sortie = self.executer(
            "let fini = 0;"
            " choisirDirectContinu('Salon', true);"
            " const budget = armerBudget('Salon', 600000, () => { fini++; });"
            " minuteries[0].f();"
            " sortie.apresBudget = fini;"
            " sortie.revérification = minuteries[1].d;"
            " sortie.id = budget.id;"
            " choisirDirectContinu('Salon', false);"
            " minuteries[1].f();"
            " sortie.apresDecoche = fini;")
        self.assertEqual(sortie["sortie"], {"apresBudget": 0, "revérification": 60000,
                                            "id": 2, "apresDecoche": 1})

    def test_boucles_et_carte_branchees(self):
        s = self.source
        self.assertEqual(s.count("directContinu(name) || performance.now() - t0 <"), 2)
        self.assertIn("if (!directContinu(name)) break;", s)
        self.assertIn('data-action="continu"', s)
        self.assertIn('case "continu":', s)
        for cle in ("camera.continuous", "camera.continuous.title",
                    "camera.continuous.title.battery"):
            self.assertEqual(s.count(f'"{cle}":'), 2, cle)


if __name__ == "__main__":
    unittest.main()
