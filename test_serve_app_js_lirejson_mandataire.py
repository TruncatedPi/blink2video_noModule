"""Issue #35, suite (Caddy) : pendant la relance, le mandataire répond 502 avec
un corps vide. lireJSON() prenait cette SyntaxError pour un jeton périmé et
rechargeait la page, qui tombait sur la page d'erreur du navigateur, sans
script pour la relancer. Le vrai code de serve_app.js, exécuté par node avec
un faux fetch et un faux location."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).parent


class TestsLireJsonEtMandataire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("node introuvable")
        source = (RACINE / "serve_app.js").read_text(encoding="utf-8")
        trouve = re.search(r"^async function lireJSON\(.*?^\}", source,
                           re.DOTALL | re.MULTILINE)
        if trouve is None:
            raise AssertionError("fonction lireJSON() introuvable")
        cls.code = trouve.group(0)

    def rechargements(self, statut: int, corps_json: bool) -> dict:
        """Passe une réponse de ce statut à lireJSON() ; « corps_json » dit si
        .json() réussit ou lève la SyntaxError d'un corps vide/HTML."""
        script = (
            "let rechargements = 0;\n"
            "globalThis.location = {reload: () => { rechargements += 1; }};\n"
            f"const reponse = {{status: {statut}, json: async () => "
            + ("({ok: true})" if corps_json else "{ throw new SyntaxError('corps vide'); }")
            + "};\n" + self.code + "\n"
            "(async () => {\n"
            "  let resultat = 'valeur';\n"
            "  try { await lireJSON(reponse); } catch (e) { resultat = e.name; }\n"
            "  console.log(JSON.stringify({resultat, rechargements}));\n"
            "})();\n"
        )
        sortie = subprocess.run([self.node, "-e", script], capture_output=True,
                                text=True, encoding="utf-8", check=True)
        return json.loads(sortie.stdout)

    def test_un_502_503_504_de_mandataire_ne_recharge_pas(self):
        for code in (502, 503, 504):
            with self.subTest(code=code):
                self.assertEqual(self.rechargements(code, corps_json=False),
                                 {"resultat": "SyntaxError", "rechargements": 0})

    def test_un_jeton_perime_recharge_toujours(self):
        # send_error() de http.server : HTML en 403, jamais du JSON.
        for code in (403, 404, 200):
            with self.subTest(code=code):
                self.assertEqual(self.rechargements(code, corps_json=False),
                                 {"resultat": "SyntaxError", "rechargements": 1})

    def test_un_corps_json_valide_ne_recharge_rien(self):
        self.assertEqual(self.rechargements(200, corps_json=True),
                         {"resultat": "valeur", "rechargements": 0})


if __name__ == "__main__":
    unittest.main()
