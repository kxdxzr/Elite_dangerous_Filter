import hashlib
import json
from pathlib import Path
import re
import struct
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class DocumentationImageTests(unittest.TestCase):
    def test_every_readme_image_exists_and_is_in_the_current_manifest(self):
        manifest = json.loads((PROJECT / 'docs/images/screenshots.json').read_text(encoding='utf-8'))
        entries = {entry['file']: entry for entry in manifest['screenshots']}
        referenced = set()
        for readme, language in (('README.md', 'en'), ('README_zh-CN.md', 'zh')):
            text = (PROJECT / readme).read_text(encoding='utf-8')
            images = re.findall(r'!\[[^\]]*\]\((docs/images/[^)]+)\)', text)
            self.assertEqual(len(images), 11, readme)
            for path in images:
                name = Path(path).name
                self.assertTrue((PROJECT / path).is_file(), path)
                self.assertIn(name, entries)
                self.assertEqual(entries[name]['language'], language)
                referenced.add(name)
        self.assertEqual(referenced, set(entries))
        self.assertIn('illustrative', manifest['data'])

    def test_images_match_recorded_dimensions_and_checksums(self):
        manifest = json.loads((PROJECT / 'docs/images/screenshots.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['screenshots']), 22)
        for entry in manifest['screenshots']:
            with self.subTest(image=entry['file']):
                raw = (PROJECT / 'docs/images' / entry['file']).read_bytes()
                self.assertEqual(raw[:8], b'\x89PNG\r\n\x1a\n')
                width, height = struct.unpack('>II', raw[16:24])
                self.assertEqual((width, height), (entry['width'], entry['height']))
                self.assertGreater(width, 700)
                self.assertGreater(height, 500)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['sha256'])
