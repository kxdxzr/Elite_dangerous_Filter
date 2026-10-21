import ast
from collections import Counter
from pathlib import Path
from string import Formatter
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import i18n
from translations import en, zh


class LanguageRegistryTests(unittest.TestCase):
    def test_only_existing_languages_are_enabled(self):
        self.assertEqual(i18n.LANGUAGES, {'zh': '中文', 'en': 'English'})
        self.assertEqual(i18n.normalize_language('not-installed'), 'zh')
        self.assertEqual(i18n.language_code('English'), 'en')
        self.assertEqual(i18n.missing_translations('en'), [])

    def test_registered_pack_works_without_changes_to_localizer_or_exporters(self):
        pack = ModuleType('translations.zz')
        pack.CATALOG = {'名称': 'ZZ name', '项目名': 'ZZ project'}
        pack.MESSAGES = {'csv.distance': 'ZZ {reference} (ly)'}
        with patch.dict(i18n.LANGUAGES, {'zz': 'Test language'}), \
                patch.dict(sys.modules, {'translations.zz': pack}):
            localizer = i18n.Localizer(SimpleNamespace(), 'zz')
            self.assertEqual(localizer.language, 'zz')
            self.assertEqual(localizer.tr('名称'), 'ZZ name')
            self.assertEqual(localizer.tr('关闭'), 'Close')
            self.assertEqual(localizer.tr('Sol'), 'Sol')
            self.assertEqual(localizer.message('csv.distance', reference='Sol'), 'ZZ Sol (ly)')
            self.assertEqual(localizer.message('csv.indexed', title='Item', index=2), 'Item (2)')
            self.assertIn('关闭', i18n.missing_translations('zz'))
            self.assertIn('@csv.indexed', i18n.missing_translations('zz'))
            from main_csv import export_table
            headers, _ = export_table([], 'systems', [], 'zz', localizer.tr)
            self.assertEqual(headers, ['ZZ name'])
            import csv
            import io
            from export_metadata import write_csv_provenance
            output = io.StringIO(newline='')
            write_csv_provenance(csv.writer(output), 2, 'zz')
            rows = list(csv.reader(io.StringIO(output.getvalue())))
            self.assertEqual(rows[1][0], '# ZZ project')
            self.assertEqual(rows[0][0], '# GitHub project author')
            localizer.set_language('en')
            self.assertEqual(localizer.tr('名称'), 'Name')

    def test_templates_preserve_placeholder_names_and_format_specifications(self):
        def placeholders(text):
            return {(name, spec, conversion) for _, name, spec, conversion in Formatter().parse(text)
                    if name is not None}
        for key, source in zh.MESSAGES.items():
            with self.subTest(key=key):
                # Field labels intentionally choose one of two supplied representations.
                if key != 'csv.field':
                    self.assertEqual(placeholders(source), placeholders(en.MESSAGES[key]))
        self.assertEqual(i18n.message('progress.unknown', 'en', stage='Checking', done=1200),
                         'Checking: 1,200; total unknown')
        with self.assertRaises(KeyError):
            i18n.message('no-such-message', 'en')

    def test_packs_have_no_duplicate_translation_keys(self):
        folder = Path(__file__).resolve().parents[1] / 'src/translations'
        for path in folder.glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf8'))):
                if isinstance(node, ast.Dict):
                    keys = [key.value for key in node.keys if isinstance(key, ast.Constant)]
                    self.assertFalse([key for key, count in Counter(keys).items() if count > 1], path.name)

    def test_presentation_modules_do_not_branch_on_individual_language_codes(self):
        folder = Path(__file__).resolve().parents[1] / 'src'
        for path in folder.glob('*.py'):
            if path.name == 'i18n.py' or path.name.endswith('_test.py'):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding='utf8'))):
                if isinstance(node, ast.Compare):
                    literals = [child.value for child in ast.walk(node)
                                if isinstance(child, ast.Constant) and isinstance(child.value, str)]
                    self.assertFalse({'zh', 'en'} & set(literals), (path.name, node.lineno))

    def test_spec_collects_registered_language_pack_modules(self):
        spec = (Path(__file__).resolve().parents[1] / 'EliteDangerousFilter.spec').read_text(encoding='utf8')
        self.assertIn('"translations." + path.stem', spec)
