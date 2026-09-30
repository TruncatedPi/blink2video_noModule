"""Reporting failure must not change acquisition results or exception precedence."""
import asyncio
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import blink_engine

class BrokenOutput:
    def __init__(self, operation):
        self.operation = operation
    def write(self, text):
        if self.operation == 'write':
            raise OSError('synthetic private output failure')
        return len(text)
    def flush(self):
        if self.operation == 'flush':
            raise OSError('synthetic private output failure')

class ReportingBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_helper_handles_ordinary_reporting_failures(self):
        for operation in ('write', 'flush'):
            with self.subTest(operation=operation), contextlib.redirect_stdout(BrokenOutput(operation)):
                blink_engine._signaler_echec_acquisition('transfer', OSError('private'))
        with mock.patch.object(blink_engine, 'msg', side_effect=RuntimeError('private')):
            blink_engine._signaler_echec_acquisition('transfer')
        class BadStatus(Exception):
            @property
            def status(self):
                raise ValueError('private')
        blink_engine._signaler_echec_acquisition('transfer', BadStatus())

    def test_helper_does_not_swallow_exit_or_cancellation(self):
        for error in (KeyboardInterrupt(), SystemExit(7), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__), mock.patch('builtins.print', side_effect=error):
                with self.assertRaises(type(error)) as caught:
                    blink_engine._signaler_echec_acquisition('transfer')
                self.assertIs(caught.exception, error)

    async def test_broken_output_preserves_false_results_and_call_order(self):
        for operation in ('write', 'flush'):
            for stage in ('preparation', 'transfer', 'validation'):
                with self.subTest(operation=operation, stage=stage), tempfile.TemporaryDirectory() as folder:
                    events = []
                    target = Path(folder)/'synthetic.mp4'
                    original_unlink = Path.unlink
                    def unlink(path, *args, **kwargs):
                        events.append('unlink')
                        return original_unlink(path, *args, **kwargs)
                    async def prepare(_blink):
                        events.append('prepare')
                        return stage != 'preparation'
                    async def transfer(_blink, path):
                        events.append('transfer')
                        if stage == 'validation':
                            Path(path).write_bytes(b'synthetic')
                        return stage == 'validation'
                    def validate(_path):
                        events.append('validate')
                        return False
                    clip = SimpleNamespace(prepare_download=mock.AsyncMock(side_effect=prepare),
                                           download_video=mock.AsyncMock(side_effect=transfer))
                    with mock.patch.object(Path, 'unlink', new=unlink), mock.patch.object(blink_engine.md, 'valid_mp4_complet', side_effect=validate), contextlib.redirect_stdout(BrokenOutput(operation)):
                        self.assertEqual(await blink_engine.download_clip(object(), clip, target, False), 'failed')
                    expected = ['unlink', 'prepare']
                    if stage != 'preparation': expected.append('transfer')
                    if stage == 'validation': expected.append('validate')
                    self.assertEqual(events, expected+['unlink'])
                    self.assertEqual(clip.prepare_download.await_count, 1)
                    self.assertEqual(clip.download_video.await_count, int(stage != 'preparation'))
                    self.assertFalse(target.with_suffix('.mp4.part').exists())

    async def test_broken_output_preserves_primary_and_cleanup_exceptions(self):
        for operation in ('write', 'flush'):
            for cleanup_fails in (False, True):
                with self.subTest(operation=operation, cleanup_fails=cleanup_fails), tempfile.TemporaryDirectory() as folder:
                    events = []
                    primary = RuntimeError('https://synthetic.invalid/private-token')
                    cleanup = PermissionError('https://synthetic.invalid/private-token')
                    original_unlink = Path.unlink
                    def unlink(path, *args, **kwargs):
                        events.append('unlink')
                        if len(events) == 3 and cleanup_fails:
                            raise cleanup
                        return original_unlink(path, *args, **kwargs)
                    async def prepare(_blink):
                        events.append('prepare')
                        raise primary
                    clip = SimpleNamespace(prepare_download=mock.AsyncMock(side_effect=prepare), download_video=mock.AsyncMock())
                    with mock.patch.object(Path, 'unlink', new=unlink), contextlib.redirect_stdout(BrokenOutput(operation)):
                        with self.assertRaises(PermissionError if cleanup_fails else RuntimeError) as caught:
                            await blink_engine.download_clip(object(), clip, Path(folder)/'synthetic.mp4', False)
                    self.assertIs(caught.exception, cleanup if cleanup_fails else primary)
                    if cleanup_fails: self.assertIs(cleanup.__context__, primary)
                    self.assertEqual(events, ['unlink', 'prepare', 'unlink'])
                    self.assertEqual(clip.prepare_download.await_count, 1)
                    self.assertEqual(clip.download_video.await_count, 0)

    async def test_initial_probe_errors_report_without_setup_or_provider_calls(self):
        for operation in ('exists', 'validation'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as folder:
                target = Path(folder)/'private-name.mp4'
                target.write_bytes(b'synthetic')
                error = PermissionError('https://synthetic.invalid/private-token private-name.mp4')
                clip = SimpleNamespace(prepare_download=mock.AsyncMock(), download_video=mock.AsyncMock())
                text = io.StringIO()
                with mock.patch.object(Path, 'exists', side_effect=error if operation == 'exists' else None, return_value=True), mock.patch.object(blink_engine.md, 'valid_mp4_complet', side_effect=error if operation == 'validation' else None), mock.patch.object(Path, 'mkdir') as mkdir, mock.patch.object(Path, 'unlink') as unlink, contextlib.redirect_stdout(text):
                    with self.assertRaises(PermissionError) as caught:
                        await blink_engine.download_clip(object(), clip, target, False)
                self.assertIs(caught.exception, error)
                self.assertIn('='+('local' if operation == 'exists' else 'validation'), text.getvalue())
                self.assertIn('unknown', text.getvalue())
                for value in ('https:', 'private-token', 'private-name'):
                    self.assertNotIn(value, text.getvalue())
                mkdir.assert_not_called(); unlink.assert_not_called()
                clip.prepare_download.assert_not_awaited(); clip.download_video.assert_not_awaited()

    async def test_existing_target_probe_order_and_quiet_skip(self):
        with tempfile.TemporaryDirectory() as folder:
            events = []
            class Overwrite:
                def __bool__(self):
                    events.append('overwrite')
                    return False
            def exists(_path):
                events.append('exists'); return True
            def validate(_path):
                events.append('validation'); return True
            clip = SimpleNamespace(prepare_download=mock.AsyncMock(), download_video=mock.AsyncMock())
            text = io.StringIO()
            with mock.patch.object(Path, 'exists', new=exists), mock.patch.object(blink_engine.md, 'valid_mp4_complet', side_effect=validate), mock.patch.object(Path, 'mkdir') as mkdir, mock.patch.object(Path, 'unlink') as unlink, contextlib.redirect_stdout(text):
                result = await blink_engine.download_clip(object(), clip, Path(folder)/'synthetic.mp4', Overwrite())
            self.assertEqual(result, 'skipped'); self.assertEqual(events, ['exists', 'validation', 'overwrite']); self.assertEqual(text.getvalue(), '')
            mkdir.assert_not_called(); unlink.assert_not_called()
            clip.prepare_download.assert_not_awaited(); clip.download_video.assert_not_awaited()

    async def test_acquisition_exit_and_cancellation_propagate_after_cleanup(self):
        for error in (KeyboardInterrupt(), SystemExit(7), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as folder:
                clip = SimpleNamespace(prepare_download=mock.AsyncMock(side_effect=error), download_video=mock.AsyncMock())
                original_unlink = Path.unlink
                calls = []
                def unlink(path, *args, **kwargs):
                    calls.append(path)
                    return original_unlink(path, *args, **kwargs)
                text = io.StringIO()
                with mock.patch.object(Path, 'unlink', new=unlink), contextlib.redirect_stdout(text):
                    with self.assertRaises(type(error)) as caught:
                        await blink_engine.download_clip(object(), clip, Path(folder)/'synthetic.mp4', False)
                self.assertIs(caught.exception, error)
                self.assertEqual(len(calls), 2)
                clip.prepare_download.assert_awaited_once(); clip.download_video.assert_not_awaited()
                self.assertEqual(text.getvalue(), '')
