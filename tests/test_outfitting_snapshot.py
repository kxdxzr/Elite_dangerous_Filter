import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import full_outfitting as tool
import outfitting_snapshot as snapshots


class OutfittingSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        paths = patch.object(snapshots, 'data_file', side_effect=lambda name: str(Path(self.directory.name)/name))
        paths.start()
        self.addCleanup(paths.stop)
        self.item = dict(name='Fuel Scoop', ed_symbol='scoop', **{'class': 2, 'rating': 'A'})
        self.catalog = dict(items=[self.item], issues=[], special_items=[], special_issues=[], ships=[], armours=[])
        self.rows = [dict(name='One', system_name='Near', type='Orbis Starport', distance=10,
                          system_x=10, system_y=0, system_z=0,
                          modules=[self.item], system_controlling_power='Li Yong-Rui', system_power_state='Fortified'),
                     dict(name='Two', system_name='Far', type='Orbis Starport', distance=100, modules=[self.item],
                          system_x=100, system_y=0, system_z=0)]
        self.fetched = dict(complete=True, rows=copy.deepcopy(self.rows), scanned=200, notes=[])

    def build(self, criteria=None, **options):
        with patch.object(snapshots.catalogue, 'load', return_value=copy.deepcopy(self.catalog)), \
                patch.object(tool, 'search', return_value=copy.deepcopy(self.fetched)) as fetch:
            result = snapshots.search(criteria or tool.build_criteria('Sol', 500), **options)
        return result, fetch

    def test_initial_strict_query_builds_widest_snapshot_not_limited_to_display_count(self):
        criteria = tool.build_criteria('Sol', 500, require_discount=True)
        result, fetch = self.build(criteria, want=1)
        used = fetch.call_args.args[0]
        self.assertEqual(used.reference, 'Sol')
        self.assertEqual(used.radius, 20000)
        self.assertFalse(used.require_discount)
        self.assertFalse(used.ax_weapons)
        self.assertFalse(used.special_equipment)
        self.assertEqual(fetch.call_args.kwargs['want'], 10001)
        self.assertEqual(len(snapshots.read()['rows']), 2)
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(result['criteria'], vars(criteria))

    def test_first_user_reference_does_not_change_fixed_discovery_scope(self):
        criteria = tool.build_criteria('New Reference', 20)
        with patch.object(tool, 'request_json', return_value=dict(results=[
                dict(name='New Reference', x=95, y=0, z=0)])):
            result, fetch = self.build(criteria)
        self.assertEqual(fetch.call_args.args[0].reference, 'Sol')
        self.assertEqual(fetch.call_args.args[0].radius, 20000)
        self.assertEqual([row['name'] for row in result['rows']], ['Two'])
        self.assertEqual(result['rows'][0]['distance'], 5)
        self.assertEqual(result['snapshot_scope']['radius'], 20000)

    def test_subsequent_queries_are_offline_and_use_same_catalogue_and_stock(self):
        first, _ = self.build()
        with patch.object(snapshots.catalogue, 'load', side_effect=AssertionError('catalogue network')), \
                patch.object(tool, 'search', side_effect=AssertionError('inventory network')):
            result = snapshots.search(tool.build_criteria('sol', 500), want=100)
            smaller = snapshots.search(tool.build_criteria('Sol', 50))
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(len(smaller['rows']), 1)
        self.assertEqual(first['snapshot_created_at'], result['snapshot_created_at'])

    def test_larger_radius_and_new_reference_reuse_inventory_and_recalculate_sorting(self):
        self.build()
        path = Path(snapshots.data_file(snapshots.NAME))
        before = path.read_bytes()
        with patch.object(tool, 'search', side_effect=AssertionError('network')):
            expanded = snapshots.search(tool.build_criteria('Sol', 600))
            self.assertEqual(len(expanded['rows']), 2)
            with patch.object(tool, 'request_json', return_value=dict(results=[
                    dict(name='New Reference', x=95, y=0, z=0)])) as lookup:
                changed = snapshots.search(tool.build_criteria('New Reference', 200), want=1)
                self.assertEqual(changed['rows'][0]['name'], 'Two')
                self.assertEqual(changed['rows'][0]['distance'], 5)
                self.assertEqual(lookup.call_count, 1)
                self.assertIn('/systems/search', lookup.call_args.args[0])
            with patch.object(tool, 'request_json', side_effect=AssertionError('coordinates already cached')):
                again = snapshots.search(tool.build_criteria('New Reference', 20))
                self.assertEqual([r['name'] for r in again['rows']], ['Two'])
        self.assertEqual(path.read_bytes(), before)

    def test_unknown_reference_does_not_reuse_old_distances_or_replace_stock(self):
        self.build()
        before = Path(snapshots.data_file(snapshots.NAME)).read_bytes()
        with patch.object(tool, 'request_json', return_value=dict(results=[])), self.assertRaises(ValueError):
            snapshots.search(tool.build_criteria('Unknown Reference', 500))
        self.assertEqual(Path(snapshots.data_file(snapshots.NAME)).read_bytes(), before)

    def test_failed_refresh_keeps_previous_file_and_success_replaces_it(self):
        self.build()
        path = Path(snapshots.data_file(snapshots.NAME))
        before = path.read_bytes()
        self.fetched['complete'] = False
        with self.assertRaisesRegex(ValueError, '原快照未替换'):
            self.build(refresh=True)
        self.assertEqual(path.read_bytes(), before)
        self.fetched['complete'] = True
        self.fetched['rows'] = self.fetched['rows'][:1]
        self.build(refresh=True)
        self.assertEqual(len(snapshots.read()['rows']), 1)

    def test_local_filter_keeps_missing_stricter_inventory_out_and_does_not_mutate_snapshot(self):
        self.build()
        snapshot = snapshots.read()
        before = copy.deepcopy(snapshot)
        result = snapshots.filter_snapshot(snapshot, tool.build_criteria('Sol', 500, guardian=True))
        self.assertEqual(result['rows'], [])
        self.assertEqual(snapshot, before)
        stopped = threading.Event()
        stopped.set()
        result = snapshots.filter_snapshot(snapshot, tool.build_criteria('Sol', 500), stop=stopped)
        self.assertTrue(result['partial'])
        self.assertTrue(result['stopped'])

    def test_corrupt_snapshot_does_not_automatically_reconnect(self):
        Path(snapshots.data_file(snapshots.NAME)).write_text('{}', encoding='utf-8')
        with patch.object(tool, 'search', side_effect=AssertionError('network')), self.assertRaises(ValueError):
            snapshots.search(tool.build_criteria('Sol', 500))

    def test_existing_fixed_scope_v1_is_migrated_in_place_without_inventory_scan(self):
        original, _ = self.build()
        path = Path(snapshots.data_file(snapshots.NAME))
        data = json.loads(path.read_text(encoding='utf-8'))
        data['schema'] = 1
        path.write_text(json.dumps(data), encoding='utf-8')
        with patch.object(tool, 'search', side_effect=AssertionError('must reuse inventory')), \
                patch.object(snapshots.catalogue, 'load', side_effect=AssertionError('must reuse catalogue')):
            result = snapshots.search(tool.build_criteria('Sol', 500))
        self.assertEqual(result['snapshot_created_at'], original['snapshot_created_at'])
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['schema'], snapshots.SCHEMA)
        self.assertEqual(len(list(Path(self.directory.name).glob('full_outfitting_snapshot*.json'))), 1)

    def test_small_old_scope_is_not_mistaken_for_fixed_scope_or_overwritten_on_read(self):
        self.build()
        path = Path(snapshots.data_file(snapshots.NAME))
        data = json.loads(path.read_text(encoding='utf-8'))
        data['schema'] = 1
        data['scope']['radius'] = 500
        path.write_text(json.dumps(data), encoding='utf-8')
        before = path.read_bytes()
        with patch.object(tool, 'search', side_effect=AssertionError('no auto scan')), self.assertRaises(ValueError):
            snapshots.search(tool.build_criteria('Sol', 500))
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
