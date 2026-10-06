"""Vrais boutons HTTP stop/restart, serveur direct et état isolé sans Blink."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import runtime


class TestsCycleVieServeur(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="blink-serve-cycle-")
        self.home = Path(self.temp.name)
        self.process = None
        self.pids = set()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.version = self.home / "test-version.txt"
        self.version.write_text("test-old-dev", encoding="utf-8")
        (self.home / runtime.REGLAGES).write_text(json.dumps({
            "port": self.port, "timezone": "UTC", "doorbell_alerts_enabled": False,
        }), encoding="utf-8")
        self.runner = self.home / "serve-isole.py"
        # Le vrai superviseur restart/finaliseur et le vrai serveur sont exercés.
        # Remplacer seulement start évite le preflight de compte et les boucles
        # de téléchargement, sans modifier l'arrêt natif ni le relais HTTP.
        self.runner.write_text(f'''
import pathlib, sys
sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
import runtime
runtime.VERSION = pathlib.Path({str(self.version)!r}).read_text(encoding="utf-8")
runtime.git_commit_info = lambda: ""
original_command = runtime.self_command
def command(verb, *args):
    if verb in ("restart", "start"):
        return [sys.executable, "-u", {str(self.runner)!r}, verb, *args]
    return original_command(verb, *args)
runtime.self_command = command
if len(sys.argv) > 1 and sys.argv[1] == "restart":
    import blink_cli
    raise SystemExit(blink_cli.redemarrer(sys.argv[2:]))
sys.argv = ["serve.py", "--port", {str(self.port)!r}]
import serve
serve.veiller_sur_les_versions = lambda: None
serve.demarrer_moniteur_evenements = lambda: None
raise SystemExit(serve.main())
''', encoding="utf-8")
        self.env = dict(os.environ, BLINK_HOME=str(self.home),
                        BLINK_CONTROL_HOME=str(self.home), BLINK_BOOTSTRAP="none",
                        PYTHONDONTWRITEBYTECODE="1", BLINK_BIND="127.0.0.1")
        self.env.pop(runtime.INSTANCE_PID_ENV, None)
        self.log = (self.home / "server.log").open("wb")

    def tearDown(self):
        # Arrêt coopératif même si une assertion échoue après le restart.
        (self.home / runtime.ARRET_DEMANDE).write_text("test cleanup")
        limit = time.monotonic() + 8
        while time.monotonic() < limit and any(runtime.processus_vivant(p) for p in self.pids):
            time.sleep(0.1)
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait(timeout=5)
        self.log.close()
        self.temp.cleanup()

    def request(self, path="/", token=None, post=False):
        headers = {"X-Blink-Token": token} if token else {}
        if post:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.url + path, data=b"{}" if post else None,
                                         headers=headers)
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.read().decode("utf-8")

    def wait_page(self, expected_version):
        limit = time.monotonic() + 15
        while time.monotonic() < limit:
            try:
                page = self.request()
                if expected_version in page:
                    self.token = re.search(r'const BLINK_TOKEN = "([a-f0-9]+)";', page).group(1)
                    self.pid = int(re.search(r'const BLINK_PID = "(\d+)";', page).group(1))
                    self.pids.add(self.pid)
                    return page
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.1)
        self.fail((self.home / "server.log").read_text(encoding="utf-8", errors="replace"))

    def start(self):
        self.process = subprocess.Popen([sys.executable, "-u", str(self.runner)],
                                        env=self.env, stdin=subprocess.DEVNULL,
                                        stdout=self.log, stderr=subprocess.STDOUT)
        self.wait_page("test-old-dev")

    def test_stop_http_termine_serve_direct_et_libere_port(self):
        self.start()
        status = json.loads(self.request("/api/status", self.token))
        self.assertEqual(status["pid"], self.pid)
        self.assertEqual(status["version"], "test-old-dev")
        self.assertTrue(list((self.home / runtime.INSTANCES).glob("*.json")))
        result = json.loads(self.request("/api/stop", self.token, post=True))
        self.assertTrue(result["accepted"])
        self.process.wait(timeout=12)
        self.assertEqual(self.process.returncode, 0)
        with self.assertRaises((OSError, urllib.error.URLError)):
            self.request()
        self.assertEqual(list((self.home / runtime.INSTANCES).glob("*.json")), [])

    def test_restart_http_change_pid_et_charge_nouvelle_version(self):
        self.start()
        old_pid, old_token = self.pid, self.token
        self.version.write_text("test-new-dev", encoding="utf-8")
        result = json.loads(self.request("/api/redemarrer", old_token, post=True))
        self.assertTrue(result["accepted"])
        self.wait_page("test-new-dev")
        self.process.wait(timeout=5)
        self.assertEqual(self.process.returncode, 0)
        self.assertNotEqual(self.pid, old_pid)
        self.assertNotEqual(self.token, old_token)
        status = json.loads(self.request("/api/status", self.token))
        self.assertEqual(status["version"], "test-new-dev")
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/status", old_token)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    @unittest.skipUnless(os.name == "nt", "Lanceur Windows")
    def test_stop_cmd_termine_instance_inscrite(self):
        self.start()
        result = subprocess.run([
            "cmd.exe", "/d", "/c", str(Path(__file__).with_name("stop.cmd"))],
            cwd=str(Path(__file__).resolve().parent), env=self.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=20,
            creationflags=runtime.SANS_FENETRE)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.process.wait(timeout=5)
        self.assertEqual(self.process.returncode, 0)
        with self.assertRaises((OSError, urllib.error.URLError)):
            self.request()


if __name__ == "__main__":
    unittest.main()
