import copy
import threading
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

import colonisation_tool as colony
import filter_engine as eng


def gateway():
    return HTTPError('https://spansh.co.uk/api/systems/search', 502, 'Bad Gateway', {}, None)


def candidate(name, **values):
    return dict(name=name, population=0, stations=[], needs_permit=False, **values)


class SearchRecoveryTests(unittest.TestCase):
    def test_manual_stop_then_continue_reuses_page_and_preserves_matches(self):
        state, stop, stopped = {}, threading.Event(), [False]
        def check(row):
            if not stopped[0]:
                stopped[0] = True
                stop.set()
            return True
        with patch.object(eng, '_http_json', return_value=dict(results=[dict(name='A'), dict(name='B')])) as http:
            rows, _, _ = eng.search('systems', [], resume=state, row_filter=check, stop=stop)
            self.assertEqual([r['name'] for r in rows], ['A'])
            self.assertTrue(state['paused'])
            self.assertIn('batch', state)
            stop.clear()
            rows, _, scanned = eng.search('systems', [], resume=state, row_filter=check, stop=stop)
            self.assertEqual([r['name'] for r in rows], ['A', 'B'])
            self.assertEqual(scanned, 2)
            self.assertFalse(state['paused'])
            http.assert_called_once()

    def test_colony_manual_stop_then_continue(self):
        state, stop, stopped = {}, threading.Event(), [False]
        def rank(*args):
            if not stopped[0]:
                stopped[0] = True
                stop.set()
            return [], False
        response = dict(results=[candidate('A'), candidate('B')])
        with patch.object(eng, '_http_json', return_value=response) as http, \
                patch.object(colony, 'top_scan_planets', side_effect=rank):
            info, rows = colony.search(colony.Criteria(), resume=state, stop=stop)
            self.assertEqual([r['name'] for r in rows], ['A'])
            self.assertTrue(state['paused'])
            stop.clear()
            info, rows = colony.search(colony.Criteria(), resume=state, stop=stop)
            self.assertTrue(info['complete'])
            self.assertEqual([r['name'] for r in rows], ['A', 'B'])
            self.assertEqual(info['scanned'], 2)
            http.assert_called_once()

    def test_main_retains_results_and_retries_failed_page_not_page_zero(self):
        state, calls, notes = {}, [], []
        def http(url, payload):
            calls.append(payload['page'])
            if len(calls) in (2, 3):
                raise gateway()
            return dict(count=3, results=[dict(name='A', id64=1), dict(name='B', id64=2)] if payload['page'] == 0 else [dict(name='C', id64=3)])
        args = dict(kind='systems', conditions=[], want=3, max_pages=3, page_size=2, http=http, resume=state)
        for attempt in range(2):
            rows, total, scanned = eng.search(**args, notes=notes)
            self.assertEqual([r['name'] for r in rows], ['A', 'B'])
            self.assertEqual((total, scanned), (3, 2))
            self.assertTrue(state['paused'])
        rows, _, scanned = eng.search(**args)
        self.assertEqual([r['name'] for r in rows], ['A', 'B', 'C'])
        self.assertEqual(scanned, 3)
        self.assertEqual(calls, [0, 1, 1, 1])
        self.assertFalse(state['paused'])

    def test_main_nested_failure_reuses_page_and_never_emits_unverified_rows(self):
        state = {}
        rows = [dict(name='A', id64=1), dict(name='B', id64=2)]
        conditions = [dict(type='rings', mode='present')]
        bodies = {'a': [dict(name='A 1', rings=[dict(type='Icy')])], 'b': [dict(name='B 1', rings=[])]}
        with patch.object(colony, 'load_bodies', side_effect=[gateway(), bodies]), \
                patch.object(eng, '_http_json', return_value=dict(count=2, results=rows)) as http:
            first, _, _ = eng.search('systems', conditions, resume=state)
            self.assertEqual(first, [])
            self.assertTrue(state['paused'])
            second, _, scanned = eng.search('systems', conditions, resume=state)
            self.assertEqual([r['name'] for r in second], ['A'])
            self.assertEqual(scanned, 2)
            http.assert_called_once()

    def test_main_mid_page_retry_keeps_verified_rows_and_rechecks_failed_candidate(self):
        state = {}
        response = dict(results=[dict(name=name, id64=i) for i, name in enumerate(('A', 'B', 'C'))])
        with patch.object(eng, '_http_json', return_value=response) as http:
            from unittest.mock import Mock
            check = Mock(side_effect=[True, gateway(), True, True, True])
            rows, _, _ = eng.search('systems', [], want=3, row_filter=check, resume=state)
            self.assertEqual([r['name'] for r in rows], ['A'])
            self.assertTrue(state['paused'])
            rows, _, scanned = eng.search('systems', [], want=3, row_filter=check, resume=state)
            self.assertEqual([r['name'] for r in rows], ['A', 'B', 'C'])
            self.assertEqual(scanned, 3)
            http.assert_called_once()

    def test_colony_retains_page_results_and_resume_counters(self):
        state, pages = {}, []
        first = [candidate('A'), candidate('B')] + [dict(candidate(f'No {i}'), population=1) for i in range(498)]
        def http(url, payload, **kwargs):
            pages.append(payload['page'])
            if len(pages) == 2:
                raise gateway()
            return dict(count=501, results=copy.deepcopy(first) if payload['page'] == 0 else [candidate('C')])
        with patch.object(eng, '_http_json', side_effect=http):
            info, rows = colony.search(colony.Criteria(), resume=state)
            self.assertFalse(info['complete'])
            self.assertTrue(state['paused'])
            self.assertEqual([r['name'] for r in rows], ['A', 'B'])
            self.assertEqual(info['scanned'], 500)
            info, rows = colony.search(colony.Criteria(), resume=state)
            self.assertTrue(info['complete'])
            self.assertEqual([r['name'] for r in rows], ['A', 'B', 'C'])
            self.assertEqual(info['scanned'], 501)
            self.assertEqual(pages, [0, 1, 1])

    def test_colony_failure_mid_page_preserves_verified_rows_without_duplicates(self):
        state = {}
        c = colony.Criteria(populated_radius=10)
        response = dict(results=[candidate('A'), candidate('B')])
        with patch.object(eng, '_http_json', return_value=response) as http, \
                patch.object(colony, 'populated_neighbour', side_effect=[
                    (True, 'Near', 1, 2), gateway(), (True, 'Near', 1, 2), (True, 'Near', 1, 2)]):
            info, rows = colony.search(c, resume=state)
            self.assertEqual([r['name'] for r in rows], ['A'])
            self.assertTrue(state['paused'])
            info, rows = colony.search(c, resume=state)
            self.assertEqual([r['name'] for r in rows], ['A', 'B'])
            self.assertEqual(info['scanned'], 2)
            self.assertTrue(info['complete'])
            http.assert_called_once()

    def test_first_page_network_failure_validation_and_query_binding(self):
        state = {}
        with patch.object(eng, '_http_json', side_effect=URLError('offline')):
            rows, _, _ = eng.search('systems', [], resume=state)
        self.assertEqual(rows, [])
        self.assertTrue(state['paused'])
        with self.assertRaises(ValueError):
            eng.search('systems', [dict(field='name', op='=', text='different')], resume=state)
        with patch.object(eng, '_http_json', side_effect=ValueError('schema error')):
            with self.assertRaisesRegex(ValueError, 'schema error'):
                eng.search('systems', [], resume={})
        with patch.object(eng, '_http_json', side_effect=HTTPError('url', 403, 'Forbidden', {}, None)):
            with self.assertRaises(HTTPError):
                eng.search('systems', [], resume={})

    def test_cancellation_and_legacy_calls_are_not_changed(self):
        with patch.object(eng, '_http_json', side_effect=gateway()):
            with self.assertRaises(HTTPError):
                eng.search('systems', [])
            with self.assertRaises(HTTPError):
                colony.search(colony.Criteria())
        stop = threading.Event()
        stop.set()
        state = {}
        self.assertEqual(eng.search('systems', [], stop=stop, resume=state)[0], [])
        self.assertTrue(state['paused'])

    def test_stop_immediately_after_continue_does_not_erase_prior_matches(self):
        state = {}
        stop = threading.Event()
        def check(row):
            if row['name'] == 'B':
                raise gateway()
            return True
        with patch.object(eng, '_http_json', return_value=dict(results=[dict(name='A'), dict(name='B')])):
            rows, _, _ = eng.search('systems', [], resume=state, row_filter=check)
        self.assertEqual([r['name'] for r in rows], ['A'])
        stop.set()
        rows, _, _ = eng.search('systems', [], resume=state, row_filter=check, stop=stop)
        self.assertEqual([r['name'] for r in rows], ['A'])
        self.assertTrue(state['paused'])


if __name__ == '__main__':
    unittest.main()
