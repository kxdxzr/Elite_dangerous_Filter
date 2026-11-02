import copy
import threading
import unittest
from unittest.mock import patch
from urllib.error import URLError

import filter_engine as eng
import colonisation_tool as colony
import system_filters as details


class StagedSearchTests(unittest.TestCase):
    def test_faction_rejection_skips_station_body_and_neighbour_requests(self):
        conditions = eng.normalize_conditions('systems', [
            dict(field='minor_faction_count', op='=', text=1),
            dict(field='station_count', op='=', text=0),
            dict(type='system_details', body_groups=[[dict(field='subtype', op='=', value='Water world')]],
                 nearest_max=100)])
        rows = [dict(name='Rejected', minor_faction_presences=[])]
        with patch.object(details.bodies, 'confirm_station_absence') as stations, \
                patch.object(details.bodies, 'load_bodies') as bodies, \
                patch.object(details.bodies, 'populated_neighbour') as near:
            details.prepare(rows, conditions)
        stations.assert_not_called()
        bodies.assert_not_called()
        near.assert_not_called()

    def test_station_groups_reject_before_body_and_neighbour_requests(self):
        conditions = eng.normalize_conditions('systems', [dict(type='system_details',
            station_groups=[[dict(field='services', op='=', value='Repair')]],
            body_groups=[[dict(field='subtype', op='=', value='Water world')]], nearest_max=100)])
        for records in ([], [dict(name='Unknown')]):
            with self.subTest(records=records), \
                    patch.object(details.bodies, 'confirm_station_absence', return_value={'a': records}), \
                    patch.object(details.bodies, 'load_bodies') as bodies, \
                    patch.object(details.bodies, 'populated_neighbour') as near:
                rows = [dict(name='A')]
                details.prepare(rows, conditions)
                self.assertFalse(eng.match_candidate('systems', rows[0], conditions, {}, {}, set()))
                bodies.assert_not_called()
                near.assert_not_called()

    def test_colony_cheap_rejections_skip_station_queries(self):
        candidates = [dict(name='Low', population=0, needs_permit=False, x=0, y=0, z=0,
                           estimated_scan_value=1),
                      dict(name='Far', population=0, needs_permit=False, x=500, y=0, z=0,
                           estimated_scan_value=100)]
        with patch.object(eng, '_http_json', return_value=dict(results=candidates)), \
                patch.object(eng, 'resolve_ref', return_value=('Sol', (0, 0, 0), False)), \
                patch.object(colony, 'confirm_station_absence') as stations:
            _, rows = colony.search(colony.Criteria(reference='Sol', radius=10, minimum_value=10))
        self.assertEqual(rows, [])
        stations.assert_not_called()

    def test_later_body_rejection_skips_earlier_neighbour_condition(self):
        conditions = eng.normalize_conditions('systems', [
            dict(type='system_details', nearest_max=100),
            dict(type='system_details', body_groups=[[dict(field='subtype', op='=', value='Water world')]])])
        rows = [dict(name='A')]
        with patch.object(details.bodies, 'load_bodies', return_value={'a': []}), \
                patch.object(details.bodies, 'populated_neighbour') as near:
            details.prepare(rows, conditions)
        near.assert_not_called()
        self.assertIsNone(details.outcome(rows[0], conditions[0]))

    def test_stream_precedes_next_page_and_is_detached(self):
        events = []
        def http(url, payload):
            if payload['page']:
                self.assertEqual(events, ['A'])
            return dict(results=[dict(id64=payload['page'], name='AB'[payload['page']])])
        def receive(batch):
            events.extend(r['name'] for r in batch)
            batch[0]['name'] = 'Mutated by consumer'
        rows, _, _ = eng.search('systems', [], want=2, page_size=1, http=http, on_results=receive)
        self.assertEqual(events, ['A', 'B'])
        self.assertEqual([r['name'] for r in rows], events)

    def test_stream_resume_no_duplicates_and_failure_preserves_verified_rows(self):
        state, events, failed = {}, [], [False]
        def http(url, payload):
            if payload['page'] == 1 and not failed[0]:
                failed[0] = True
                raise URLError('offline')
            return dict(results=[dict(id64=payload['page'], name='AB'[payload['page']])])
        args = dict(kind='systems', conditions=[], want=2, page_size=1, http=http,
                    resume=state, on_results=lambda batch: events.extend(r['name'] for r in batch))
        eng.search(**args)
        self.assertEqual(events, ['A'])
        self.assertTrue(state['paused'])
        rows, _, _ = eng.search(**args)
        self.assertEqual(events, ['A', 'B'])
        self.assertEqual([r['name'] for r in rows], events)

    def test_only_verified_rows_stream_and_stop_retains_them(self):
        events, stop = [], threading.Event()
        conditions = [dict(type='rings', mode='present')]
        records = {'a': [dict(name='A 1', rings=[])],
                   'b': [dict(name='B 1', rings=[dict(type='Icy')]) ]}
        def receive(batch):
            events.extend(copy.deepcopy(batch))
            stop.set()
        with patch.object(colony, 'load_bodies', return_value=records), \
                patch.object(eng, '_http_json', return_value=dict(results=[dict(name='A'), dict(name='B')])):
            rows, _, _ = eng.search('systems', conditions, on_results=receive, stop=stop, resume={})
        self.assertEqual([r['name'] for r in events], ['B'])
        self.assertEqual(rows, events)

    def test_colony_stream_is_detached_and_matches_final_rows(self):
        events = []
        def receive(batch):
            events.extend(copy.deepcopy(batch))
            batch[0]['name'] = 'Changed'
        with patch.object(eng, '_http_json', return_value=dict(results=[
                dict(name='A', population=0, stations=[], needs_permit=False)])):
            _, rows = colony.search(colony.Criteria(), on_results=receive)
        self.assertEqual(rows, events)
        self.assertEqual(rows[0]['name'], 'A')
