"""Groupement par jour de la vue journalières (issue #14) : sans lui, voir
toutes les caméras d'une même journée oblige à rouvrir chaque caméra une
par une. label d'une journalière est déjà AAAA-MM-JJ (merge_daily.py,
f"{day}_{camera}.mp4"), le tri alphabétique EST le tri chronologique."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

from test_serve_app_js_datetime import formatting_source


class TestsGroupementVideosParJour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("node introuvable")
        source = (Path(__file__).parent / "serve_app.js").read_text(encoding="utf-8")
        fragments = []
        for nom in ("duration", "regroupable", "renderVideos", "videoCard"):
            correspondance = re.search(
                rf"^(?:async )?function {nom}\(.*?^\}}", source, re.DOTALL | re.MULTILINE,
            )
            if correspondance is None:
                raise AssertionError(f"fonction {nom}() introuvable")
            fragments.append(correspondance.group(0))
        cls.javascript = formatting_source(source) + "\n" + "\n".join(fragments)

    def _executer(self, videos_daily: list, group_by: str, camera_filtre: str = "") -> dict:
        script = f"""
const h = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({{
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}})[char]);
const avecJeton = (url) => url;
function t(cle) {{ return cle; }}
function tf(cle, valeurs) {{ return cle; }}
const estMasquee = () => false; const comparerNoms = (a, b) => String(a).localeCompare(String(b));

const boxes = {{
  camera: {{ value: {camera_filtre!r} }},
  groupBy: {{ value: {group_by!r} }},
  count: {{ set textContent(v) {{}} }},
  list: {{ innerHTML: "" }},
}};
function $(id) {{ return boxes[id]; }}

const videos = {{ daily: {videos_daily} }};

{self.javascript}

renderVideos("daily");
process.stdout.write(boxes.list.innerHTML);
"""
        resultat = subprocess.run(
            [self.node, "-e", script], capture_output=True, text=True, timeout=60,
        )
        if resultat.returncode != 0:
            self.fail(f"Node a échoué : {resultat.stderr}")
        return resultat.stdout

    def _evaluer(self, expression: str, camera_filtre: str = "") -> str:
        """Évalue une expression JavaScript dans le même décor que _executer."""
        script = f"""
