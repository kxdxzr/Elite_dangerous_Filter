import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import journal_location as journal


def event(name='Location', system='Sol', **values):
    return json.dumps(dict(event=name, StarSystem=system, timestamp='2026-11-06T12:00:00Z', **values)).encode() + b'\n'


class JournalLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def write(self, name, data, stamp=10):
        path = self.folder / name
        path.write_bytes(data)
        os.utime(path, ns=(stamp * 1_000_000_000, stamp * 1_000_000_000))
        return path

    def test_confirmed_events_ignore_jump_destination(self):
        for name in journal.LOCATION_EVENTS:
            with self.subTest(event=name):
                self.write('Journal.session.01.log', event(name, 'Colonia') + event('StartJump', 'Sagittarius A*'))
                found = journal.read_current_system(self.folder)
                self.assertEqual(found.system, 'Colonia')
                self.assertEqual(found.timestamp, '2026-11-06T12:00:00Z')

    def test_latest_session_without_position_never_uses_old_session(self):
        self.write('Journal.old.01.log', event(), 1)
        self.write('Journal.new.01.log', event('Fileheader'), 2)
        with self.assertRaisesRegex(ValueError, '最新游戏会话'):
            journal.read_current_system(self.folder)

    def test_same_session_numbered_parts(self):
        self.write('Journal.session.01.log', event('FSDJump', 'Achenar'), 1)
        self.write('Journal.session.02.log', event('Music'), 3)
        self.write('Journal.other.01.log', event('Location', 'Wrong'), 2)
        self.assertEqual(journal.read_current_system(self.folder).system, 'Achenar')

    def test_latest_invalid_position_does_not_fall_back(self):
        for invalid in (None, '', 'Bad\nName', 'Bad\x7fName', 'x' * 257):
            self.write('Journal.session.01.log', event() + event('FSDJump', invalid))
            with self.assertRaises(ValueError):
                journal.read_current_system(self.folder)

    def test_missing_or_naive_time_invalid(self):
        for stamp in (None, '2026-11-06', 'bad'):
            line = json.dumps(dict(event='Location', StarSystem='Sol', timestamp=stamp)).encode()
            with self.assertRaises(ValueError):
                journal.parse_location(line, 'file')

    def test_bom_crlf_and_bad_json(self):
        self.write('Journal.session.01.log', b'\xef\xbb\xbf' + event(system='星系 Test').replace(b'\n', b'\r\n') + b'bad JSON\n')
        self.assertEqual(journal.read_current_system(self.folder).system, '星系 Test')

    def test_unterminated_tail_waits_even_if_json_complete(self):
        self.write('Journal.session.01.log', event(system='Old') + event('FSDJump', 'New').rstrip(b'\n'))
        self.assertEqual(journal.read_current_system(self.folder).system, 'Old')
        self.write('Journal.session.01.log', event(system='Only').rstrip(b'\n'))
        with self.assertRaises(ValueError):
            journal.read_current_system(self.folder)

    def test_chunk_boundary_and_trailing_partial(self):
        with patch.object(journal, 'CHUNK_BYTES', 7):
            self.write('Journal.session.01.log', event(system='Old') + event('FSDJump', 'New') + b'{"event":"Location"')
            self.assertEqual(journal.read_current_system(self.folder).system, 'New')

    def test_scan_and_line_budgets(self):
        self.write('Journal.session.01.log', event() + b' ' * 100 + b'\n')
        with patch.object(journal, 'MAX_SCAN_BYTES', 20):
            with self.assertRaisesRegex(ValueError, '近期日志过大'):
                journal.read_current_system(self.folder)
        with patch.object(journal, 'MAX_LINE_BYTES', 20):
            with self.assertRaisesRegex(ValueError, '日志行过长'):
                journal.read_current_system(self.folder)

    def test_missing_empty_nonjournal_and_file_limit(self):
        with self.assertRaises(ValueError):
            journal.read_current_system(self.folder / 'missing')
        self.write('not-a-journal.log', event())
        with self.assertRaises(ValueError):
            journal.read_current_system(self.folder)
        self.write('Journal.one.01.log', event())
        self.write('Journal.two.01.log', event())
        with patch.object(journal, 'MAX_FILES', 1):
            with self.assertRaisesRegex(ValueError, '日志文件过多'):
                journal.read_current_system(self.folder)
