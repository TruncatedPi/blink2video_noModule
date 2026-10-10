"""Date/time display uses saved formats and zone, independently of the browser."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path


def formatting_source(source, settings=None):
    settings = settings or {"timezone": "UTC", "date_format": "iso", "time_format": "24h"}
    start = source.index("const AFFICHAGE_DATES =")
    end = source.index("// Préférence de lecture", start)
    return source[start:end].replace("__DATE_TIME_SETTINGS__", json.dumps(settings))


def function_source(source, name):
    match = re.search(rf"^(?:async )?function {name}\(.*?^\}}", source, re.M | re.S)
    if not match:
        raise AssertionError(name)
    return match.group(0)


class DateTimeDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node unavailable")
        cls.source = Path(__file__).with_name("serve_app.js").read_text(encoding="utf-8")

    def run_js(self, expression, *, date_format="iso", time_format="24h",
               timezone="Etc/GMT+7", browser_zone="Asia/Tokyo", functions=()):
        settings = dict(timezone=timezone, date_format=date_format, time_format=time_format)
        code = formatting_source(self.source, settings)
        code += "\n" + "\n".join(function_source(self.source, name) for name in functions)
        code += "\nconsole.log(JSON.stringify(" + expression + "));"
        result = subprocess.run([self.node, "-"], input=code, text=True, encoding="utf-8",
                                capture_output=True, check=True, timeout=10,
                                env={**os.environ, "TZ": browser_zone})
        return json.loads(result.stdout)

    def test_fixed_pacific_is_minus_seven_in_winter_and_summer(self):
        self.assertEqual(self.run_js("""[
          dateHeure("2026-01-15T19:18:20Z"),
          dateHeure("2026-07-15T19:18:20Z"),
          dateHeure("2026-11-01T19:18:20Z")
        ]"""), ["2026-01-15 12:18:20", "2026-07-15 12:18:20", "2026-11-01 12:18:20"])

    def test_fixed_pacific_day_boundary_and_midnight(self):
        self.assertEqual(self.run_js("""[
          dateHeure("2026-10-10T06:59:59Z"),
          dateHeure("2026-10-10T07:00:00Z"),
          dateLocale("2026-10-09")
        ]"""), ["2026-10-09 23:59:59", "2026-10-10 00:00:00", "2026-10-09"])

    def test_display_does_not_depend_on_browser_timezone(self):
        results = [self.run_js('dateHeure("2026-10-09T19:18:20Z")',
                               browser_zone=zone, date_format="mdy", time_format="12h")
                   for zone in ("UTC", "Asia/Tokyo", "America/New_York")]
        self.assertEqual(results, ["10/09/2026 12:18:20 PM"] * 3)

    def test_all_date_orders_and_clock_formats(self):
        for order, date in (("iso", "2026-10-09"), ("mdy", "10/09/2026"), ("dmy", "09/10/2026")):
            for clock, time in (("24h", "15:04:05"), ("12h", "3:04:05 PM")):
                with self.subTest(order=order, clock=clock):
                    self.assertEqual(self.run_js('dateHeure("2026-10-09T22:04:05Z")',
                                                date_format=order, time_format=clock),
                                     f"{date} {time}")

    def test_twelve_hour_midnight_and_noon(self):
        self.assertEqual(self.run_js("""[
          heureLocale("00:01:02"), heureLocale("12:01:02"),
          heureLocale("23:59:59"), heureInstant("2026-10-09T19:18:20Z", false)
        ]""", time_format="12h"), ["12:01:02 AM", "12:01:02 PM", "11:59:59 PM", "12:18 PM"])

    def test_filter_wall_time_is_not_shifted_by_browser_timezone(self):
        self.assertEqual(self.run_js('dateHeureLocale("2026-10-09T12:18")',
                                     date_format="dmy", time_format="12h"),
                         "09/10/2026 12:18 PM")

    def test_invalid_or_missing_instants_do_not_show_epoch_or_invalid_date(self):
        self.assertEqual(self.run_js('[dateHeure(null), dateHeure("invalid"), heureInstant("")]'),
                         ["", "", ""])

    def test_normal_iana_timezone_still_uses_dst(self):
        self.assertEqual(self.run_js("""[
          dateHeure("2026-01-15T19:18:20Z"), dateHeure("2026-07-15T19:18:20Z")
        ]""", timezone="America/Los_Angeles"), ["2026-01-15 11:18:20", "2026-07-15 12:18:20"])

    def test_event_clip_and_snapshot_have_identical_display(self):
        settings = {"timezone": "Etc/GMT+7", "date_format": "mdy", "time_format": "12h"}
        code = formatting_source(self.source, settings)
        code += "\n" + "\n".join(function_source(self.source, n)
                                 for n in ("card", "dateSnapshot", "renderEvents"))
        code += r"""
const h=String, t=String, duration=String, avecJeton=String;
const elements={view:{value:"events"},count:{},list:{innerHTML:"",querySelectorAll:()=>[]}};
const $=id=>elements[id] || null;
let generationEvenements=0;
const data={suppressionAuto:[]};
const evt={id:"one",camera:"Door",type:"motion",timestamp:"2026-10-09T19:18:20Z"};
const fetch=async()=>({events:[evt]});
const lireJSON=async r=>r;
(async()=>{
  await renderEvents();
  console.log(JSON.stringify({
    event:elements.list.innerHTML,
    clip:card({camera:"Door",kind:"direct",identity:"video.mp4",day:"2026-10-09",
               time:"12:18:20",created_at:evt.timestamp}),
    snapshot:dateSnapshot("2026-10-09_19-18-20Z_Door.jpg"),
    fallback:card({camera:"Door",kind:"clip",identity:"old.mp4",
                   day:"2026-10-09",time:"12:18:20"})
  }));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run([self.node, "-"], input=code, text=True, encoding="utf-8",
                                capture_output=True, check=True, timeout=10,
                                env={**os.environ, "TZ": "Asia/Tokyo"})
        for name, rendered in json.loads(result.stdout).items():
            with self.subTest(view=name):
                self.assertIn("10/09/2026 12:18:20 PM", rendered)


if __name__ == "__main__":
    unittest.main()
