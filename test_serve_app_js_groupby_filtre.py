"""Issue #36, suite : dans le panneau du filtre, « Grouper par » apparaît et
disparaît dès qu'on change de caméra dans la liste, sans attendre « Filtrer »
puis une réouverture. Le vrai code de serve_app.js, exécuté par node avec un
faux DOM."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).parent


class TestsGroupByDansLeFiltre(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("node introuvable")
        cls.source = (RACINE / "serve_app.js").read_text(encoding="utf-8")
        fragments = []
        for nom in ("regroupable", "majGroupBy"):
            trouve = re.search(rf"^function {nom}\(.*?^\}}", cls.source, re.DOTALL | re.MULTILINE)
            if trouve is None:
                raise AssertionError(f"fonction {nom}() introuvable")
            fragments.append(trouve.group(0))
        cls.code = "\n".join(fragments)

    def visible(self, vue: str, camera: str) -> bool:
        script = (
            f"const boites = {{ view: {{ value: {vue!r} }}, camera: {{ value: {camera!r} }},\n"
            "  groupBySection: { hidden: true } };\n"
            "function $(id) { return boites[id]; }\n"
            + self.code + "\n"
            "majGroupBy();\n"
            "process.stdout.write(String(!boites.groupBySection.hidden));\n"
        )
        resultat = subprocess.run([self.node, "-e", script], capture_output=True, text=True,
                                  encoding="utf-8", timeout=60)
        self.assertEqual(resultat.returncode, 0, resultat.stderr)
        return resultat.stdout == "true"

    def test_journalieres_toutes_cameras_le_choix_est_visible(self):
        self.assertTrue(self.visible("daily", ""))

    def test_journalieres_une_camera_le_choix_disparait(self):
        self.assertFalse(self.visible("daily", "camera-abc"))

    def test_hebdomadaires_et_mensuelles_n_ont_jamais_le_choix(self):
        for vue in ("weekly", "monthly", "clips", "direct", "live"):
            with self.subTest(vue=vue):
                self.assertFalse(self.visible(vue, ""))

    def test_le_choix_suit_la_liste_des_cameras_sans_valider_le_filtre(self):
        # Le cas signalé : d'une caméra à « toutes les caméras », le choix devait
        # apparaître tout de suite, sans « Filtrer » ni réouverture.
        self.assertIn('$("camera").addEventListener("change", majGroupBy);', self.source)

    def test_ouvrir_le_filtre_et_le_rendu_passent_par_la_meme_fonction(self):
        ouvrir = re.search(r"^function ouvrirFiltre\(.*?^\}", self.source, re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(ouvrir)
        self.assertIn("majGroupBy();", ouvrir.group(0))
        self.assertIn("  majGroupBy();\n  $(\"filtreResume\")", self.source)
        # Plus de second calcul du même état, qui pourrait diverger.
        self.assertEqual(self.source.count('$("groupBySection").hidden ='), 1)


if __name__ == "__main__":
    unittest.main()
