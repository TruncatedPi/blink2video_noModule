"""Diagnostics bornés, sans exposer le média ou le texte d'une exception."""
import contextlib
import io
import os
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import blink_engine
import blink_models
from test_download_progression import FauxSync, FauxClip


class TestsDiagnosticAcquisition(unittest.IsolatedAsyncioTestCase):
    async def test_failure_stages_preserve_calls_and_cleanup(self):
        for stage in ('preparation', 'transfer', 'validation'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / 'private-name.mp4'
                async def transfer(_blink, path):
                    if stage == 'validation':
                        Path(path).write_bytes(b'invalid media')
                    return stage == 'validation'
                clip = SimpleNamespace(
                    prepare_download=mock.AsyncMock(return_value=stage != 'preparation'),
                    download_video=mock.AsyncMock(side_effect=transfer))
                text = io.StringIO()
                with mock.patch.object(blink_engine.md, 'valid_mp4_complet', return_value=False), contextlib.redirect_stdout(text):
                    outcome = await blink_engine.download_clip(object(), clip, target, False)
                self.assertEqual(outcome, 'failed')
                self.assertEqual(clip.prepare_download.await_count, 1)
                self.assertEqual(clip.download_video.await_count, 0 if stage == 'preparation' else 1)
                self.assertIn('='+stage, text.getvalue())
                self.assertNotIn('private-name', text.getvalue())
                self.assertFalse(target.exists())
                self.assertFalse(target.with_suffix('.mp4.part').exists())

    async def test_exception_propagates_with_only_safe_status(self):
        class PrivateError(Exception):
            status = 429
        error = PrivateError('https://private.example/token?account=123 private-name.mp4')
        for stage in ('preparation', 'transfer'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                clip = SimpleNamespace(prepare_download=mock.AsyncMock(return_value=True),
                                       download_video=mock.AsyncMock(return_value=True))
                getattr(clip, 'prepare_download' if stage == 'preparation' else 'download_video').side_effect = error
                text = io.StringIO()
                with contextlib.redirect_stdout(text), self.assertRaises(PrivateError) as caught:
                    await blink_engine.download_clip(object(), clip, Path(folder)/'private-name.mp4', False)
                self.assertIs(caught.exception, error)
                self.assertIn('='+stage, text.getvalue())
                self.assertIn('429', text.getvalue())
                for secret in ('https:', 'token', 'account', '123', 'private-name'):
                    self.assertNotIn(secret, text.getvalue())

    async def test_success_and_skip_do_not_emit_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'private-name.mp4'
            async def transfer(_blink, path):
                Path(path).write_bytes(b'synthetic valid media')
                return True
            clip = SimpleNamespace(prepare_download=mock.AsyncMock(return_value=True),
                                   download_video=mock.AsyncMock(side_effect=transfer))
            text = io.StringIO()
            with mock.patch.object(blink_engine.md, 'valid_mp4_complet', return_value=True), contextlib.redirect_stdout(text):
                self.assertEqual(await blink_engine.download_clip(object(), clip, target, False), 'downloaded')
                self.assertEqual(await blink_engine.download_clip(object(), clip, target, False), 'skipped')
            self.assertEqual(clip.prepare_download.await_count, 1)
            self.assertEqual(clip.download_video.await_count, 1)
            self.assertEqual(text.getvalue(), '')

    def test_unknown_status_is_not_printed_verbatim(self):
        for status in ('https://private.example/token', 123456789, None):
            text = io.StringIO()
            with contextlib.redirect_stdout(text):
                blink_engine._signaler_echec_acquisition('transfer', SimpleNamespace(status=status))
            self.assertIn('unknown', text.getvalue())
            self.assertNotIn('private', text.getvalue())
            self.assertNotIn('123456789', text.getvalue())

    def test_final_and_exception_messages_do_not_claim_retries_or_print_errors(self):
        for language in ('fr', 'en'):
            with mock.patch.object(blink_engine.runtime, 'lire_langue', return_value=language):
                final = blink_engine.msg('usb_echec_final')
                exception = blink_engine.msg('usb_echec', type='RuntimeError')
                gabarit = blink_engine.LIBELLES[language]['usb_echec']
            self.assertNotIn('attempt', final)
            self.assertNotIn('tentative', final)
            # Seul le nom de la classe est imprimé, jamais le texte de l'erreur.
            self.assertIn('RuntimeError', exception)
            self.assertNotIn('{', exception)
            self.assertNotIn('{erreur}', gabarit)

    async def test_usb_exception_log_does_not_copy_private_exception_text(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {"BLINK_HOME": folder}):
            clip = FauxClip("synthetic", "Test", dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc), 7, "test")
            args = SimpleNamespace(since=None, camera=None, command="download", output=Path(folder)/"clips",
                                   hub=None, overwrite=False, source="usb", loop=None)
            text = io.StringIO()
            with mock.patch.object(blink_models, "read_local_manifest", new=mock.AsyncMock(return_value=[clip])), \
                 mock.patch.object(blink_engine, "download_clip", new=mock.AsyncMock(side_effect=RuntimeError("https://private.example/token?account=123"))), \
                 mock.patch.object(blink_engine.runtime, "travail"), \
                 mock.patch.object(blink_engine.runtime, "lire_suppression_auto", return_value=set()), \
                 mock.patch.object(blink_engine.runtime, "marquer"), contextlib.redirect_stdout(text):
                code = await blink_engine.un_passage(object(), args, [("Test", FauxSync(10, 7))])
            self.assertEqual(code, 1)
            for secret in ("https:", "private.example", "token", "account=123"):
                self.assertNotIn(secret, text.getvalue())

    async def test_directory_and_initial_unlink_errors_are_local(self):
        for operation in ('mkdir', 'unlink'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as folder:
                target = Path(folder)/'private-name.mp4'
                error = PermissionError('https://private.example/token?account=123')
                clip = SimpleNamespace(prepare_download=mock.AsyncMock(), download_video=mock.AsyncMock())
                text = io.StringIO()
                with mock.patch.object(Path, operation, side_effect=error) as operation_mock, contextlib.redirect_stdout(text):
                    with self.assertRaises(PermissionError) as caught:
                        await blink_engine.download_clip(object(), clip, target, False)
                self.assertIs(caught.exception, error)
                self.assertEqual(operation_mock.call_count, 1)
                self.assertEqual(clip.prepare_download.await_count, 0)
                self.assertEqual(clip.download_video.await_count, 0)
                self.assertEqual(text.getvalue().count('=local'), 1)
                for secret in ('https:', 'token', 'account', '123', 'private-name'):
                    self.assertNotIn(secret, text.getvalue())

    async def test_cleanup_error_retains_error_and_reports_local(self):
        for primary in ('false-transfer', 'exception', 'success'):
            with self.subTest(primary=primary), tempfile.TemporaryDirectory() as folder:
                target = Path(folder)/'private-name.mp4'
                original_unlink = Path.unlink
                cleanup_error = PermissionError('https://private.example/cleanup-token')
                primary_error = RuntimeError('https://private.example/primary-token')
                calls = []
                def unlink(path, *args, **kwargs):
                    calls.append(path)
                    if len(calls) == 2:
                        raise cleanup_error
                    return original_unlink(path, *args, **kwargs)
                async def transfer(_blink, path):
                    if primary == 'exception':
                        raise primary_error
                    if primary == 'success':
                        Path(path).write_bytes(b'synthetic valid media')
                        return True
                    return False
                clip = SimpleNamespace(prepare_download=mock.AsyncMock(return_value=True),
                                       download_video=mock.AsyncMock(side_effect=transfer))
                text = io.StringIO()
                with mock.patch.object(Path, 'unlink', new=unlink), \
                     mock.patch.object(blink_engine.md, 'valid_mp4_complet', return_value=True), \
                     contextlib.redirect_stdout(text), self.assertRaises(PermissionError) as caught:
                    await blink_engine.download_clip(object(), clip, target, False)
                self.assertIs(caught.exception, cleanup_error)
                if primary == 'exception':
                    self.assertIs(cleanup_error.__context__, primary_error)
                self.assertEqual(len(calls), 2)
                self.assertEqual(clip.prepare_download.await_count, 1)
                self.assertEqual(clip.download_video.await_count, 1)
                self.assertEqual(target.exists(), primary == 'success')
                self.assertEqual(text.getvalue().count('=local'), 1)
                self.assertEqual(text.getvalue().count('=transfer'), 0 if primary == 'success' else 1)
                for secret in ('https:', 'token', 'private-name'):
                    self.assertNotIn(secret, text.getvalue())
