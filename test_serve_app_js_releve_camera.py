"""Issue #37 : la date d'un relevé de caméra et la température sont mises en
forme par la page, dans sa langue et au format du navigateur. Le serveur
envoyait « 28/09 à 14:30 » (français en dur, et la page devinait la phrase à
prendre en cherchant ce « à » dedans) et la température prenait toujours une
virgule. Le vrai code de serve_app.js, dictionnaires compris, exécuté par node.
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


class TestsReleveEtTemperature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("node introuvable")
        source = (RACINE / "serve_app.js").read_text(encoding="utf-8")
        cls.code = "\n".join([
            extraire(source, r'^const I18N = \{.*?^\};'),
            extraire(source, r'^function t\(k\) \{[^\n]*\}$'),
            extraire(source, r'^function tf\(k, v\) \{.*?^\}'),
            extraire(source, r'^function dateReleve\(c, locale\) \{.*?^\}'),
            extraire(source, r'^function degres\(valeur, locale\) \{.*?^\}'),
        ])

    def executer(self, langue: str, expression: str):
        script = (f"let _lang = {json.dumps(langue)};\n" + self.code + "\n"
                  f"console.log(JSON.stringify({expression}));\n")
        resultat = subprocess.run([self.node, "-"], input=script, capture_output=True,
                                  text=True, encoding="utf-8", check=True)
        return json.loads(resultat.stdout)

    def releve(self, langue, locale, iso, aujourdhui):
        return self.executer(
            langue, f"dateReleve({{measured_at: {json.dumps(iso)}, "
                    f"measured_today: {str(aujourdhui).lower()}}}, {json.dumps(locale)})")

    def test_releve_du_jour_en_francais_et_en_anglais(self):
        self.assertEqual(self.releve("fr", "fr", "2026-09-28T14:30+02:00", True),
                         "relevé à 14:30")
        self.assertEqual(self.releve("en", "en-GB", "2026-09-28T14:30+02:00", True),
                         "measured at 14:30")

    def test_releve_ancien_dit_le_jour_puis_l_heure_dans_la_langue_de_la_page(self):
        self.assertEqual(self.releve("fr", "fr", "2026-09-26T10:05+02:00", False),
                         "relevé du 26/09 à 10:05")
        self.assertEqual(self.releve("en", "en-GB", "2026-09-26T10:05+02:00", False),
                         "measured on 26/09 at 10:05")

    def test_le_format_de_date_est_celui_du_navigateur(self):
        self.assertEqual(self.releve("en", "en-US", "2026-09-26T10:05+02:00", False),
                         "measured on 09/26 at 10:05")

    def test_aucun_mot_francais_sous_une_page_anglaise(self):
        for iso, aujourdhui in (("2026-09-28T14:30+02:00", True),
                                ("2026-09-26T10:05+02:00", False)):
            with self.subTest(iso=iso):
                texte = self.releve("en", "en-GB", iso, aujourdhui)
                self.assertNotRegex(texte, r"[àéèêç]|\b(relevé|du|le)\b")

    def test_le_jour_est_celui_du_serveur_pas_un_jour_converti(self):
        # 23:59 à +02:00 reste le 28 : la page lit la date telle qu'envoyée au
        # lieu de la convertir dans son propre fuseau.
        self.assertEqual(self.releve("fr", "fr", "2026-09-28T23:59+02:00", False),
                         "relevé du 28/09 à 23:59")

    def test_sans_releve_ou_date_illisible_rien(self):
        self.assertIsNone(self.executer("fr", "dateReleve({measured_at: null}, 'fr')"))
        self.assertIsNone(self.executer("fr", "dateReleve({}, 'fr')"))
        self.assertIsNone(self.executer("fr", "dateReleve({measured_at: '28/09 à 14:30'}, 'fr')"))

    def test_la_temperature_suit_le_separateur_du_navigateur(self):
        self.assertEqual(self.executer("fr", "degres(21.5, 'fr')"), "21,5")
        self.assertEqual(self.executer("en", "degres(21.5, 'en-GB')"), "21.5")
        self.assertEqual(self.executer("en", "degres(21, 'en-GB')"), "21.0")

    def test_les_deux_dictionnaires_donnent_le_jour_et_l_heure_separement(self):
        for langue in ("fr", "en"):
            with self.subTest(langue=langue):
                phrase = self.executer(langue, "t('camera.measured.on')")
                self.assertIn("{d}", phrase)
                self.assertIn("{h}", phrase)

    def test_la_page_ne_cherche_plus_un_a_dans_le_texte_du_serveur(self):
        source = (RACINE / "serve_app.js").read_text(encoding="utf-8")
        self.assertNotIn('measured_at.includes("à")', source)
        self.assertNotIn('.replace(".", ",")', source)
        self.assertIn("const date = dateReleve(c);", source)


if __name__ == "__main__":
    unittest.main()
