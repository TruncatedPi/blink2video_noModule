"""Enregistrement d'alerte côté serveur, sans compte Blink ni navigateur."""

from __future__ import annotations

import io
import os
import queue
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ["BLINK_BOOTSTRAP"] = "none"
os.environ["BLINK_HOME"] = tempfile.mkdtemp(prefix="blink-alert-record-")

import serve
from test_serve_live_mse_enregistrement_fragmente import _segment_synthetique, _fragment
import test_serve_webrtc_sessions as live_fixtures


class DoorbellRecordingTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(prefix="blink-alert-video-")
        self.addCleanup(self.home.cleanup)
        self.root = Path(self.home.name)
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.stop = threading.Event()
        self.stack.enter_context(mock.patch.object(serve, "DOORBELL_MONITOR_STOP", self.stop))
        self.stack.enter_context(mock.patch.object(serve, "DOORBELL_EVENTS", []))
        self.stack.enter_context(mock.patch.object(serve, "DOORBELL_SEEN_EVENTS", {}))
        self.stack.enter_context(mock.patch.object(serve, "DOSSIER_DIRECT", self.root))
        self.stack.enter_context(mock.patch.object(serve, "_sauvegarder_evenements_sonnette"))
        self.stack.enter_context(mock.patch.object(serve, "_journal_direct"))
        self.settings = {"doorbell_alerts_enabled": True, "doorbell_auto_record": True,
                         "doorbell_auto_record_seconds": 30}
        self.stack.enter_context(mock.patch.object(serve.runtime, "lire_reglages", return_value=self.settings))
        stop = self.stop

        class Queue(queue.Queue):
            def task_done(self):
                super().task_done()
                stop.set()
        self.jobs = Queue()
        self.stack.enter_context(mock.patch.object(serve, "DOORBELL_RECORD_QUEUE", self.jobs))
        self.event = dict(source_event_id="button-event", id="button-event", camera="Porte",
                          camera_key="camera-key", timestamp="2026-10-05T12:00:00+00:00",
                          type="ring", verified=True)

    def test_evenement_n_est_planifie_qu_une_fois(self):
        serve._publier_evenements_sonnette([self.event], self.settings)
        serve._publier_evenements_sonnette([self.event], self.settings)
        self.assertEqual(self.jobs.qsize(), 1)
        self.assertEqual(len(serve.DOORBELL_EVENTS), 1)
        self.assertEqual(serve.DOORBELL_EVENTS[0]["recording_status"], "pending")

    def test_enregistrement_desactive_ne_cree_aucun_travail(self):
        serve._publier_evenements_sonnette([self.event], dict(self.settings, doorbell_auto_record=False))
        self.assertTrue(self.jobs.empty())

    def test_desactivation_pendant_attente_annule_enregistrement(self):
        serve._publier_evenements_sonnette([self.event], self.settings)
        self.settings["doorbell_auto_record"] = False
        with mock.patch.object(serve, "_EnregistreurSonnette") as recorder:
            serve._doorbell_record_loop()
        recorder.assert_not_called()
        self.assertEqual(serve.DOORBELL_EVENTS[0]["recording_status"], "cancelled")

    def test_stop_annule_les_alertes_encore_en_file(self):
        serve._publier_evenements_sonnette([self.event], self.settings)
        with mock.patch.object(serve, "DOORBELL_MONITOR_THREAD", None), \
             mock.patch.object(serve, "DOORBELL_RECORD_THREAD", None), \
             mock.patch.object(serve, "DIRECT_MSE_SESSION", {}):
            serve.arreter_moniteur_evenements()
        self.assertTrue(self.jobs.empty())
        self.assertEqual(serve.DOORBELL_EVENTS[0]["recording_status"], "cancelled")

    def test_stop_attend_fermeture_video_et_session_blink(self):
        live = live_fixtures.TestsSessionsDirect()
        live.setUp()
        self.addCleanup(live.tearDown)
        serve._publier_evenements_sonnette([self.event], self.settings)
        en_lecture = threading.Event()
        reads = []

        def read(_delay):
            reads.append(True)
            if len(reads) == 1:
                return _fragment(1)
            en_lecture.set()
            serve.DIRECT_MSE_SESSION["session"]["arret"].wait(timeout=2)
            return None

        process = mock.Mock(stdout=io.BytesIO(), stderr=io.BytesIO())
        reader = mock.Mock(lire=mock.Mock(side_effect=read))
        worker = threading.Thread(target=serve._doorbell_record_loop, daemon=True)
        with mock.patch.object(serve.Handler, "ffmpeg", "ffmpeg-factice"), \
             mock.patch.object(serve.runtime, "demarrer", return_value=process), \
             mock.patch.object(serve, "LecteurTube", return_value=reader), \
             mock.patch.object(serve, "read_mp4_init_segment", return_value=_segment_synthetique()), \
             mock.patch.object(serve, "DOORBELL_RECORD_THREAD", worker), \
             mock.patch.object(serve, "DOORBELL_MONITOR_THREAD", None):
            worker.start()
            try:
                self.assertTrue(en_lecture.wait(timeout=3))
            finally:
                serve.arreter_moniteur_evenements()
            self.assertFalse(worker.is_alive())
        saved = next(self.root.rglob("*.mp4"))
        self.assertTrue(serve.md.valid_mp4(saved))
        live.flux.stop.assert_called_once()
        live.verrou.__exit__.assert_called_once()
        self.assertTrue(live.slot.acquire(blocking=False))
        live.slot.release()

    def test_erreur_de_module_est_visible_dans_evenement(self):
        serve._publier_evenements_sonnette([self.event], self.settings)
        with mock.patch.object(serve, "_EnregistreurSonnette") as recorder:
            recorder.return_value.error = "Live stream busy"
            serve._doorbell_record_loop()
        event = serve.DOORBELL_EVENTS[0]
        self.assertEqual(event["recording_status"], "failed")
        self.assertIn("busy", event["recording_error"])

    def test_sans_navigateur_fichier_valide_et_duree_apres_premier_fragment(self):
        live = live_fixtures.TestsSessionsDirect()
        live.setUp()
        self.addCleanup(live.tearDown)
        serve._publier_evenements_sonnette([self.event], self.settings)
        now = [0.0]
        reads = []
        fragments = [_fragment(1), _fragment(2)]

        def read(_delay):
            reads.append(now[0])
            if len(reads) == 1:
                now[0] = 40.0  # Réveil lent : ne consomme pas les 30 s de vidéo.
                return fragments[0]
            if len(reads) == 2:
                now[0] = 69.0
                return fragments[1]
            now[0] = 70.0
            return None

        clock = SimpleNamespace(monotonic=lambda: now[0], time=time.time, sleep=time.sleep)
        process = mock.Mock(stdout=io.BytesIO(), stderr=io.BytesIO())
        reader = mock.Mock(lire=mock.Mock(side_effect=read))
        with mock.patch.object(serve, "time", clock), \
             mock.patch.object(serve.Handler, "ffmpeg", "ffmpeg-factice"), \
             mock.patch.object(serve.runtime, "demarrer", return_value=process), \
             mock.patch.object(serve, "LecteurTube", return_value=reader), \
             mock.patch.object(serve, "read_mp4_init_segment", return_value=_segment_synthetique()):
            serve._doorbell_record_loop()
        saved = list(self.root.rglob("*.mp4"))
        self.assertEqual(len(saved), 1)
        self.assertTrue(serve.md.valid_mp4(saved[0]))
        self.assertEqual(saved[0].read_bytes(), _segment_synthetique() + b"".join(fragments))
        self.assertEqual(serve.DOORBELL_EVENTS[0]["recording_status"], "recorded")
        self.assertEqual(len(reads), 3)
        live.flux.stop.assert_called_once()
        live.verrou.__exit__.assert_called_once()
        self.assertTrue(live.slot.acquire(blocking=False))
        live.slot.release()
        self.assertFalse(serve.ENREGISTREMENT_DIRECT_ACTIF.is_set())

    def test_arret_milieu_mdat_conserve_seulement_fragments_complets(self):
        path = self.root / "fragmented.mp4"
        complete = _segment_synthetique() + _fragment(1)
        file = path.open("wb")
        file.write(complete + _fragment(2)[:-30])
        serve._fermer_enregistrement_direct(file)
        self.assertEqual(path.read_bytes(), complete)
        self.assertTrue(serve.md.valid_mp4(path))

    def test_erreur_flux_apres_premier_fragment_reste_visible(self):
        live = live_fixtures.TestsSessionsDirect()
        live.setUp()
        self.addCleanup(live.tearDown)
        serve._publier_evenements_sonnette([self.event], self.settings)
        process = mock.Mock(stdout=io.BytesIO(), stderr=io.BytesIO())
        reader = mock.Mock(lire=mock.Mock(side_effect=[
            _fragment(1), RuntimeError("relais interrompu")]))
        with mock.patch.object(serve.Handler, "ffmpeg", "ffmpeg-factice"), \
             mock.patch.object(serve.runtime, "demarrer", return_value=process), \
             mock.patch.object(serve, "LecteurTube", return_value=reader), \
             mock.patch.object(serve, "read_mp4_init_segment", return_value=_segment_synthetique()):
            serve._doorbell_record_loop()
        self.assertEqual(serve.DOORBELL_EVENTS[0]["recording_status"], "failed")
        self.assertIn("relais interrompu", serve.DOORBELL_EVENTS[0]["recording_error"])
        self.assertTrue(serve.md.valid_mp4(next(self.root.rglob("*.mp4"))))

    def test_video_ffmpeg_reelle_reste_decodable_apres_arret_automatique(self):
        try:
            ffmpeg = serve.md.find_ffmpeg()
        except RuntimeError as error:
            self.skipTest(str(error))
        live = live_fixtures.TestsSessionsDirect()
        live.setUp()
        self.addCleanup(live.tearDown)
        settings = dict(self.settings, doorbell_auto_record_seconds=1)
        serve._publier_evenements_sonnette([self.event], settings)

        def source_video(*_args, **_kwargs):
            # Même sortie fMP4 que le relais remuxé : le codec et le décodage
            # sont réels ; seul le matériel Blink est remplacé par une mire.
            return subprocess.Popen([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi",
                "-i", "testsrc=size=640x360:rate=10:duration=8", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-g", "5", "-an",
                "-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                "pipe:1"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, creationflags=serve.runtime.SANS_FENETRE)

        with mock.patch.object(serve.Handler, "ffmpeg", ffmpeg), \
             mock.patch.object(serve.runtime, "demarrer", side_effect=source_video):
            serve._doorbell_record_loop()
        files = list(self.root.rglob("*.mp4"))
        self.assertEqual(len(files), 1)
        self.assertEqual(serve.DOORBELL_EVENTS[0]["recording_status"], "recorded")
        self.assertTrue(serve.md.valid_mp4_complet(files[0]))
        facts = serve.probe_facts(ffmpeg, files[0])
        self.assertGreater(facts[0], 0)
        self.assertIn(b"moov", files[0].read_bytes())
        self.assertIn(b"moof", files[0].read_bytes())


if __name__ == "__main__":
    unittest.main()
