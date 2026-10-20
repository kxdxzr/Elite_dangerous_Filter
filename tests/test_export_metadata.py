import csv
from datetime import datetime, timezone
import io
import re
import unittest
from unittest.mock import patch

import export_metadata as metadata


def assert_english_csv(test, rows):
    text = '\n'.join(','.join(row) for row in rows)
    test.assertIsNone(re.search(r'[\u3400-\u9fff]', text), text)


def assert_provenance(test, rows, width):
    test.assertEqual(rows[5], [])
    preamble = rows[:5]
    test.assertTrue(all(len(row) == width and row[0].startswith('# ') for row in preamble))
    test.assertEqual([preamble[i][1] for i in (0, 1, 2, 4)],
                     [metadata.PROJECT_AUTHOR, metadata.PROJECT_NAME, metadata.PROJECT_VERSION, metadata.PROJECT_URL])
    test.assertIsNotNone(datetime.fromisoformat(preamble[3][1]).utcoffset())
    return rows[6:]


class ExportMetadataTests(unittest.TestCase):
    def test_search_conditions_are_last_preamble_row_before_separator(self):
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        metadata.write_csv_provenance(writer, 5, 'en', search_conditions='Reference: Sol; Radius: 500')
        writer.writerow(['result'] * 5)
        rows = list(csv.reader(io.StringIO(output.getvalue())))
        self.assertEqual(rows[5], ['# Search conditions', 'Reference: Sol; Radius: 500', '', '', ''])
        self.assertEqual(rows[6], [])
        self.assertEqual(rows[7], ['result'] * 5)

    def test_provenance_language_is_english_or_chinese_not_bilingual(self):
        for language in ('en', 'zh'):
            with self.subTest(language=language):
                output = io.StringIO(newline='')
                metadata.write_csv_provenance(csv.writer(output), 5, language)
                rows = list(csv.reader(io.StringIO(output.getvalue())))
                assert_provenance(self, rows, 5)
                if language == 'en':
                    assert_english_csv(self, rows)
                    self.assertEqual(rows[0][0], '# GitHub project author')
                else:
                    self.assertEqual(rows[0][0], '# 源于 GitHub 项目作者')

    def test_provenance_precedes_header_and_does_not_change_result_rows(self):
        for width in (2, 5, 19):
            with self.subTest(width=width):
                output = io.StringIO(newline='')
                writer = csv.writer(output)
                metadata.write_csv_provenance(writer, width)
                writer.writerow(['header'] * width)
                writer.writerow(['data'] * width)
                rows = list(csv.reader(io.StringIO(output.getvalue())))
                self.assertEqual(rows[6:], [['header'] * width, ['data'] * width])
                assert_provenance(self, rows, width)

    def test_export_time_is_generated_on_each_call(self):
        for stamp in (datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc),
                      datetime(2026, 10, 18, 13, 0, tzinfo=timezone.utc)):
            output = io.StringIO(newline='')
            with patch.object(metadata, 'datetime') as clock:
                clock.now.return_value = stamp
                metadata.write_csv_provenance(csv.writer(output), 2)
            rows = list(csv.reader(io.StringIO(output.getvalue())))
            self.assertEqual(datetime.fromisoformat(rows[3][1]), stamp)
