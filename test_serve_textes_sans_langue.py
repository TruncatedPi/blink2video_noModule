"""Issue #37 : ce que le serveur compose pour la page ne porte ni mot ni format
de date d'une langue. La page s'affiche en français ou en anglais et compose
elle-même ses phrases ; « type Blink « hawk » » et « 28/09 à 14:30 » partaient
tels quels sous une page anglaise, où un utilisateur a vu du français."""

from __future__ import annotations

import datetime as dt
import re
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

import serve

PARIS = ZoneInfo("Europe/Paris")


class TestsModeleDeCamera(unittest.TestCase):
    def test_un_modele_connu_donne_le_nom_du_produit(self):
        self.assertEqual(serve.model_name("owl"), "Blink Mini")
        self.assertEqual(serve.model_name("catalina"), "Blink Outdoor")

    def test_un_code_inconnu_est_rendu_tel_quel_jamais_une_phrase(self):
        # hawk, sedona et lotus : les trois codes que le rapporteur voyait.
        for code in ("hawk", "sedona", "lotus"):
            with self.subTest(code=code):
                self.assertEqual(serve.model_name(code), code)

    def test_sans_type_rien(self):
        self.assertIsNone(serve.model_name(None))
        self.assertIsNone(serve.model_name(""))


class TestsHorodatageDuReleve(unittest.TestCase):
    def test_iso_a_la_minute_a_l_heure_du_serveur(self):
        moment = dt.datetime(2026, 9, 28, 12, 30, 45, tzinfo=dt.timezone.utc)
        maintenant = dt.datetime(2026, 9, 28, 20, 0, tzinfo=PARIS)
        iso, aujourdhui = serve.horodatage_releve(moment, PARIS, maintenant=maintenant)
        self.assertEqual(iso, "2026-09-28T14:30+02:00")
        self.assertTrue(aujourdhui)

    def test_un_releve_d_un_jour_plus_ancien(self):
        moment = dt.datetime(2026, 9, 26, 8, 5, tzinfo=dt.timezone.utc)
        maintenant = dt.datetime(2026, 9, 28, 9, 0, tzinfo=PARIS)
        iso, aujourdhui = serve.horodatage_releve(moment, PARIS, maintenant=maintenant)
        self.assertEqual(iso, "2026-09-26T10:05+02:00")
        self.assertFalse(aujourdhui)

    def test_le_jour_est_celui_du_serveur_pas_celui_d_utc(self):
        # 23:30 UTC le 28 est 01:30 le 29 à Paris : « aujourd'hui » quand il
        # est 08:00 le 29 à Paris, alors que la date UTC est celle de la veille.
        moment = dt.datetime(2026, 9, 28, 23, 30, tzinfo=dt.timezone.utc)
        maintenant = dt.datetime(2026, 9, 29, 8, 0, tzinfo=PARIS)
        iso, aujourdhui = serve.horodatage_releve(moment, PARIS, maintenant=maintenant)
        self.assertEqual(iso, "2026-09-29T01:30+02:00")
        self.assertTrue(aujourdhui)

    def test_maintenant_par_defaut_est_l_heure_courante(self):
        iso, aujourdhui = serve.horodatage_releve(dt.datetime.now(dt.timezone.utc), PARIS)
        self.assertTrue(aujourdhui)
        self.assertRegex(iso, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[+-]\d{2}:\d{2}$")

    def test_le_texte_envoye_ne_contient_aucun_mot(self):
        moment = dt.datetime(2026, 9, 26, 8, 5, tzinfo=dt.timezone.utc)
        iso, _ = serve.horodatage_releve(moment, PARIS)
        self.assertNotRegex(iso, r"[A-SU-Za-z]")   # seul le « T » de l'ISO


class TestsSourceDuServeur(unittest.TestCase):
    def test_plus_de_phrase_ni_de_format_francais_dans_les_donnees_de_la_page(self):
        source = (Path(__file__).parent / "serve.py").read_text(encoding="utf-8")
        self.assertNotIn("type Blink «", source)
        self.assertNotIn('"%d/%m à %H:%M"', source)
        # Le relevé passe par horodatage_releve(), pas par un strftime local.
        self.assertIn("horodatage_releve(moment, self.timezone)", source)
        self.assertIsNone(re.search(r'measured\s*=\s*local\.strftime', source))


if __name__ == "__main__":
    unittest.main()
