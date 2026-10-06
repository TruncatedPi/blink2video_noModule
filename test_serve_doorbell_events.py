"""Unit tests for doorbell event alerts and live recording controls (Feature 1).

Covers:
- Doorbell settings in runtime and validation in web settings handler.
- Event queue, retrieval via GET /api/events, acknowledging via POST /api/events/ack.
- Test alert trigger via POST /api/events/test.
- Required UI elements and i18n keys for English and French.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

os.environ["BLINK_BOOTSTRAP"] = "none"
_TEST_HOME = tempfile.TemporaryDirectory(prefix="blink-doorbell-")
os.environ["BLINK_HOME"] = _TEST_HOME.name

import runtime
import serve


class TestDoorbellEvents(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="blink_doorbell_test_")
        self.root = Path(self.tmp_dir.name)
        self.paths = {
            "input": self.root / "clips",
            "normalized": self.root / "normalized",
            "excluded": self.root / "excluded",
            "thumbs": self.root / "thumbs",
            "direct": self.root / "direct",
        }
        for path in self.paths.values():
            path.mkdir(parents=True, exist_ok=True)

        # Clear events before each test
        with serve.DOORBELL_EVENTS_LOCK:
            serve.DOORBELL_EVENTS.clear()

    def tearDown(self) -> None:
        with serve.DOORBELL_EVENTS_LOCK:
            serve.DOORBELL_EVENTS.clear()
        self.tmp_dir.cleanup()

    def build_handler(self) -> serve.Handler:
        """Constructs an isolated Handler instance with authorization headers."""
        handler = serve.Handler.__new__(serve.Handler)
        handler.paths = self.paths
        handler.initial_setup = False
        handler.headers = {
            "Host": "127.0.0.1",
            "X-Blink-Token": serve.TOKEN,
        }
        return handler

    def call_get(self, handler: serve.Handler, path: str = "/api/events") -> tuple[int, dict]:
        """Performs a simulated GET request on the handler."""
        handler.path = path
        responses = []
        handler.send_json = lambda payload, code=200: responses.append((code, payload))
        handler.do_GET()
        return responses[0]

    def call_post(self, handler: serve.Handler, path: str, payload: dict) -> tuple[int, dict]:
        """Performs a simulated POST request with JSON payload."""
        body = json.dumps(payload).encode("utf-8")
        handler.path = path
        handler.headers = {
            **handler.headers,
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
            "X-Blink-Token": serve.TOKEN,
        }
        handler.rfile = io.BytesIO(body)
        responses = []
        handler.send_json = lambda payload, code=200: responses.append((code, payload))
        handler.do_POST()
        return responses[0]

    def test_default_settings(self) -> None:
        """Verifies default doorbell configuration in runtime."""
        settings = runtime.REGLAGES_DEFAUT
        self.assertTrue(settings["doorbell_alerts_enabled"])
        self.assertFalse(settings["doorbell_auto_record"])
        self.assertEqual(settings["doorbell_auto_record_seconds"], 30)
        self.assertTrue(settings["doorbell_chime_enabled"])
        self.assertEqual(settings["doorbell_poll_interval_seconds"], 6)

    def test_preparer_reglages_web_validation(self) -> None:
        """Validates sanitization and limits in _preparer_reglages_web."""
        payload = {
            "usb_minutes": 5,
            "cloud_minutes": 15,
            "port": 5000,
            "timezone": "UTC",
            "doorbell_alerts_enabled": False,
            "doorbell_auto_record": True,
            "doorbell_auto_record_seconds": 45,
            "doorbell_chime_enabled": False,
            "doorbell_poll_interval_seconds": 10,
        }
        dossier, reglages = serve._preparer_reglages_web(payload)
        self.assertFalse(reglages["doorbell_alerts_enabled"])
        self.assertTrue(reglages["doorbell_auto_record"])
        self.assertEqual(reglages["doorbell_auto_record_seconds"], 45)
        self.assertFalse(reglages["doorbell_chime_enabled"])
        self.assertEqual(reglages["doorbell_poll_interval_seconds"], 10)

    def test_reglages_omis_conservent_valeurs_existantes(self) -> None:
        settings = dict(runtime.REGLAGES_DEFAUT, doorbell_auto_record=True,
                        doorbell_auto_record_seconds=45, doorbell_poll_interval_seconds=37)
        with mock.patch.object(runtime, "lire_reglages", return_value=settings):
            _, prepared = serve._preparer_reglages_web(
                {"timezone": "UTC", "usb_minutes": 10, "cloud_minutes": 1, "port": 8765})
        for field in ("doorbell_auto_record", "doorbell_auto_record_seconds", "doorbell_poll_interval_seconds"):
            self.assertEqual(prepared[field], settings[field])

    def test_reglages_invalides_ne_se_reinitialisent_pas_en_silence(self) -> None:
        for payload, expected in (({"doorbell_auto_record": "false"}, "booléen"),
                                  ({"doorbell_auto_record_seconds": 420}, "durée"),
                                  ({"doorbell_poll_interval_seconds": 0}, "intervalle")):
            with self.subTest(payload=payload), self.assertRaisesRegex(serve._ReglagesInvalides, expected):
                serve._preparer_reglages_web(dict(payload, timezone="UTC", usb_minutes=10,
                                                 cloud_minutes=1, port=8765))

    def test_ancien_historique_est_conserve_mais_non_confirme(self) -> None:
        path = self.root / serve.DOORBELL_EVENTS_FILE
        path.write_text(json.dumps([{"id": "old-heartbeat", "type": "motion", "acknowledged": False}]), encoding="utf-8")
        with mock.patch.object(runtime, "app_dir", return_value=self.root):
            events = serve._charger_evenements_sonnette()
        self.assertEqual(events[0]["type"], "unknown")
        self.assertTrue(events[0]["acknowledged"])

    def test_etat_versionne_recharge_evenements_confirmes(self) -> None:
        path = self.root / serve.DOORBELL_EVENTS_FILE
        path.write_text(json.dumps({"version": 2, "events": [{"id": "new-ring", "type": "ring",
                        "verified": True, "acknowledged": False}], "seen": {}}), encoding="utf-8")
        with mock.patch.object(runtime, "app_dir", return_value=self.root):
            events = serve._charger_evenements_sonnette()
        self.assertEqual(events[0]["type"], "ring")
        self.assertFalse(events[0]["acknowledged"])

    def test_get_events_empty(self) -> None:
        """GET /api/events returns empty lists when no events exist."""
        handler = self.build_handler()
        code, data = self.call_get(handler, "/api/events")
        self.assertEqual(code, 200)
        self.assertEqual(data["events"], [])
        self.assertEqual(data["unacknowledged"], [])
        self.assertIn("doorbell_alerts_enabled", data)

    def test_post_events_test_and_get(self) -> None:
        """POST /api/events/test enqueues an event that appears in GET /api/events."""
        handler = self.build_handler()
        code, res = self.call_post(handler, "/api/events/test", {"camera": "Front Door"})
        self.assertEqual(code, 200)
        self.assertTrue(res["ok"])
        event = res["event"]
        self.assertEqual(event["camera"], "Front Door")
        self.assertEqual(event["type"], "ring")
        self.assertFalse(event["acknowledged"])

        code, get_res = self.call_get(handler, "/api/events")
        self.assertEqual(code, 200)
        self.assertEqual(len(get_res["events"]), 1)
        self.assertEqual(len(get_res["unacknowledged"]), 1)
        self.assertEqual(get_res["unacknowledged"][0]["id"], event["id"])

    def test_get_events_since_filter(self) -> None:
        """GET /api/events?since=... filters out older events."""
        handler = self.build_handler()
        t0 = time.time()
        self.call_post(handler, "/api/events/test", {"camera": "Door 1"})
        time.sleep(0.02)
        t_mid = time.time()
        self.call_post(handler, "/api/events/test", {"camera": "Door 2"})

        code, all_events = self.call_get(handler, f"/api/events?since={t0 - 1}")
        self.assertEqual(len(all_events["events"]), 2)

        code, filtered = self.call_get(handler, f"/api/events?since={t_mid}")
        self.assertEqual(len(filtered["events"]), 1)
        self.assertEqual(filtered["events"][0]["camera"], "Door 2")

    def test_post_events_ack_specific_and_all(self) -> None:
        """POST /api/events/ack marks individual or all events acknowledged."""
        handler = self.build_handler()
        _, res1 = self.call_post(handler, "/api/events/test", {"camera": "Cam 1"})
        _, res2 = self.call_post(handler, "/api/events/test", {"camera": "Cam 2"})
        evt1_id = res1["event"]["id"]
        evt2_id = res2["event"]["id"]

        # Ack first event only
        code, ack_res = self.call_post(handler, "/api/events/ack", {"event_id": evt1_id})
        self.assertEqual(code, 200)
        self.assertTrue(ack_res["ok"])

        _, get_res = self.call_get(handler, "/api/events")
        self.assertEqual(len(get_res["unacknowledged"]), 1)
        self.assertEqual(get_res["unacknowledged"][0]["id"], evt2_id)

        # Ack all
        code, ack_res2 = self.call_post(handler, "/api/events/ack", {"all": True})
        self.assertEqual(code, 200)

        _, get_res2 = self.call_get(handler, "/api/events")
        self.assertEqual(len(get_res2["unacknowledged"]), 0)

    def test_html_and_i18n_elements_present(self) -> None:
        """Verifies that all required HTML elements exist in serve.PAGE and i18n keys exist."""
        page_html = serve.PAGE
        required_ids = [
            'id="doorbellAlertBanner"',
            'id="doorbellAlertTitle"',
            'id="doorbellAlertSubtitle"',
            'id="btnAlertRecord"',
            'id="btnAlertWatch"',
            'id="btnAlertDismiss"',
            'id="doorbellAlertsEnabled"',
            'id="doorbellChimeEnabled"',
            'id="doorbellAutoRecord"',
            'id="doorbellAutoRecordSeconds"',
            'id="btnTestDoorbellAlert"',
        ]
        for req_id in required_ids:
            self.assertIn(req_id, page_html, f"Missing element {req_id} in serve.PAGE")

        app_js = (Path(__file__).parent / "serve_app.js").read_text(encoding="utf-8")
        required_i18n_keys = [
            "doorbell.ring",
            "doorbell.motion",
            "doorbell.recordLive",
            "doorbell.watchLive",
            "doorbell.dismiss",
            "doorbell.justNow",
            "doorbell.test",
            "reglages.doorbellSection",
            "reglages.doorbellAlertsEnabled",
            "reglages.doorbellChimeEnabled",
            "reglages.doorbellAutoRecord",
            "reglages.doorbellAutoRecordSeconds",
            "events.viewRecordings",
        ]
        for key in required_i18n_keys:
            self.assertIn(f'"{key}":', app_js, f"Missing i18n key {key} in serve_app.js")

    def test_evenement_reel_pendant_direct_autre_camera_est_conserve(self) -> None:
        event = {"source_event_id": "real-ring", "camera": "Porte", "type": "ring",
                 "timestamp": "2026-10-05T12:00:00+00:00", "verified": True}
        with mock.patch.object(serve, "MODULE_SLOT_INFO", {"quoi": "direct WebRTC", "name": "Jardin"}), \
             mock.patch.object(serve, "DOORBELL_SEEN_EVENTS", {}), \
             mock.patch.object(serve, "_sauvegarder_evenements_sonnette"):
            serve._publier_evenements_sonnette([event], {"doorbell_auto_record": False})
        self.assertEqual([e["type"] for e in serve.DOORBELL_EVENTS], ["ring"])

    def test_post_arm_ne_cree_aucune_alerte(self) -> None:
        handler = self.build_handler()
        handler.set_armed = lambda scope, name, armed: None
        handler.system_state = lambda: {"systems": []}
        code, res = self.call_post(handler, "/api/arm", {"name": "TestCam", "scope": "camera", "armed": True})
        self.assertEqual(code, 200)
        self.assertEqual(serve.DOORBELL_EVENTS, [])

    def test_describe_camera_enabled_priority(self) -> None:
        """Verifies that describe_camera uses info['enabled'] from homescreen."""
        handler = self.build_handler()
        handler.timezone = "UTC"
        class MockCamera:
            name = "TestCam"
            motion_enabled = False
            attributes = {}
        cam = MockCamera()
        raw = {"TestCam": [{"id": "1", "enabled": True, "status": "online"}]}
        desc = handler.describe_camera("TestCam", cam, raw)
        self.assertTrue(desc["armed"])

    def test_post_events_clear(self) -> None:
        """POST /api/events/clear removes all events."""
        handler = self.build_handler()
        self.call_post(handler, "/api/events/test", {"camera": "Cam 1"})
        _, get_res = self.call_get(handler, "/api/events")
        self.assertEqual(len(get_res["events"]), 1)

        code, clear_res = self.call_post(handler, "/api/events/clear", {})
        self.assertEqual(code, 200)
        self.assertTrue(clear_res["ok"])

        _, get_res2 = self.call_get(handler, "/api/events")
        self.assertEqual(len(get_res2["events"]), 0)


if __name__ == "__main__":
    unittest.main()
