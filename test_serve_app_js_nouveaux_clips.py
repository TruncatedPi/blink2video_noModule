"""Audit du 26/09/2026, B03 : heuresDePassage() comparait le nombre de clips
de /api/passages à data.total_known entier, devenu un objet par genre
({"clip": ..., "direct": ...}) le 2026-09-04. La soustraction donnait NaN :
les nouveaux clips n'étaient plus annoncés, ni la galerie rechargée quand la
case d'actualisation automatique était cochée.

La vraie fonction est extraite de serve_app.js et exécutée par node, avec une
API et un DOM simulés.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from test_serve_app_js_datetime import formatting_source


class TestsNouveauxClips(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("node introuvable")
        source = (Path(__file__).parent / "serve_app.js").read_text(encoding="utf-8")
        fonction = re.search(
            r"^async function heuresDePassage\(\) \{.*?^\}", source,
            re.DOTALL | re.MULTILINE,
        )
        if fonction is None:
            raise AssertionError("heuresDePassage() introuvable dans serve_app.js")
        cls.fonction = fonction.group(0)

        cls.fonction = formatting_source(source) + "\n" + cls.fonction

    def _executer(self, *, galerie: dict, clips_passages: int, auto: bool) -> dict:
        etat = {"passages": {"download": "2026-09-26T18:05:00Z"},
                "clips": clips_passages, "maj": None}
        script = f"""
let data = {json.dumps(galerie)};
let travailEnCours = false;
let rechargements = 0;
function rechargerEnArrierePlan() {{ rechargements += 1; }}
function montrerMaj() {{}}
async function lireJSON(reponse) {{ return reponse; }}
globalThis.fetch = async () => ({json.dumps(etat)});
function tf(cle, valeurs) {{ return "[" + cle + ":" + JSON.stringify(valeurs || {{}}) + "]"; }}
const elements = {{ auto: {{ checked: {json.dumps(auto)} }}, passages: {{ textContent: "" }} }};
globalThis.$ = (id) => elements[id];

{self.fonction}

heuresDePassage().then(() => process.stdout.write(JSON.stringify({{
  rechargements, texte: elements.passages.textContent,
}})));
"""
        resultat = subprocess.run(
            [self.node, "-e", script], capture_output=True, text=True,
            encoding="utf-8", timeout=60,
        )
        if resultat.returncode != 0:
            raise AssertionError(resultat.stderr)
        return json.loads(resultat.stdout)

    def test_un_clip_arrive_recharge_quand_la_case_est_cochee(self):
        sortie = self._executer(
            galerie={"clips": [], "total_known": {"clip": 10, "direct": 3}},
            clips_passages=11, auto=True)
        self.assertEqual(sortie["rechargements"], 1)

    def test_un_clip_arrive_est_annonce_sans_actualisation_automatique(self):
        sortie = self._executer(
            galerie={"clips": [], "total_known": {"clip": 10, "direct": 3}},
            clips_passages=11, auto=False)
        self.assertEqual(sortie["rechargements"], 0)
        self.assertIn('passages.new.one:{"n":1}', sortie["texte"])

    def test_rien_de_nouveau_rien_d_annonce(self):
        sortie = self._executer(
            galerie={"clips": [], "total_known": {"clip": 11, "direct": 3}},
            clips_passages=11, auto=True)
        self.assertEqual(sortie["rechargements"], 0)
        self.assertNotIn("passages.new", sortie["texte"])

    def test_galerie_pas_encore_chargee_rien_a_comparer(self):
        # État initial de serve_app.js : data sans total_known.
        sortie = self._executer(
            galerie={"clips": [], "cameras": [], "days": []},
            clips_passages=11, auto=True)
        self.assertEqual(sortie["rechargements"], 0)
        self.assertNotIn("passages.new", sortie["texte"])


if __name__ == "__main__":
    unittest.main()
