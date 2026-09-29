"""Issue #37 : le sélecteur de caméra ne montre que les noms. Le modèle n'y
figurait que pour les caméras déjà vues en direct (le serveur le retenait dans
cameras.json à chaque passage par Direct), et sous le code interne de Blink
quand il n'en donne pas le nom : « hawk », « sedona », « lotus » pour les unes,
rien pour les autres. Il reste sur la carte de la caméra.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8, édition Windows 7
    from backports.zoneinfo import ZoneInfo

RACINE = Path(__file__).parent


class TestsSelecteurDeCamera(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (RACINE / "serve_app.js").read_text(encoding="utf-8")

    def test_les_deux_remplissages_posent_les_noms_seuls(self):
        # Au chargement des clips, et à chaque changement de langue.
        appels = re.findall(r'fill\(\$\("camera"\), camerasConnues\(\), t\("filter\.allcameras"\)\);',
                            self.source)
        self.assertEqual(len(appels), 2)
        self.assertNotIn("data.models", self.source)

    def test_fill_pose_le_nom_tel_quel_et_garde_la_selection(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node introuvable")
        trouve = re.search(r"^function fill\(.*?^\}", self.source, re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(trouve, "fonction fill() introuvable")
        script = (
            "globalThis.document = { createElement: (tag) => ({ tag, value: '', textContent: '' }) };\n"
            "const select = { value: 'Salon', children: [],\n"
            "  replaceChildren() { this.children = []; },\n"
            "  append(o) { this.children.push(o); } };\n"
            + trouve.group(0) + "\n"
            "fill(select, ['Jardin', 'Salon'], 'Toutes');\n"
            "console.log(JSON.stringify({ options: select.children.map((o) => [o.value, o.textContent]),\n"
            "                             selection: select.value }));\n"
        )
        resultat = subprocess.run([node, "-e", script], capture_output=True, text=True,
                                  encoding="utf-8", check=True)
        self.assertEqual(json.loads(resultat.stdout),
                         {"options": [["", "Toutes"], ["Jardin", "Jardin"], ["Salon", "Salon"]],
                          "selection": "Salon"})


class TestsServeurSansModeles(unittest.TestCase):
    def test_l_inventaire_n_envoie_plus_de_modeles(self):
        import serve

        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            paths = {cle: racine / cle for cle in (
                "input", "normalized", "excluded", "thumbs", "daily", "weekly",
                "monthly", "direct", "snapshots")}
            for dossier in paths.values():
                dossier.mkdir()
            donnees = serve.collect(paths, ZoneInfo("Europe/Paris"))
        self.assertIn("cameras", donnees)
        self.assertNotIn("models", donnees)

    def test_plus_d_ecriture_de_cameras_json_a_chaque_passage_par_direct(self):
        import serve

        self.assertFalse(hasattr(serve, "remember_cameras"))
        self.assertFalse(hasattr(serve, "CAMERA_FACTS"))

    def test_le_modele_reste_sur_la_carte_de_la_camera(self):
        import serve

        self.assertEqual(serve.model_name("owl"), "Blink Mini")
        self.assertEqual(serve.model_name("hawk"), "hawk")
        self.assertIsNone(serve.model_name(None))


if __name__ == "__main__":
    unittest.main()
