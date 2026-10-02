"""Une conclusion sans relance rend les contrôles et le libellé du bouton."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


class TestsFinMiseAJour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("node introuvable")
        source = (Path(__file__).parent / "serve_app.js").read_text(encoding="utf-8")
        motifs = [
            r"^const I18N = \{.*?^\};",
            r"^function t\([^\n]*$",
            r"^const CONTROLES_GELES_PENDANT_MAJ = [^\n]*;$",
            *[rf"^function {nom}\(.*?^\}}" for nom in (
                "tf", "libellePhase", "montrerTravail", "montrerMaj", "gelerPendantMaj")],
            r'^\$\("update"\)\.onclick = async \(\) => \{.*?^\};',
            r'^async function etatDuTravail\(.*?^\}',
        ]
        cls.code = "\n".join(re.search(motif, source, re.DOTALL | re.MULTILINE).group(0)
                             for motif in motifs)

    def executer(self, langue, actif, retard=False, refus=False, retard_post=False,
                 reessai=False):
        script = """
const elements = {};
const $ = id => elements[id] ||= {
  disabled: false, dataset: {}, textContent: '', hidden: false,
  classList: {add() {}, remove() {}}, removeAttribute() {}
};
let _lang = LANGUE, actualisationLocale = false;
let travailVisible = false, travailEnCours = true, miseAJourAttente = null;
let generationMaj = 0, repondreTravail, repondreMaj;
let rechargements = 0;
const intervallesAnnules = [];
const delais = [];
const rechargerEnArrierePlan = () => rechargements++;
const setInterval = () => 7;
const clearInterval = id => intervallesAnnules.push(id);
const setTimeout = rappel => delais.push(rappel);
const fetch = async url => url === '/api/travail'
  ? new Promise(resolve => repondreTravail = resolve)
  : (RETARD_POST ? new Promise(resolve => repondreMaj = resolve)
    : (REFUS ? {error: 'Conclusion occupée'} : {ok: true, version: '0.99.0'}));
