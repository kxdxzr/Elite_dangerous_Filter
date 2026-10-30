import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import colonisation_tool as colony
import filter_engine as eng
import pve_cache


class SearchSpeedTests(unittest.TestCase):
    def test_repacking_cached_batch_preserves_original_freshness(self):
        with patch.object(pve_cache, 'peek', return_value=(False, None)), \
                patch.object(pve_cache, 'cached', return_value=({'a': []}, dict(fetched_at=123, hit=True))), \
                patch.object(pve_cache, 'put') as save:
            colony.load_bodies(['A'])
            save.assert_called_once_with('body-system-v1:a', [], fetched_at=123)

    def test_body_cache_reuses_overlap_and_refresh_bypasses_it(self):
        requests = []
        def http(url, payload, **kwargs):
            names = payload['filters']['system_name']['value']
            requests.append(names)
            return dict(results=[dict(name=name + ' 1', system_name=name, type='Planet') for name in names])
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(pve_cache, 'data_file', side_effect=lambda name: str(Path(folder) / name)), \
                patch.object(eng, '_http_json', side_effect=http):
            pve_cache.clear_memory()
            a = colony.load_bodies(['Cache A', 'Cache B'])
            a['cache b'][0]['type'] = 'altered by caller'
            b = colony.load_bodies(['Cache B', 'Cache C'])
            self.assertEqual(b['cache b'][0]['type'], 'Planet')
            self.assertEqual(requests, [['Cache A', 'Cache B'], ['Cache C']])
            pve_cache.clear_memory()  # Disk entries also work across batch regrouping.
            colony.load_bodies(['Cache A', 'Cache C'])
            self.assertEqual(len(requests), 2)
            colony.load_bodies(['Cache B'], refresh=True)
            self.assertEqual(requests[-1], ['Cache B'])
        pve_cache.clear_memory()

    def test_failed_partial_batch_is_not_published_as_complete(self):
        with patch.object(pve_cache, 'peek', return_value=(False, None)), \
                patch.object(pve_cache, 'put') as save, \
                patch.object(colony, '_load_bodies_batch', return_value={'a': []}):
            with self.assertRaises(ValueError):
                colony.load_bodies(['A', 'B'])
            save.assert_not_called()

    def test_main_reuses_body_evidence_for_ring_filter_and_stops_scheduling(self):
        calls = []
        def bodies(names, **kwargs):
            calls.extend(names)
            return {name.casefold(): [dict(name=name + ' 1', type='Planet', subtype='Water world',
                rings=[dict(name=name + ' A Ring', type='Metallic')])] for name in names}
        conditions = [dict(type='system_details', body_groups=[[dict(field='subtype', op='=', value='Water world')]]),
                      dict(type='rings', mode='types', values=['Metallic'])]
        response = dict(results=[dict(name=f'Sys {i}', id64=i) for i in range(100)])
        with patch.object(colony, 'load_bodies', side_effect=bodies):
            rows, _, _ = eng.search('systems', conditions, want=1, http=lambda *a: response)
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(len(calls), 16)
        self.assertEqual(len(calls), len(set(calls)))

    def test_neighbour_parallelism_is_bounded_to_four(self):
        lock, gate = threading.Lock(), threading.Barrier(4)
        active = [0, 0]
        def lookup(*args, **kwargs):
            with lock:
                active[0] += 1
                active[1] = max(active)
            gate.wait(timeout=5)
            with lock:
                active[0] -= 1
            return True, 'Near', 1, 1
        with patch.object(colony, 'populated_neighbour', side_effect=lookup):
            results = colony._neighbours_batch([dict(name=f'S{i}') for i in range(4)], colony.Criteria(), None)
        self.assertEqual(active[1], 4)
        self.assertTrue(all(not isinstance(result, Exception) for result in results.values()))

    def test_colony_does_not_schedule_entire_page_when_one_hit_is_enough(self):
        response = dict(results=[dict(name=f'S{i}', population=0, stations=[], needs_permit=False) for i in range(100)])
        with patch.object(eng, '_http_json', return_value=response), \
                patch.object(colony, 'populated_neighbour', return_value=(True, 'Near', 1, 1)) as lookup:
            _, rows = colony.search(colony.Criteria(want=1, populated_radius=10))
        self.assertEqual(len(rows), 1)
        self.assertEqual(lookup.call_count, 1)
