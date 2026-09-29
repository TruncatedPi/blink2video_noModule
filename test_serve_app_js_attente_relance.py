"""La page se recharge toute seule quand blink2video revient après une mise à
jour, Appliquer ou Redémarrer (issue #35 : « Instead of an Error page and a
manual refresh »). Le vrai code de serve_app.js, exécuté par node avec un
faux fetch et un faux location.

Deux façons de rater le retour existaient : un serveur relancé plus vite que
le sondage de 2 s (jamais vu absent, alors que son nouveau jeton fait
répondre 403 à l'ancienne page), et un mandataire (nginx...) qui répond 502
au lieu de refuser la connexion pendant l'arrêt."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).parent


class TestsSondeDeRelance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("node introuvable")
        cls.source = (RACINE / "serve_app.js").read_text(encoding="utf-8")
        fonctions = []
        for nom in ("etatServeur", "sonderRelance"):
            trouve = re.search(rf"^async function {nom}\(.*?^\}}", cls.source,
                               re.DOTALL | re.MULTILINE)
            if trouve is None:
                raise AssertionError(f"fonction {nom}() introuvable")
            fonctions.append(trouve.group(0))
        cls.code = "\n".join(fonctions)

    def executer(self, reponses: list) -> dict:
        """Enchaîne un sondage par réponse : « erreur » fait lever fetch(),
        un entier est un code HTTP. Rend l'état vu et les rechargements."""
        script = (
            f"const reponses = {json.dumps(reponses)};\n"
            "let rechargements = 0;\n"
            "globalThis.location = {reload: () => { rechargements += 1; }};\n"
            "globalThis.fetch = async () => {\n"
            "  const r = reponses.shift();\n"
            "  if (r === 'erreur') throw new TypeError('Connexion refusée');\n"
            "  return {status: r};\n"
            "};\n" + self.code + "\n"
            "(async () => {\n"
            "  const suivi = {parti: false}, apres = [];\n"
            f"  for (let i = 0; i < {len(reponses)}; i++) {{\n"
            "    await sonderRelance(suivi); apres.push([suivi.parti, rechargements]);\n"
            "  }\n"
            "  console.log(JSON.stringify(apres));\n"
            "})();\n"
        )
        resultat = subprocess.run([self.node, "-e", script], capture_output=True,
                                  text=True, encoding="utf-8", check=True)
        return json.loads(resultat.stdout)

    def test_le_serveur_est_vu_absent_puis_revient(self):
        # Connexion refusée, puis le serveur répond : rechargement au retour.
        self.assertEqual(self.executer(["erreur", "erreur", 200]),
                         [[True, 0], [True, 0], [True, 1]])

    def test_un_mandataire_qui_repond_502_503_504_compte_comme_absence(self):
        for code in (502, 503, 504):
            with self.subTest(code=code):
                self.assertEqual(self.executer([code, code, 200]),
                                 [[True, 0], [True, 0], [True, 1]])

    def test_403_recharge_sans_avoir_vu_l_absence(self):
        # Le serveur relancé (nouveau jeton) répond 403 à l'ancienne page.
        self.assertEqual(self.executer([403]), [[False, 1]])

    def test_rien_a_faire_tant_que_le_serveur_n_a_pas_disparu(self):
        self.assertEqual(self.executer([200, 200, 200]),
                         [[False, 0], [False, 0], [False, 0]])

    def test_une_erreur_500_est_un_serveur_vivant_pas_une_absence(self):
        self.assertEqual(self.executer([500]), [[False, 0]])


class TestsMiseAJourEtRedemarrage(unittest.TestCase):
    def test_les_trois_attentes_passent_par_la_meme_sonde(self):
        source = (RACINE / "serve_app.js").read_text(encoding="utf-8")
        self.assertIn("miseAJourAttente = setInterval(() => sonderRelance(suivi), 2000);", source)
        self.assertIn("const attente = setInterval(() => sonderRelance(suivi), 2000);", source)
        # Plus de sonde écrite à la main, qui ne reconnaissait ni le 403 du
        # serveur relancé ni le 502 d'un mandataire.
        self.assertNotIn('await fetch("/api/status", { cache: "no-store" });\n'
                         "      if (parti) location.reload();", source)


if __name__ == "__main__":
    unittest.main()
