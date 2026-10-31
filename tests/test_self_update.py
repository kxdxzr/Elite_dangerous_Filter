import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import self_update as update
import release_updates as releases


ROOT = Path(__file__).resolve().parents[1]


class SelfUpdateTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'dist').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='self-update-test-', dir=ROOT / 'dist')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.target = self.folder / '程序 with spaces.exe'
        self.target.write_bytes(b'old-executable')
        self.payload = b'MZverified-new-executable'
        self.release = releases.Release('v99.0.0', releases.PROJECT_URL + '/releases/tag/v99.0.0',
                                        releases.PROJECT_URL + '/releases/download/v99.0.0/EliteDangerousFilter.exe',
                                        hashlib.sha256(self.payload).hexdigest(), len(self.payload))

    def response(self, payload=None):
        return io.BytesIO(self.payload if payload is None else payload)

    def test_validated_download_stays_separate_and_helper_needs_explicit_commit(self):
        process = Mock()
        process.poll.return_value = None
        def launch(*args, **kwargs):
            # Simulate helper acknowledging startup, not authorization to replace.
            config = json.loads(Path(args[0][-1]).read_text())
            Path(config['ready']).write_text('ready')
            return process
        with patch.dict(update.os.environ, SystemRoot=str(self.folder / 'mock-windows')), \
                patch.object(update, 'urlopen', return_value=self.response()), \
                patch.object(update.subprocess, 'Popen', side_effect=launch):
            prepared = update.prepare_update(self.release, self.target)
        self.assertEqual(self.target.read_bytes(), b'old-executable')
        self.assertEqual((prepared.folder / 'new.exe').read_bytes(), self.payload)
        self.assertFalse((prepared.folder / 'go').exists())
        prepared.commit()
        self.assertTrue((prepared.folder / 'go').exists())
        prepared.cancel()
        process.terminate.assert_called_once()

    def test_bad_metadata_is_rejected_before_network(self):
        from dataclasses import replace
        changes = [dict(sha256=None), dict(sha256='x' * 64), dict(size=0), dict(size=update.MAX_EXE + 1),
                   dict(version='v0.0.1'), dict(download_url='https://evil.example/new.exe')]
        for change in changes:
            with self.subTest(change=change), patch.object(update, 'urlopen') as http, self.assertRaises(ValueError):
                update.prepare_update(replace(self.release, **change), self.target)
            http.assert_not_called()

    def test_truncated_extra_corrupt_and_non_exe_payload_never_launch_helper(self):
        from dataclasses import replace
        for payload in (self.payload[:-1], self.payload + b'extra', b'xx' + self.payload[2:]):
            with self.subTest(payload=payload), patch.object(update, 'urlopen', return_value=self.response(payload)), patch.object(update.subprocess, 'Popen') as launch, self.assertRaises(ValueError):
                update.prepare_update(self.release, self.target)
            launch.assert_not_called()
            self.assertEqual(self.target.read_bytes(), b'old-executable')
        bad = b'not an executable'
        release = replace(self.release, sha256=hashlib.sha256(bad).hexdigest(), size=len(bad))
        with patch.object(update, 'urlopen', return_value=self.response(bad)), self.assertRaises(ValueError):
            update.prepare_update(release, self.target)

    def test_permission_or_network_failure_never_changes_old_exe(self):
        for target, error in (('tempfile.mkdtemp', PermissionError()), ('urlopen', TimeoutError())):
            with patch('self_update.' + target, side_effect=error), self.assertRaises(type(error)):
                update.prepare_update(self.release, self.target)
            self.assertEqual(self.target.read_bytes(), b'old-executable')

    def test_exited_helper_cannot_be_committed(self):
        process = Mock()
        process.poll.return_value = 1
        with self.assertRaises(OSError):
            update.PreparedUpdate(self.folder, process).commit()
        self.assertFalse((self.folder / 'go').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows helper integration')
    def test_real_windows_helper_waits_replaces_backs_up_and_rolls_back_launch_failure(self):
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        old = (Path(os.environ['SystemRoot']) / 'System32/hostname.exe').read_bytes()
        new = (Path(os.environ['SystemRoot']) / 'System32/whoami.exe').read_bytes()
        for mode in ('success', 'rollback', 'hash-changed'):
            fail = mode == 'rollback'
            with self.subTest(mode=mode):
                folder = self.folder / mode
                folder.mkdir()
                target, staged = folder / '程序.exe', folder / 'new.exe'
                target.write_bytes(old)
                payload = b'MZinvalid-executable' if fail else new
                staged.write_bytes(payload)
                parent_exit = folder / 'parent-exit'
                parent_program = (
                    'import sys, time\n'
                    'from pathlib import Path\n'
                    'gate = Path(sys.argv[1])\n'
                    'deadline = time.monotonic() + 45\n'
                    'while not gate.exists() and time.monotonic() < deadline:\n'
                    '    time.sleep(.02)\n'
                )
                parent = subprocess.Popen([sys.executable, '-c', parent_program, str(parent_exit)])
                config = dict(pid=parent.pid, notify=False, target=str(target), staged=str(staged),
                              sha256=hashlib.sha256(payload).hexdigest(), backup=str(folder / 'old.exe'),
                              failed=str(folder / 'failed.exe'), ready=str(folder / 'ready'),
                              go=str(folder / 'go'), log=str(folder / 'update.log'))
                script, conf = folder / 'helper.ps1', folder / 'config.json'
                script.write_text(update.HELPER, encoding='utf-8-sig')
                conf.write_text(json.dumps(config), encoding='utf-8')
                process = subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                            '-File', str(script), '-Config', str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 15
                    while not Path(config['ready']).exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(.05)
                    self.assertTrue(Path(config['ready']).exists())
                    self.assertEqual(target.read_bytes(), old)  # no go, no replacement
                    if mode == 'hash-changed':
                        staged.write_bytes(b'tampered')
                    Path(config['go']).write_bytes(b'go')
                    time.sleep(.1)
                    self.assertIsNone(parent.poll(), 'Parent must stay alive until explicitly released')
                    self.assertEqual(target.read_bytes(), old)  # parent still running
                    parent_exit.write_bytes(b'exit')
                    parent.wait(timeout=10)
                    _, stderr = process.communicate(timeout=30)
                    log = Path(config['log'])
                    diagnostics = (log.read_text(encoding='utf-8', errors='replace') if log.exists()
                                   else 'Helper produced no log') + '\n' + repr(stderr)
                    self.assertEqual(process.returncode, 0 if mode == 'success' else 1, diagnostics)
                    self.assertEqual(target.read_bytes(), new if mode == 'success' else old)
                    if mode == 'success':
                        self.assertEqual(Path(config['backup']).read_bytes(), old)
                    elif fail:
                        self.assertTrue(Path(config['failed']).exists(), diagnostics)
                        self.assertEqual(Path(config['failed']).read_bytes(), payload)
                    self.assertTrue(Path(config['log']).exists())
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    if parent.poll() is None:
                        parent.terminate()
                    parent.wait(timeout=10)
