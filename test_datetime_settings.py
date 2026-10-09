"""Saved date/time preferences and fixed UTC-07:00 server behavior."""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import runtime


class DateTimeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(prefix="blink-datetime-")
        self.addCleanup(self.home.cleanup)
        self.root = Path(self.home.name)
        patch = mock.patch.object(runtime, "app_dir", return_value=self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def test_format_preferences_round_trip_and_survive_older_callers(self):
        settings = runtime.lire_reglages()
        settings.update(timezone="Etc/GMT+7", date_format="mdy", time_format="12h")
        runtime.ecrire_reglages(**settings)
        self.assertEqual(runtime.lire_reglages(), settings)
        settings.pop("date_format")
        settings.pop("time_format")
        runtime.ecrire_reglages(**settings)
        reread = runtime.lire_reglages()
        self.assertEqual(reread["date_format"], "mdy")
        self.assertEqual(reread["time_format"], "12h")
        self.assertEqual(reread["timezone"], "Etc/GMT+7")

    def test_bad_formats_fall_back_to_safe_defaults(self):
        for value in (None, [], {}, "unknown", 12):
            (self.root / runtime.REGLAGES).write_text(
                json.dumps({"date_format": value, "time_format": value}), encoding="utf-8")
            settings = runtime.lire_reglages()
            self.assertEqual(settings["date_format"], "iso")
            self.assertEqual(settings["time_format"], "24h")

    def test_explicit_timezone_is_not_overridden_by_system_timezone(self):
        (self.root / runtime.REGLAGES).write_text(
            json.dumps({"timezone": "Europe/Paris"}), encoding="utf-8")
        with mock.patch.object(runtime, "detect_system_timezone", return_value="America/Los_Angeles"):
            self.assertEqual(runtime.lire_reglages()["timezone"], "Europe/Paris")

    def test_windows_no_dst_uses_fixed_current_offset(self):
        registry = mock.MagicMock()
        values = {"TimeZoneKeyName": "Pacific Standard Time", "DynamicDaylightTimeDisabled": 1}
        registry.QueryValueEx.side_effect = lambda key, name: (values[name], 0)
        clock = mock.Mock()
        clock.now.return_value.astimezone.return_value.utcoffset.return_value = dt.timedelta(hours=-7)
        with mock.patch.object(runtime.sys, "platform", "win32"), \
             mock.patch.dict(os.environ, {"TZ": ""}), \
             mock.patch.dict(sys.modules, {"winreg": registry}), \
             mock.patch.object(runtime.dt, "datetime", clock):
            self.assertEqual(runtime.detect_system_timezone(), "Etc/GMT+7")

    def test_build_timestamp_retains_commit_offset_for_ui_conversion(self):
        process = mock.Mock(returncode=0, stdout="2026-10-09T15:34:55-07:00\n")
        with mock.patch.object(runtime.subprocess, "run", return_value=process):
            self.assertEqual(runtime.git_commit_timestamp(), "2026-10-09T15:34:55-07:00")
        with mock.patch.object(runtime.subprocess, "run", side_effect=OSError):
            self.assertEqual(runtime.git_commit_timestamp(), "")

    def test_fixed_zone_server_offset_is_identical_in_winter_and_summer(self):
        zone = ZoneInfo("Etc/GMT+7")
        for month in (1, 7, 11):
            local = dt.datetime(2026, month, 15, 19, 18, 20, tzinfo=dt.timezone.utc).astimezone(zone)
            self.assertEqual(local.utcoffset(), dt.timedelta(hours=-7))
            self.assertEqual(local.hour, 12)


class DateTimeHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.TemporaryDirectory(prefix="blink-datetime-http-")
        with mock.patch.dict(os.environ, {"BLINK_HOME": cls.home.name, "BLINK_BOOTSTRAP": "none"}):
            import serve
        cls.serve = serve

    @classmethod
    def tearDownClass(cls):
        cls.home.cleanup()

    def test_page_bootstrap_has_formats_and_actual_server_zone(self):
        handler = object.__new__(self.serve.Handler)
        handler.path = "/"
        handler.timezone = ZoneInfo("Etc/GMT+7")
        handler.wfile = io.BytesIO()
        handler.hote_autorise = mock.Mock(return_value=True)
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        settings = dict(runtime.REGLAGES_DEFAUT, date_format="mdy", time_format="12h",
                        timezone="America/Los_Angeles")
        with mock.patch.object(runtime, "lire_reglages", return_value=settings):
            handler.do_GET()
        page = handler.wfile.getvalue().decode("utf-8")
        self.assertNotIn("__DATE_TIME_SETTINGS__", page)
        bootstrap = json.loads(re.search(r"const AFFICHAGE_DATES = (.*);", page).group(1))
        self.assertEqual(bootstrap, {"timezone": "Etc/GMT+7", "date_format": "mdy", "time_format": "12h"})
        self.assertIn('id="dateFormat"', page)
        self.assertIn('id="timezonePacific"', page)

    def test_http_validates_formats_and_preserves_omitted_preferences(self):
        settings = dict(runtime.REGLAGES_DEFAUT, date_format="mdy", time_format="12h")
        payload = dict(usb_minutes=10, cloud_minutes=1, port=8765, timezone="Etc/GMT+7")
        with mock.patch.object(runtime, "lire_reglages", return_value=settings):
            _, saved = self.serve._preparer_reglages_web(payload)
            self.assertEqual(saved["date_format"], "mdy")
            self.assertEqual(saved["time_format"], "12h")
            for field in ("date_format", "time_format"):
                with self.subTest(field=field), self.assertRaises(self.serve._ReglagesInvalides):
                    self.serve._preparer_reglages_web({**payload, field: "bad"})
            _, saved = self.serve._preparer_reglages_web(
                {**payload, "date_format": "dmy", "time_format": "24h"})
            self.assertEqual(saved["date_format"], "dmy")
            self.assertEqual(saved["time_format"], "24h")


if __name__ == "__main__":
    unittest.main()
