from copy import deepcopy
import threading
import unittest
from unittest.mock import Mock

import pve_tool as pve
from test_pve_tool import candidate, page, faction


class PvePipelineTests(unittest.TestCase):
    def search(self, rows, **kwargs):
        criteria = kwargs.pop('criteria', pve.Criteria(radius=0, min_factions=3, target_controller='Pirates'))
        return pve.search(criteria, page=page(*rows), ring_loader=lambda names: {}, **kwargs)

    def test_unlimited_source_rejections_skip_targets_and_preserve_all_results(self):
        rows = [candidate(f'S{i}', f'T{i}', distance=100000 + i) for i in range(40)]
        calls, streamed = [], []
        def load(name):
            calls.append(name)
            if name.startswith('S'):
                return dict(minor_faction_presences=[faction(str(i)) for i in range(3 if int(name[1:]) % 4 == 0 else 1)])
            return dict(controlling_minor_faction='Pirates')
        info, result = self.search(rows, workers=4, details_loader=load,
                                   on_results=lambda batch: streamed.extend(batch))
        self.assertTrue(info['complete'])
        self.assertEqual(info['scanned'], 40)
        self.assertEqual(len(calls), 50)  # Eager algorithm would load 40 + 40.
        self.assertEqual(info['detail_requests'], 50)
        self.assertEqual({name for name in calls if name.startswith('T')}, {f'T{i}' for i in range(0, 40, 4)})
        self.assertEqual([r['source'] for r in result], [f'S{i}' for i in range(0, 40, 4)])
        self.assertEqual(streamed, result)

    def test_stream_before_next_batch_and_shared_system_requested_once(self):
        rows = [candidate(f'S{i}', 'Shared', distance=i) for i in range(20)]
        calls, streamed = [], []
        def load(name):
            if name == 'S8':
                self.assertEqual(len(streamed), 8)
            calls.append(name)
            return dict(minor_faction_presences=[faction(str(i)) for i in range(3)], controlling_minor_faction='Pirates')
        info, result = self.search(rows, workers=4, details_loader=load,
                                   on_results=lambda batch: streamed.extend(deepcopy(batch)))
        self.assertTrue(info['complete'])
        self.assertEqual(len(result), 20)
        self.assertEqual(calls.count('Shared'), 1)
        self.assertEqual(info['detail_requests'], 21)

    def test_casefold_dedup_across_sources_targets_and_batches(self):
        rows = [candidate('Shared', 'Target'), candidate('SHARED', 'Other'), candidate('Target', 'SHARED')]
        loader = Mock(return_value=dict(minor_faction_presences=[faction(str(i)) for i in range(3)],
                                       controlling_minor_faction='Pirates'))
        _, result = self.search(rows, workers=4, details_loader=loader)
        self.assertEqual(len(result), 3)
        self.assertEqual(loader.call_count, 3)

    def test_local_only_unlimited_uses_no_details_and_streams_without_duplicates(self):
        rows = [candidate(f'S{i}', distance=100000 + i) for i in range(100)]
        loader, streamed = Mock(side_effect=AssertionError('No dynamic filter')), []
        info, result = self.search(rows + [rows[0]], criteria=pve.Criteria(radius=0), workers=4,
                                   details_loader=loader, on_results=lambda batch: streamed.extend(batch))
        loader.assert_not_called()
        self.assertEqual(info['detail_requests'], 0)
        self.assertEqual(streamed, result)
        self.assertEqual(len(result), 100)

    def test_stop_after_first_verified_batch_keeps_only_verified_rows(self):
        stop, calls, streamed = threading.Event(), [], []
        def load(name):
            calls.append(name)
            return dict(minor_faction_presences=[faction(str(i)) for i in range(3)], controlling_minor_faction='Pirates')
        def receive(batch):
            streamed.extend(batch)
            stop.set()
        info, result = self.search([candidate(f'S{i}', f'T{i}') for i in range(40)],
            workers=4, details_loader=load, stop=stop, on_results=receive)
        self.assertFalse(info['complete'])
        self.assertEqual(len(result), 1)
        self.assertEqual(streamed, result)
        self.assertLessEqual(len(calls), 16)

    def test_cnb_waits_for_full_absence_and_errors_suppress_it(self):
        for fail in (False, True):
            streamed = []
            def load(name):
                self.assertEqual(streamed, [])
                if fail and name == 'Bad':
                    raise OSError('offline')
                return dict(minor_faction_presences=[faction('Only one')])
            rows = [candidate('CNB', sites=(), cnb=True), candidate('Bad')]
            # CNB passes while the potential RES candidate is rejected or unknown.
            def details(name):
                if name == 'CNB':
                    return dict(minor_faction_presences=[faction(str(i)) for i in range(3)])
                return load(name)
            info, result = self.search(rows, criteria=pve.Criteria(radius=0, min_factions=3),
                workers=4, details_loader=details, on_results=lambda batch: streamed.extend(batch))
            self.assertEqual(info['complete'], not fail)
            self.assertEqual(len(result), 0 if fail else 1)
            self.assertEqual(streamed, result)

    def test_ring_limit_never_streams_before_verification(self):
        streamed = []
        def rings(names):
            self.assertEqual(streamed, [])
            return {'near': dict(seen=True, distance=10, body='Near 1'),
                    'far': dict(seen=True, distance=500)}
        info, result = pve.search(pve.Criteria(radius=0, target_ring_max_ls=50),
            page=page(candidate('A', 'Near'), candidate('B', 'Far')), ring_loader=rings,
            on_results=lambda batch: streamed.extend(batch))
        self.assertTrue(info['complete'])
        self.assertEqual(streamed, result)
        self.assertEqual([r['target'] for r in result], ['Near'])

    def test_stream_snapshot_cannot_mutate_results_and_final_sort_is_retained(self):
        names = []
        def receive(batch):
            names.extend(row['source'] for row in batch)
            batch[0]['source'] = 'Corrupted'
        _, result = self.search([candidate('High', distance=1, sites=('high',)), candidate('Low', distance=10)],
            criteria=pve.Criteria(radius=0), on_results=receive)
        self.assertEqual(names, ['High', 'Low'])
        self.assertEqual([r['source'] for r in result], ['Low', 'High'])
