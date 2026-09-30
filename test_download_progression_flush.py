"""Les lignes de progression doivent atteindre le pipe sans attendre la fin."""
import io
import unittest
from unittest import mock
import blink_engine


class TestsProgressionFlush(unittest.TestCase):
    def test_each_progress_event_reaches_a_buffered_pipe(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="utf-8")
        with mock.patch.object(blink_engine.runtime, "travail"), mock.patch("sys.stdout", stream):
            progress = blink_engine._ProgressionTelechargement(2)
            self.assertEqual(raw.getvalue().decode("utf-8"), "  [1/2] 0%\n")
            progress.commencer("synthetic.mp4")
            self.assertTrue(raw.getvalue().decode("utf-8").endswith("  [1/2] synthetic.mp4\n"))
            progress.terminer()
            self.assertTrue(raw.getvalue().decode("utf-8").endswith("  [1/2] 100%\n"))
