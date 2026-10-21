import ast
from pathlib import Path
import unittest

from export_metadata import PROJECT_AUTHOR, PROJECT_NAME, PROJECT_VERSION


PROJECT = Path(__file__).resolve().parents[1]


class ExeVersionTests(unittest.TestCase):
    def test_spec_embeds_version_resource(self):
        self.assertIn('version=str(project / "EliteDangerousFilter.version.txt")',
                      (PROJECT / 'EliteDangerousFilter.spec').read_text(encoding='utf-8'))

    def test_resource_matches_application_metadata(self):
        tree = ast.parse((PROJECT / 'EliteDangerousFilter.version.txt').read_text(encoding='utf-8'))
        fields = {}
        fixed = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == 'StringStruct':
                    fields[ast.literal_eval(node.args[0])] = ast.literal_eval(node.args[1])
                elif node.func.id == 'FixedFileInfo':
                    fixed = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords}
        version = tuple(int(part) for part in PROJECT_VERSION.split('.')) + (0,)
        self.assertEqual(fixed['filevers'], version)
        self.assertEqual(fixed['prodvers'], version)
        self.assertEqual(fixed['flags'], 0)
        self.assertEqual(fields['FileVersion'], '.'.join(map(str, version)))
        self.assertEqual(fields['ProductVersion'], PROJECT_VERSION)
        self.assertEqual(fields['ProductName'], PROJECT_NAME)
        self.assertEqual(fields['CompanyName'], PROJECT_AUTHOR)
        self.assertEqual(fields['OriginalFilename'], 'EliteDangerousFilter.exe')
