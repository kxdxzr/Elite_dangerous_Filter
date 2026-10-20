import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import catalog_updates as updates
import outfitting_catalog as catalog
import full_outfitting as tool


def package(ver='2026.10.20.1'):
    facts = [dict(ed_id=i, ed_symbol=f'int_test_{i}', name=name, category='standard',
                  **{'class': 2, 'rating': 'A'}) for i, name in enumerate(
                      ('New Ordinary Module', 'New Power Module', 'New AX Module'), 1)]
    entries = [dict(item, group=group) for item, group in zip(facts, ('ordinary', 'power', 'ax'))]
    return dict(format=1, engine=1, version=ver, sources=['test-facts@revision'],
                entries=entries, module_facts=facts, ships=['Sidewinder'])


class CatalogUpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.paths = patch.object(updates, 'data_file', side_effect=lambda name: str(Path(self.directory.name) / name))
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def install(self, data):
        content = json.dumps(data).encode()
        manifest = dict(version=data['version'], sha256=hashlib.sha256(content).hexdigest(), url='test')
        return updates.install(manifest, fetch=lambda *args: content)

    def test_install_backup_rollback_and_snapshot(self):
        self.install(package())
        snapshot = updates.as_catalog(updates.read_package())
        self.install(package('2026.10.21.1'))
        self.assertEqual(snapshot['release_version'], '2026.10.20.1')
        self.assertEqual(updates.read_package()['version'], '2026.10.21.1')
        self.assertEqual(updates.rollback(), '2026.10.20.1')

    def test_bad_hash_and_incompatible_package_leave_active_unchanged(self):
        self.install(package())
        before = Path(updates.data_file(updates.ACTIVE)).read_bytes()
        with self.assertRaises(ValueError):
            updates.install(dict(url='test', sha256='0' * 64), lambda *args: b'{}')
        invalid = package('2026.10.21.1')
        invalid['engine'] = 2
        with self.assertRaises(ValueError):
            self.install(invalid)
        self.assertEqual(Path(updates.data_file(updates.ACTIVE)).read_bytes(), before)

    def test_first_installation_rolls_back_to_original_catalogue(self):
        self.install(package())
        self.assertEqual(updates.rollback(), '内置目录')
        self.assertIsNone(updates.read_package())
        self.assertEqual(updates.read_package(updates.PREVIOUS)['version'], '2026.10.20.1')

    def test_reject_unknown_groups_unclassified_ids_and_conflicting_identity(self):
        for change in ('unknown', 'missing', 'conflict', 'duplicate', 'empty'):
            data = package()
            if change == 'unknown':
                data['entries'][0]['group'] = 'new-rule-code'
            elif change == 'missing':
                data['entries'].pop()
            elif change == 'conflict':
                data['entries'][0]['rating'] = 'B'
            elif change == 'duplicate':
                data['entries'].append(data['entries'][0])
            else:
                data['entries'] = []
            with self.subTest(change=change), self.assertRaises(ValueError):
                updates.validate(data)

    def test_future_names_use_release_groups_not_old_allowlist(self):
        data = updates.as_catalog(package())
        self.assertEqual(len(catalog.prepare(data)['items']), 3)
        row = dict(type='Orbis Starport', modules=data['module_facts'][:2])
        evidence = tool.check_station(row, tool.build_criteria('Sol', 500), data)
        self.assertTrue(evidence['matched'])
        self.assertEqual(evidence['required'], 2)
        evidence = tool.check_station(row, tool.build_criteria('Sol', 500, ax_weapons=True), data)
        self.assertFalse(evidence['matched'])
        self.assertEqual(evidence['required'], 3)

    def test_loader_uses_installed_release_without_upstream_requests(self):
        self.install(package())
        with patch.object(catalog.eng, '_http_json', side_effect=AssertionError('unexpected network')):
            loaded = catalog.load(refresh=True)
        self.assertEqual(loaded['release_version'], '2026.10.20.1')

    def test_check_finds_catalog_release_not_application_release(self):
        prefix = f'https://github.com/{updates.REPOSITORY}/releases/download/'
        manifest = dict(format=1, engine=1, version='2026.10.20.1', file='catalog.json',
                        sha256='a'*64, summary='Reviewed equipment changes')
        releases = [dict(tag_name='v0.1.4', assets=[]),
                    dict(tag_name='catalog-2026.10.20.1', assets=[dict(name='catalog-manifest.json',
                         browser_download_url=prefix+'catalog-2026.10.20.1/catalog-manifest.json')])]
        def fetch(url, limit):
            return json.dumps(releases if url == updates.API else manifest).encode()
        self.assertEqual(updates.check(fetch)['version'], manifest['version'])
        self.assertIsNone(updates.check(lambda *args: b'[]'))

    def test_offline_check_preserves_active_and_downgrade_rejected(self):
        self.install(package('2026.10.21.1'))
        with self.assertRaises(OSError):
            updates.check(lambda *args: (_ for _ in ()).throw(OSError('offline')))
        with self.assertRaises(ValueError):
            self.install(package())
        self.assertEqual(updates.read_package()['version'], '2026.10.21.1')

    def test_build_assets_and_per_id_change_report(self):
        from scripts.build_catalog_release import build
        root = Path(self.directory.name)
        old = package()
        new = package('2026.10.21.1')
        new['entries'][0]['name'] = new['module_facts'][0]['name'] = 'Renamed Ordinary Module'
        (root/'old.json').write_text(json.dumps(old), encoding='utf-8')
        (root/'new.json').write_text(json.dumps(new), encoding='utf-8')
        manifest = build(root/'new.json', root/'output', 'Renamed one item', root/'old.json')
        content = (root/'output/catalog.json').read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), manifest['sha256'])
        changes = json.loads((root/'output/catalog-changes.json').read_text(encoding='utf-8'))
        self.assertEqual(len(changes['changed']), 1)
        self.assertEqual(changes['changed'][0]['after']['name'], 'Renamed Ordinary Module')

    def test_failed_atomic_replace_keeps_installed_catalogue(self):
        self.install(package())
        before = Path(updates.data_file(updates.ACTIVE)).read_bytes()
        replace = updates.os.replace
        def fail_active(source, target):
            if Path(target).name == updates.ACTIVE:
                raise OSError('simulated disk failure')
            return replace(source, target)
        with patch.object(updates.os, 'replace', side_effect=fail_active), self.assertRaises(OSError):
            self.install(package('2026.10.21.1'))
        self.assertEqual(Path(updates.data_file(updates.ACTIVE)).read_bytes(), before)
        self.assertFalse(list(Path(self.directory.name).glob('*.tmp')))


if __name__ == '__main__':
    unittest.main()
