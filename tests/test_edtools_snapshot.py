from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch

import edtools_snapshot as store
import pve_tool as pve


def records(target='Target', stamp=1000):
    data = ({'Source': dict(x=1, y=0, z=0, target=target, t_r=1)},
            {target: dict(haz='', high='', reg='', low='1', beac=0)})
    return {url: dict(data=value, digest=store.digest(value), fetched_at=stamp,
                     last_modified='Mon, 02 Nov 2026 00:00:00 GMT', etag='"test"')
            for url, value in zip(store.URLS, data)}


class EDToolsSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name)
        self.patches = [patch.object(store, 'data_file', side_effect=lambda name: str(self.path / name)),
                        patch.object(store, 'bundled_path', return_value=self.path / 'default.json')]
        for item in self.patches:
            item.start()
        store._memory.clear()

    def tearDown(self):
        store._memory.clear()
        for item in reversed(self.patches):
            item.stop()
        self.folder.cleanup()

    def seed(self, target='Target', bundled=False):
        value = store.bundle(records(target), installed_at=1000, **({'bundled_at': 1000} if bundled else {}))
        if bundled:
            (self.path / 'default.json').write_text(json.dumps(value), encoding='utf-8')
        else:
            store.write(store.ACTIVE, value)
        return value

    def test_bundled_offline_no_expiry_and_user_override(self):
        baseline = self.seed(bundled=True)
        with patch.object(store, 'download', side_effect=AssertionError('offline')), \
                patch.object(store.time, 'time', return_value=10**9):
            data, info = store.get(store.URLS[0])
            self.assertEqual(data['Source']['target'], 'Target')
            self.assertEqual(info['source'], 'bundled')
            store._memory.clear()
            self.assertEqual(store.load()['generation'], baseline['generation'])
        updated = self.seed('New')
        self.assertEqual(store.load()['generation'], updated['generation'])
        data['Source']['target'] = 'Mutated'
        self.assertEqual(store.get(store.URLS[0])[0]['Source']['target'], 'New')

    def test_missing_bundle_initializes_both_once(self):
        with patch.object(store, 'download', side_effect=list(records().values())) as download:
            store.get(store.URLS[0])
            store.get(store.URLS[1])
        self.assertEqual(download.call_count, 2)
        self.assertTrue((self.path / store.ACTIVE).exists())

    def test_failed_second_initial_download_writes_nothing(self):
        with patch.object(store, 'download', side_effect=[records()[store.URLS[0]], OSError('offline')]):
            with self.assertRaises(OSError):
                store.load()
        self.assertFalse((self.path / store.ACTIVE).exists())

    def test_check_stages_but_does_not_install_and_apply_needs_matching_generation(self):
        old = self.seed()
        with patch.object(store, 'download', side_effect=list(records('New').values())):
            result = store.check(force=True)
        self.assertEqual(result['status'], 'available')
        self.assertEqual(store.load()['generation'], old['generation'])
        with self.assertRaises(ValueError):
            store.update('wrong generation')
        with patch.object(store, 'download', side_effect=AssertionError('must use staged copy')):
            updated = store.update(result['generation'])
        self.assertNotEqual(updated['generation'], old['generation'])
        self.assertEqual(store.get(store.URLS[0])[0]['Source']['target'], 'New')
        self.assertFalse((self.path / store.PENDING).exists())

    def test_query_scope_pins_both_resources_across_update(self):
        old = self.seed()
        with store.scope():
            self.assertEqual(store.get(store.URLS[0])[1]['generation'], old['generation'])
            with patch.object(store, 'download', side_effect=list(records('New').values())):
                store.update()
            with store.scope():
                sites, info = store.get(store.URLS[1])
            self.assertIn('Target', sites)
            self.assertEqual(info['generation'], old['generation'])
        self.assertIn('New', store.get(store.URLS[1])[0])

    def test_failure_preserves_active_and_check_is_throttled(self):
        old = self.seed()
        with patch.object(store, 'download', side_effect=OSError('offline')) as download:
            self.assertEqual(store.check(force=True)['status'], 'failed')
            self.assertEqual(store.check()['status'], 'failed')
            self.assertEqual(download.call_count, 1)
        self.assertEqual(store.load()['generation'], old['generation'])

    def test_success_checks_are_throttled_and_formatting_does_not_change_digest(self):
        self.seed()
        with patch.object(store, 'download', side_effect=list(records().values())) as download:
            self.assertEqual(store.check(force=True)['status'], 'unchanged')
            self.assertEqual(store.check()['status'], 'recent')
            self.assertEqual(download.call_count, 2)
        self.assertEqual(store.digest({'a': 1, 'b': 2}), store.digest({'b': 2, 'a': 1}))

    def test_rechecking_pending_uses_active_validators_not_new_content_validators(self):
        self.seed()
        updated_records = records('New')
        updated_records[store.URLS[0]]['etag'] = '"new"'
        with patch.object(store, 'download', side_effect=list(updated_records.values())):
            self.assertEqual(store.check(force=True)['status'], 'available')
        with patch.object(store, 'download', side_effect=list(updated_records.values())) as download:
            self.assertEqual(store.check(force=True)['status'], 'available')
        self.assertEqual(download.call_args_list[0].args[1]['etag'], '"test"')

    def test_partial_failed_check_or_install_never_replaces_pair(self):
        old = self.seed()
        with patch.object(store, 'download', side_effect=[records('New')[store.URLS[0]], ValueError('bad sites')]):
            self.assertEqual(store.check(force=True)['status'], 'failed')
        self.assertIsNone(store.pending())
        with patch.object(store, 'download', side_effect=[records('New')[store.URLS[0]], OSError('offline')]):
            with self.assertRaises(OSError):
                store.update()
        self.assertEqual(store.load()['generation'], old['generation'])

    def test_atomic_write_failure_keeps_previous_generation(self):
        old = self.seed()
        with patch.object(store, 'download', side_effect=list(records('New').values())), \
                patch.object(store, 'atomic_write', side_effect=OSError('read only')):
            with self.assertRaises(OSError):
                store.update()
        self.assertEqual(store.load()['generation'], old['generation'])

    def test_conditional_get_304_uses_etag_or_modified_and_does_not_read_body(self):
        record = records()[store.URLS[0]]
        for key, header in (('etag', 'If-none-match'), ('last_modified', 'If-modified-since')):
            previous = deepcopy(record)
            if key == 'last_modified':
                previous.pop('etag')
            error = urllib.error.HTTPError(store.URLS[0], 304, 'Not Modified', {}, None)
            with patch.object(store.urllib.request, 'urlopen', side_effect=error) as get:
                result = store.download(store.URLS[0], previous)
            self.assertEqual(result, previous)
            self.assertEqual(get.call_args.args[0].get_header(header), previous[key])

    def test_download_validates_full_content_and_body_size(self):
        data = records()[store.URLS[0]]['data']
        for payload, valid in ((json.dumps(data).encode(), True), (b'{}', False), (b'<html>', False)):
            response = io.BytesIO(payload)
            response.headers = {'Last-Modified': 'today', 'Content-Length': str(len(payload))}
            with patch.object(store.urllib.request, 'urlopen', return_value=response):
                if valid:
                    self.assertEqual(store.download(store.URLS[0])['data'], data)
                else:
                    with self.assertRaises(ValueError):
                        store.download(store.URLS[0])
        response = io.BytesIO(b'{}')
        response.headers = {'Content-Length': '20'}
        with patch.object(store.urllib.request, 'urlopen', return_value=response), self.assertRaisesRegex(ValueError, 'Incomplete'):
            store.download(store.URLS[0])

    def test_all_radii_and_dynamic_refresh_use_same_snapshot_without_html(self):
        self.seed()
        with patch.object(store, 'download', side_effect=AssertionError('no refresh')), \
                patch.object(pve, '_download_page', side_effect=AssertionError('no HTML')), \
                patch.object(pve.eng, 'get_system_coords', return_value=(0, 0, 0)):
            for radius in (10, 50, 250, 500, 0):
                page = pve.fetch_page(pve.Criteria(radius=radius), 'Sol', refresh=True)
                self.assertEqual(page['rows'][0]['source'], 'Source')
                self.assertTrue(all(item['manual_snapshot'] for item in page['cache']))

    def test_bundle_in_repository_is_complete_and_valid(self):
        original = Path(__file__).resolve().parents[1] / 'assets/edtools/default.json'
        with patch.object(store, 'bundled_path', return_value=original):
            baseline = store.read('bundled')
        self.assertIsNotNone(baseline)
        self.assertEqual(set(baseline['resources']), set(store.URLS))
