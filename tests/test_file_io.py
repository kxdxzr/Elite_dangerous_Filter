from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

import file_io
import session_store


class AtomicWriteTests(unittest.TestCase):
    def test_create_parent_and_replace_without_leftover_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nested' / 'data.json'
            file_io.atomic_write(path, b'old')
            file_io.atomic_write(path, b'new')
            self.assertEqual(path.read_bytes(), b'new')
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_flush_and_replace_failures_preserve_previous_bytes_and_cleanup(self):
        for operation in ('fsync', 'replace'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'data.json'
                path.write_bytes(b'previous')
                with patch.object(file_io.os, operation, side_effect=OSError('disk failure')):
                    with self.assertRaises(OSError):
                        file_io.atomic_write(path, b'replacement')
                self.assertEqual(path.read_bytes(), b'previous')
                self.assertEqual(list(path.parent.iterdir()), [path])

    def test_failed_initial_write_does_not_leave_a_partial_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.json'
            with patch.object(file_io.os, 'replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    file_io.atomic_write(path, b'new')
            self.assertFalse(path.exists())
            self.assertEqual(list(path.parent.iterdir()), [])

    def test_replacement_uses_a_temporary_file_in_the_destination_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.json'
            path.write_bytes(b'old')
            replace = file_io.os.replace

            def checked_replace(source, target):
                self.assertEqual(Path(source).parent, path.parent)
                self.assertEqual(Path(source).read_bytes(), b'new')
                self.assertEqual(path.read_bytes(), b'old')
                replace(source, target)

            with patch.object(file_io.os, 'replace', side_effect=checked_replace):
                file_io.atomic_write(path, b'new')

    def test_serialization_failure_does_not_modify_a_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            session_store.save(path, {'value': 'old'})
            with self.assertRaises(TypeError):
                session_store.save(path, {'value': object()})
            self.assertEqual(session_store.load(path), {'value': 'old'})
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_concurrent_writers_use_distinct_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.json'
            contents = [bytes([index]) * 4096 for index in range(8)]

            def write(content):
                try:
                    file_io.atomic_write(path, content)
                    return True
                except PermissionError:
                    # Windows can reject simultaneous replacements with a sharing
                    # violation. Atomicity does not promise writer serialization;
                    # the utility propagates this error and still cleans up.
                    if sys.platform != 'win32':
                        raise
                    return False

            with ThreadPoolExecutor(max_workers=4) as executor:
                successes = list(executor.map(write, contents))
            self.assertTrue(any(successes))
            self.assertIn(path.read_bytes(), contents)
            self.assertEqual(list(path.parent.iterdir()), [path])
