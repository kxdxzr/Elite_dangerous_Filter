import io
import json
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import outfitting_catalog as tool


class OutfittingCatalogTests(unittest.TestCase):
    def setUp(self):
        facts = [dict(ed_id=1, name='Beam Laser', ed_symbol='beam', category='hardpoint',
                      **{'class': 1, 'rating': 'E'}),
                 dict(ed_id=2, name='Rapid Phase Multi-Cannon', ed_symbol='multi', category='mercgear',
                      **{'class': 2, 'rating': 'E'})]
        patcher = patch.object(tool.identity, 'download_facts', return_value=facts)
        patcher.start()
        self.addCleanup(patcher.stop)

    def archive(self, rows):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            content = json.dumps({'bl': rows}).encode()
            info = tarfile.TarInfo('root/modules/hardpoints/beam_laser.json')
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        return stream.getvalue()

    def test_mounts_come_from_real_symbols_not_size_rating_product(self):
        first = dict(name='Beam Laser', ed_symbol='beam_fixed', **{'class': 1, 'rating': 'E'})
        items = {tool.variant(first): first}
        rows = [dict(symbol='beam_turret', **{'class': 1, 'rating': 'F'}),
                dict(symbol='guardian_unknown', name='Guardian', **{'class': 2, 'rating': 'A'})]
        tool.supplement(self.archive(rows), items)
        self.assertEqual({item['ed_symbol'] for item in items.values()}, {'beam_fixed', 'beam_turret'})
        self.assertNotIn(('Beam Laser', 1, 'A'), {(i['name'], i['class'], i['rating']) for i in items.values()})

    def test_no_symbol_collisions_between_base_and_power_module(self):
        items = [dict(name=name, ed_symbol='same', **{'class': 2, 'rating': 'B'})
                 for name in ('Rail Gun', 'Enduring Feedback Rail Gun')]
        self.assertEqual(len({tool.variant(item) for item in items}), 2)

    def test_ordinary_excludes_brokers_engineer_only_and_armour_but_keeps_power(self):
        for name in ('Guardian FSD Booster', 'Shock Cannon', 'Enhanced Performance Thrusters',
                     'Military Grade Composite'):
            self.assertFalse(tool.ordinary(name))
        for name in tool.POWER_MODULES:
            self.assertTrue(tool.ordinary(name), name)
        for name in tool.SPECIAL_MODULES:
            self.assertFalse(tool.ordinary(name), name)

    def test_cached_catalogue_and_cancel_do_not_send_network_requests(self):
        item = dict(name='Beam Laser', ed_symbol='beam', **{'class': 1, 'rating': 'E'})
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(tool, 'data_file', return_value=str(Path(directory) / 'catalog.json')), \
                patch.object(tool, 'required_pairs', return_value={('Beam Laser', 1, 'E')}):
            http = lambda *args: dict(results=[dict(modules=[item])])
            result = tool.load(http=http, archive_fetch=lambda: self.archive([]))
            self.assertEqual(result['issues'], [])
            with patch.object(tool.eng, '_http_json', side_effect=AssertionError('network')):
                self.assertEqual(tool.load()['items'], result['items'])
            stop = threading.Event()
            stop.set()
            with self.assertRaises(InterruptedError):
                tool.load(stop=stop)

    def test_failed_catalogue_audit_is_not_saved_as_complete(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(tool, 'data_file', return_value=str(Path(directory) / 'catalog.json')), \
                patch.object(tool, 'required_pairs', return_value={('Beam Laser', 1, 'E')}):
            result = tool.load(http=lambda *args: dict(results=[]), archive_fetch=lambda: self.archive([]))
            self.assertTrue(result['issues'])
            self.assertFalse((Path(directory) / 'catalog.json').exists())

    def test_old_cache_is_not_used_for_v4_checks(self):
        item = dict(name='Beam Laser', ed_symbol='beam', **{'class': 1, 'rating': 'E'})
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(tool, 'data_file', return_value=str(Path(directory) / 'v4.json')) as path, \
                patch.object(tool, 'required_pairs', return_value={('Beam Laser', 1, 'E')}):
            old = Path(directory) / 'v1.json'
            old.write_text('original v1 file', encoding='utf8')
            calls = []

            def http(*args):
                calls.append(args)
                return dict(results=[dict(modules=[item])])

            result = tool.load(http=http, archive_fetch=lambda: self.archive([]))
            path.assert_called_with('full_outfitting_catalog_v4.json')
            self.assertTrue(calls)
            self.assertEqual(result['schema'], 4)
            self.assertEqual(old.read_text(encoding='utf8'), 'original v1 file')

    def test_special_identity_metadata_does_not_trigger_extra_inventory_requests(self):
        base = dict(name='Beam Laser', ed_symbol='beam', **{'class': 1, 'rating': 'E'})
        special = dict(name='Rapid Phase Multi-Cannon', ed_symbol='multi', **{'class': 2, 'rating': 'E'})
        requests = []

        def http(url, payload):
            requests.append(payload)
            return dict(results=[dict(modules=[base, special] if 'modules' in payload['filters'] else [base])])

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(tool, 'data_file', return_value=str(Path(directory) / 'catalog.json')), \
                patch.object(tool, 'SPECIAL_MODULES', {'Rapid Phase Multi-Cannon'}), \
                patch.object(tool, 'required_pairs', return_value={('Beam Laser', 1, 'E')}):
            initial = tool.load(http=http, archive_fetch=lambda: self.archive([]))
            self.assertEqual(len(requests), 2)
            self.assertTrue(initial['special_checked'])
            selected = tool.load(include_special=True, http=http,
                                 archive_fetch=lambda: self.fail('base archive must be reused'))
            self.assertEqual(len(requests), 2)
            self.assertEqual(selected['special_issues'], [])
            self.assertEqual(len(selected['special_items']), 1)
            self.assertEqual(len(selected['items']), 1)
            self.assertEqual(tool.load(include_special=True)['fingerprint'], selected['fingerprint'])