const h = (value) => String(value ?? "");
const avecJeton = (url) => url;
function t(cle) {{ return cle; }}
function tf(cle, valeurs) {{ return cle; }}
const estMasquee = () => false; const comparerNoms = (a, b) => String(a).localeCompare(String(b));
const boxes = {{ camera: {{ value: {camera_filtre!r} }}, groupBy: {{ value: "day" }} }};
function $(id) {{ return boxes[id]; }}
const videos = {{ daily: [] }};
{self.javascript}
process.stdout.write(String({expression}));
"""
        resultat = subprocess.run(
            [self.node, "-e", script], capture_output=True, text=True, timeout=60,
        )
        if resultat.returncode != 0:
            self.fail(f"Node a échoué : {resultat.stderr}")
        return resultat.stdout

    def _video(self, camera: str, label: str, path: str = "x.mp4") -> dict:
        return {
            "kind": "daily", "camera": camera, "label": label,
            "path": path, "duration": 60,
        }

    def test_groupe_par_camera_est_le_comportement_par_defaut(self):
        html = self._executer(
            [self._video("Jardin", "2026-09-20"), self._video("Salon", "2026-09-20")],
            group_by="camera",
        )
        self.assertLess(html.index("<h2>Jardin</h2>"), html.index("<h2>Salon</h2>"))

    def test_groupe_par_jour_rassemble_toutes_les_cameras_d_un_meme_jour(self):
        html = self._executer(
            [self._video("Jardin", "2026-09-19"), self._video("Salon", "2026-09-20"),
             self._video("Jardin", "2026-09-20")],
            group_by="day",
        )
        # Deux groupes de jour seulement (pas un par camera : sans le
        # groupement, "Jardin" ferait un 3e groupe avec ses 2 videos).
        self.assertEqual(html.count("<h2>"), 2)
        # Le seul jour a avoir 2 cameras (le 20) doit en montrer 2 avant que
        # le second groupe (le 19, une seule camera) n'apparaisse : "Salon"
        # n'existe que dans le groupe du 20, jamais dans celui du 19.
        self.assertLess(html.index("Salon"), html.rindex("Jardin"))
        self.assertLess(html.index("Jardin"), html.index("Salon"))

    def test_groupe_par_jour_affiche_la_camera_sur_chaque_carte(self):
        html = self._executer([self._video("Jardin", "2026-09-20")], group_by="day")
        self.assertIn('<div class="time">Jardin</div>', html)
        # Le label (identique a la date deja en h2) ne doit pas etre repete.
        self.assertNotIn('<div class="time">2026-09-20</div>', html)

    def test_groupe_par_camera_affiche_le_label_sur_chaque_carte(self):
        html = self._executer([self._video("Jardin", "2026-09-20")], group_by="camera")
        self.assertIn('<div class="time">2026-09-20</div>', html)


    # Issue #37 : avec une seule caméra choisie, chaque jour n'avait qu'une
    # carte, seule sur sa ligne sous son propre titre.

    def test_camera_choisie_groupe_par_jour_donne_une_seule_grille(self):
        jours = ("2026-09-20", "2026-09-19", "2026-09-18")
        html = self._executer([self._video("Jardin", jour) for jour in jours],
                              group_by="day", camera_filtre="Jardin")
        self.assertEqual(html.count("<h2>"), 1)
        self.assertEqual(html.count("<h2>Jardin</h2>"), 1)
        self.assertEqual(html.count('class="grid wide"'), 1)
        self.assertEqual(html.count('class="card"'), 3)

    def test_camera_choisie_chaque_carte_porte_sa_date(self):
        # Plus de titre par jour : la date passe sur la carte, comme dans le
        # groupement par caméra.
        jours = ("2026-09-20", "2026-09-19")
        html = self._executer([self._video("Jardin", jour) for jour in jours],
                              group_by="day", camera_filtre="Jardin")
        for jour in jours:
            self.assertIn(f'<div class="time">{jour}</div>', html)
        self.assertNotIn('<div class="time">Jardin</div>', html)

    def test_camera_choisie_les_journees_gardent_l_ordre_du_serveur(self):
        # Le serveur les envoie de la plus récente à la plus ancienne.
        html = self._executer(
            [self._video("Jardin", "2026-09-20"), self._video("Jardin", "2026-09-19")],
            group_by="day", camera_filtre="Jardin")
        self.assertLess(html.index("2026-09-20"), html.index("2026-09-19"))

    def test_une_autre_camera_n_apparait_pas(self):
        html = self._executer(
            [self._video("Jardin", "2026-09-20"), self._video("Salon", "2026-09-20")],
            group_by="day", camera_filtre="Jardin")
        self.assertNotIn("Salon", html)

    def test_sans_camera_choisie_le_groupement_par_jour_reste(self):
        html = self._executer(
            [self._video("Jardin", "2026-09-19"), self._video("Jardin", "2026-09-20")],
            group_by="day")
        self.assertEqual(html.count("<h2>"), 2)

    def test_le_choix_ne_se_pose_que_pour_les_journalieres_sans_camera(self):
        self.assertEqual(self._evaluer('regroupable("daily")'), "true")
        self.assertEqual(self._evaluer('regroupable("daily")', camera_filtre="Jardin"), "false")
        for genre in ("weekly", "monthly", "clips", "live"):
            with self.subTest(genre=genre):
                self.assertEqual(self._evaluer(f'regroupable("{genre}")'), "false")

    def test_le_selecteur_disparait_avec_une_camera_et_revient_sans(self):
        # Le choix « Grouper par » se cache d'après la même fonction que
        # renderVideos() : les deux ne peuvent pas diverger. Depuis l'issue #36
        # (suite), majGroupBy() est le seul endroit qui pose l'attribut, appelé
        # par render(), à l'ouverture du filtre et au changement de caméra.
        source = (Path(__file__).parent / "serve_app.js").read_text(encoding="utf-8")
        self.assertIn('$("groupBySection").hidden = !regroupable($("view").value);', source)
        self.assertIn('regroupable(kind) && $("groupBy").value === "day"', source)


if __name__ == "__main__":
    unittest.main()
