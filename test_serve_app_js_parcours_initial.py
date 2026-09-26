"""Audit du 26/09/2026, B04 : une page rechargée avec ?setup=1 après la
validation de la première configuration (jeton périmé au remplacement du
serveur, voir lireJSON()) rouvrait le dialogue obligatoire, sans Fermer ni
Échap, alors que le serveur la tenait pour terminée.

lancerParcoursInitial() est extraite de serve_app.js et exécutée par node,
avec une API et un navigateur simulés.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


class TestsParcoursInitial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("node introuvable")
        source = (Path(__file__).parent / "serve_app.js").read_text(encoding="utf-8")
        parcours = re.search(
            r"^\(async function lancerParcoursInitial\(\) \{.*?^\}\)\(\);",
            source, re.DOTALL | re.MULTILINE,
        )
        lire_json = re.search(
            r"^async function lireJSON\(.*?^\}", source, re.DOTALL | re.MULTILINE,
        )
        if parcours is None or lire_json is None:
            raise AssertionError("lancerParcoursInitial() ou lireJSON() introuvable")
        # Sans l'appel final : le script de test attend lui-même la promesse.
        cls.parcours = parcours.group(0)[:-len("();")]
        cls.lire_json = lire_json.group(0)

    def _executer(self, *, recherche: str, statut) -> dict:
        script = f"""
const ouvertures = [], remplacements = [];
let rechargements = 0;
globalThis.location = {{
  search: {json.dumps(recherche)}, pathname: "/",
  reload: () => {{ rechargements += 1; }},
}};
globalThis.history = {{ replaceState: (_etat, _titre, url) => remplacements.push(url) }};
async function authenticate() {{ return true; }}
async function ouvrirReglages(obligatoire) {{ ouvertures.push(obligatoire); }}
const statut = {json.dumps(statut)};
globalThis.fetch = async () => {{
  if (statut === "reseau") throw new TypeError("Serveur arrêté");
  return {{ json: async () => statut }};
}};
{self.lire_json}
const parcours = {self.parcours};
parcours().then(() => process.stdout.write(JSON.stringify({{
  ouvertures, remplacements, rechargements,
}})));
"""
        resultat = subprocess.run(
            [self.node, "-e", script], capture_output=True, text=True,
            encoding="utf-8", timeout=60,
        )
        if resultat.returncode != 0:
            raise AssertionError(resultat.stderr)
        return json.loads(resultat.stdout)

    def test_configuration_deja_validee_ne_rouvre_pas_le_dialogue(self):
        sortie = self._executer(recherche="?setup=1", statut={"initial_setup": False})
        self.assertEqual(sortie["ouvertures"], [])
        self.assertEqual(sortie["remplacements"], ["/"])

    def test_configuration_attendue_ouvre_le_dialogue_obligatoire(self):
        sortie = self._executer(recherche="?setup=1", statut={"initial_setup": True})
        self.assertEqual(sortie["ouvertures"], [True])
        self.assertEqual(sortie["remplacements"], [])

    def test_statut_injoignable_garde_le_dialogue_obligatoire(self):
        sortie = self._executer(recherche="?setup=1", statut="reseau")
        self.assertEqual(sortie["ouvertures"], [True])

    def test_sans_setup_rien_ne_s_ouvre(self):
        sortie = self._executer(recherche="", statut={"initial_setup": True})
        self.assertEqual(sortie["ouvertures"], [])
        self.assertEqual(sortie["remplacements"], [])


if __name__ == "__main__":
    unittest.main()