const lireJSON = async reponse => reponse;
const alert = () => { if (!REFUS) throw Error('alerte inattendue'); };
""".replace("LANGUE", json.dumps(langue)) + self.code + """
(async () => {
  montrerMaj({version: '0.99.0'});
  const lecture = RETARD ? etatDuTravail() : null;
  const demande = $('update').onclick();
  let postProtege = null;
  if (RETARD_POST) {
    const travail = etatDuTravail();
    if (repondreTravail) repondreTravail({travail: {
      quoi: 'Ancien échec', cle: 'phase.update_noop', fait: 1, total: 1,
      termine: '2026-10-02T00:00:00Z'}});
    await travail;
    postProtege = $('update').disabled && !!$('update').dataset.encours;
    repondreMaj({ok: true, version: '0.99.0'});
  }
  await demande;
  const geles = CONTROLES_GELES_PENDANT_MAJ.every(id => $(id).disabled);
  let ancienneIgnoree = null;
  if (RETARD) {
    repondreTravail({travail: {quoi: 'Ancien échec', cle: 'phase.update_noop',
      fait: 1, total: 1, termine: '2026-10-02T00:00:00Z'}});
    await lecture;
    ancienneIgnoree = $('update').disabled
      && CONTROLES_GELES_PENDANT_MAJ.every(id => $(id).disabled)
      && miseAJourAttente === 7 && intervallesAnnules.length === 0;
  }
  if (REFUS) {
    console.log(JSON.stringify({bouton: {disabled: $('update').disabled,
      texte: $('update').textContent, encours: !!$('update').dataset.encours}}));
    return;
  }
  montrerTravail({quoi: "Échec de l'arrêt", cle: 'phase.update_noop',
    fait: 1, total: 1, termine: '2026-10-02T00:00:00Z', actif: ACTIF});
  if (REESSAI) {
    await $('update').onclick();
    const attenteReessai = miseAJourAttente;
    const annulesAvant = intervallesAnnules.length;
    delais[0]();
    const ancienDelaiIgnore = $('update').disabled && !!$('update').dataset.encours
      && CONTROLES_GELES_PENDANT_MAJ.every(id => $(id).disabled)
      && miseAJourAttente === attenteReessai && intervallesAnnules.length === annulesAvant;
    delais[1]();
    const nouveauDelaiApplique = !$('update').disabled && !$('update').dataset.encours
      && CONTROLES_GELES_PENDANT_MAJ.every(id => !$(id).disabled)
      && miseAJourAttente === null && intervallesAnnules.length === annulesAvant + 1;
    console.log(JSON.stringify({ancienDelaiIgnore, nouveauDelaiApplique}));
    return;
  }
  console.log(JSON.stringify({geles, ancienneIgnoree, postProtege,
    controles: CONTROLES_GELES_PENDANT_MAJ.map(id => $(id).disabled),
    bouton: {disabled: $('update').disabled, texte: $('update').textContent,
             encours: !!$('update').dataset.encours},
    refresh: $('refresh').disabled, phase: $('phase').textContent,
    attente: miseAJourAttente, intervallesAnnules, rechargements}));
})().catch(erreur => {console.error(erreur); process.exitCode = 1;});
""".replace("ACTIF", json.dumps(actif))
        script = script.replace("RETARD_POST", json.dumps(retard_post))
        script = script.replace("REESSAI", json.dumps(reessai))
        script = script.replace("RETARD", json.dumps(retard)).replace("REFUS", json.dumps(refus))
        resultat = subprocess.run([self.node, "-"], input=script, capture_output=True,
                                  text=True, encoding="utf-8", timeout=15)
        self.assertEqual(resultat.returncode, 0, resultat.stderr)
        return json.loads(resultat.stdout)

    def verifier(self, actif):
        for langue, texte in (("fr", "Installer 0.99.0"), ("en", "Install 0.99.0")):
            with self.subTest(langue=langue):
                resultat = self.executer(langue, actif)
                self.assertTrue(resultat["geles"])
                self.assertEqual(resultat["controles"], [False] * 4)
                self.assertEqual(resultat["bouton"], {
                    "disabled": False, "texte": texte, "encours": False})
                self.assertEqual(resultat["refresh"], actif)
                self.assertEqual(resultat["phase"], "Échec de l'arrêt")
                self.assertIsNone(resultat["attente"])
                self.assertEqual(resultat["intervallesAnnules"], [7])
                self.assertEqual(resultat["rechargements"], int(not actif))

    def test_echec_sans_autre_travail(self):
        self.verifier(False)

    def test_echec_pendant_un_telechargement(self):
        self.verifier(True)

    def test_reponse_en_vol_avant_le_clic_ne_debloque_pas_le_reessai(self):
        resultat = self.executer("en", True, retard=True)
        self.assertTrue(resultat["ancienneIgnoree"])
        self.assertEqual(resultat["bouton"], {
            "disabled": False, "texte": "Install 0.99.0", "encours": False})
        self.assertEqual(resultat["intervallesAnnules"], [7])

    def test_reessai_refuse_retablit_le_libelle_du_bouton(self):
        resultat = self.executer("fr", True, refus=True)
        self.assertEqual(resultat["bouton"], {
            "disabled": False, "texte": "Installer 0.99.0", "encours": False})

    def test_sonde_pendant_le_post_ne_debloque_pas_le_bouton(self):
        resultat = self.executer("en", True, retard_post=True)
        self.assertTrue(resultat["postProtege"])
        self.assertTrue(resultat["geles"])

    def test_ancien_delai_ne_debloque_pas_le_reessai(self):
        resultat = self.executer("fr", True, reessai=True)
        self.assertTrue(resultat["ancienDelaiIgnore"])
        self.assertTrue(resultat["nouveauDelaiApplique"])


if __name__ == "__main__":
    unittest.main()
