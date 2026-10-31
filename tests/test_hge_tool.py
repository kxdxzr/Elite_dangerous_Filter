import copy
from datetime import datetime, timedelta, timezone
import threading
import unittest
from unittest.mock import patch
from urllib.error import URLError

import filter_engine as eng
import hge_tool as tool


NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


def system(allegiance='Federation', state='Election', **changes):
    row = dict(id64=1, name='Candidate', x=1, y=0, z=0, population=1_000_000,
               controlling_minor_faction='Controller', allegiance='Empire',
               controlling_minor_faction_state='None', updated_at=NOW.isoformat(),
               minor_faction_presences=[dict(name='Controller', allegiance=allegiance, state=state)])
    row.update(changes)
    return row


class HgeToolTests(unittest.TestCase):
    def test_every_user_rule_and_all_materials(self):
        for key, (materials, allegiances, states) in tool.RULES.items():
            for allegiance in allegiances:
                for state in states:
                    with self.subTest(key=key, allegiance=allegiance, state=state):
                        result = tool.candidate(system(allegiance, state), tool.Criteria(material=key), NOW)
                        self.assertEqual(result['materials'], list(materials))
                        self.assertEqual(result['allegiance'], allegiance)
        result = tool.candidate(system('Independent', 'Boom'), tool.Criteria(material='all'), NOW)
        self.assertEqual(result['materials'], ['Proto Heat Radiators', 'Proto Light Alloys', 'Proto Radiolic Alloys'])
        self.assertIsNone(tool.candidate(system('Federation', 'Boom'), tool.Criteria(material='proto_radiolic'), NOW))

    def test_only_named_controller_not_system_or_unrelated_faction(self):
        row = system('Independent', 'Outbreak')
        row['minor_faction_presences'].append(dict(name='Other', allegiance='Federation', state='Election'))
        self.assertIsNone(tool.candidate(row, tool.Criteria(), NOW))
        self.assertIsNotNone(tool.candidate(row, tool.Criteria(material='pharmaceutical'), NOW))
        for change in (dict(controlling_minor_faction=None), dict(minor_faction_presences=[]),
                       dict(minor_faction_presences=None), dict(controlling_minor_faction='Wrong controller')):
            self.assertIsNone(tool.candidate(system(**change), tool.Criteria(), NOW))

    def test_none_requires_positive_evidence_not_missing_or_pending(self):
        for state in (None, '', 'Unknown'):
            row = system(state=state)
            row['minor_faction_presences'][0].update(active_states=[], pending_states=['Election'],
                                                     recovering_states=['Election'])
            self.assertIsNone(tool.candidate(row, tool.Criteria(), NOW))
        self.assertIsNotNone(tool.candidate(system(state='None'), tool.Criteria(), NOW))
        row = system(state='None')
        row['minor_faction_presences'][0]['active_states'] = ['Boom']
        self.assertIsNone(tool.candidate(row, tool.Criteria(), NOW))

    def test_secondary_active_states_and_conflicting_duplicates(self):
        row = system('Alliance', 'Boom')
        row['minor_faction_presences'][0]['active_states'] = [{'name': 'War'}]
        self.assertIsNotNone(tool.candidate(row, tool.Criteria(material='military'), NOW))
        duplicate = copy.deepcopy(row['minor_faction_presences'][0])
        row['minor_faction_presences'].append(duplicate)
        self.assertIsNotNone(tool.candidate(row, tool.Criteria(material='military'), NOW))
        duplicate['allegiance'] = 'Federation'
        self.assertIsNone(tool.candidate(row, tool.Criteria(material='military'), NOW))
        self.assertIsNone(tool.current_states({'state': 'None', 'active_states': 'bad'}))

    def test_age_boundaries_unknown_future_and_timezone(self):
        criteria = tool.Criteria(freshness='近 1 小时')
        self.assertIsNotNone(tool.candidate(system(updated_at=(NOW - timedelta(hours=1)).isoformat()), criteria, NOW))
        for stamp in (None, 'bad', (NOW - timedelta(hours=1, seconds=1)).isoformat(),
                      (NOW + timedelta(seconds=1)).isoformat()):
            self.assertIsNone(tool.candidate(system(updated_at=stamp), criteria, NOW))
        self.assertIsNotNone(tool.candidate(system(updated_at=None), tool.Criteria(freshness='不限'), NOW))
        self.assertEqual(tool.timestamp('2026-10-31T13:00:00+01:00'), NOW)

    def test_population_thresholds_and_unknown(self):
        criteria = tool.Criteria(population='至少 100 万')
        self.assertIsNotNone(tool.candidate(system(population=1_000_000), criteria, NOW))
        for value in (999_999, None, True, '1000000', float('inf'), -1):
            self.assertIsNone(tool.candidate(system(population=value), criteria, NOW))
        self.assertIsNone(tool.candidate(system(population=0), tool.Criteria(), NOW))
        self.assertIsNotNone(tool.candidate(system(population=None), tool.Criteria(population='不限'), NOW))

    def test_validation_before_network(self):
        with patch.object(eng, 'search') as search:
            for changes in (dict(reference=''), dict(radius=0), dict(radius=float('nan')),
                            dict(material='unknown'), dict(population='bad'), dict(freshness='bad'),
                            dict(want=0), dict(want=True), dict(max_pages=-1),
                            dict(require_manufactured_trader='yes')):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    tool.search(tool.Criteria(**changes))
            search.assert_not_called()

    def test_optional_manufactured_trader_checks_same_system_before_limit(self):
        systems = [system('Empire', name='Not HGE', id64=10), system(name='No trader', id64=11),
                   system(name='Target', id64=12), system(name='Unneeded', id64=13)]
        calls = []
        def http(url, payload, **kwargs):
            calls.append((url, payload))
            if url.endswith('/systems/search'):
                return dict(count=4, results=copy.deepcopy(systems))
            name = payload['filters']['system_name']['value'][0]
            self.assertEqual(payload['filters']['material_trader']['value'], ['Manufactured'])
            if name == 'No trader':
                return dict(results=[dict(name='Raw trader', system_name=name, material_trader='Raw'),
                                     dict(name='Encoded trader', system_name=name, material_trader='Encoded'),
                                     dict(name='Unknown', system_name=name),
                                     dict(name='Neighbour', system_name='Other', material_trader='Manufactured')])
            self.assertEqual(name, 'Target')
            return dict(results=[dict(name='Trade Port', system_name=name, system_id64=12,
                                       material_trader='Manufactured', updated_at=NOW.isoformat())])
        with patch.object(eng, 'resolve_ref', return_value=('Sol', (0, 0, 0), 0)), \
                patch.object(eng, '_http_json', side_effect=http):
            result = tool.search(tool.Criteria(want=1, require_manufactured_trader=True), now=NOW)
        self.assertEqual([r['name'] for r in result['rows']], ['Target'])
        self.assertEqual(result['rows'][0]['_hge']['manufactured_trader']['name'], 'Trade Port')
        self.assertEqual(len(calls), 3)
        # Disabled is backward-compatible and must not make station requests.
        with patch.object(eng, 'resolve_ref', return_value=('Sol', (0, 0, 0), 0)), \
                patch.object(eng, '_http_json', return_value=dict(results=[system()], count=1)) as http:
            result = tool.search(tool.Criteria(want=1), now=NOW)
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(http.call_count, 1)

    def test_trader_pagination_identity_unknown_and_cancellation(self):
        row = system()
        wrong = dict(id=1, name='Wrong identity', system_name='Candidate', system_id64=999,
                     material_trader='Manufactured')
        good = dict(id=2, name='Trade Port', system_name='Candidate', system_id64=1,
                    material_trader='Manufactured')
        with patch.object(eng, '_http_json', side_effect=[dict(results=[wrong]), dict(results=[good])]) as http:
            result = tool.find_manufactured_trader(row, page_size=1)
        self.assertEqual(result['name'], 'Trade Port')
        self.assertEqual(http.call_count, 2)
        for response in (dict(results='bad'), dict(results=[wrong])):
            with patch.object(eng, '_http_json', return_value=response), self.assertRaises(ValueError):
                tool.find_manufactured_trader(row, page_size=1, max_pages=1)
        with patch.object(eng, '_http_json', return_value=dict(results=[wrong])), self.assertRaises(ValueError):
            tool.find_manufactured_trader(row, page_size=1, max_pages=3)
        stop = threading.Event()
        def stopped(*args, **kwargs):
            stop.set()
            return dict(results=[good])
        with patch.object(eng, '_http_json', side_effect=stopped), self.assertRaises(InterruptedError):
            tool.find_manufactured_trader(row, stop=stop)

    def test_trader_failure_retains_verified_rows_and_incomplete_evidence_is_not_a_hit(self):
        rows = [system(name='First', id64=1), system(name='Second', id64=2)]
        good = dict(name='Trade Port', system_name='First', material_trader='Manufactured')
        with patch.object(eng, 'resolve_ref', return_value=('Sol', (0, 0, 0), 0)), \
                patch.object(eng, '_http_json', side_effect=[dict(results=rows, count=2), dict(results=[good]), URLError('offline')]):
            result = tool.search(tool.Criteria(want=2, require_manufactured_trader=True), now=NOW)
        self.assertEqual([r['name'] for r in result['rows']], ['First'])
        self.assertTrue(result['paused'])
        with patch.object(eng, 'resolve_ref', return_value=('Sol', (0, 0, 0), 0)), \
                patch.object(eng, '_http_json', side_effect=[dict(results=[system()], count=1), dict(results='bad')]):
            result = tool.search(tool.Criteria(require_manufactured_trader=True), now=NOW)
        self.assertEqual(result['rows'], [])
        self.assertIn('部分候选的人造材料商人资料无法核实，未计入结果', result['notes'])

    def test_real_engine_rejects_before_limit_and_requeries_every_run(self):
        response = dict(count=3, results=[system('Empire', 'Election', id64=2, name='Wrong'),
                                           system(name='Good'), system(id64=3, name='Duplicate')])
        with patch.object(eng, 'resolve_ref', return_value=('Sol', (0, 0, 0), 0)), \
                patch.object(eng, '_http_json', side_effect=lambda *a: copy.deepcopy(response)) as http:
            result = tool.search(tool.Criteria(want=1), now=NOW)
            again = tool.search(tool.Criteria(want=1), now=NOW)
        self.assertEqual([r['name'] for r in result['rows']], ['Good'])
        self.assertEqual(http.call_count, 2)
        self.assertEqual(again['rows'][0]['_hge']['controller'], 'Controller')
        filters = http.call_args.args[1]['filters']
        self.assertIn('population', filters)
        self.assertNotIn('updated_at', filters)  # Shared engine verifies timestamps locally.
        self.assertNotIn('allegiance', filters)
        self.assertNotIn('controlling_minor_faction_state', filters)
        self.assertNotIn('_hge', response['results'][1])

    def test_network_error_and_stop_retain_only_verified_results(self):
        rows = [system(id64=i, name=f'Candidate {i}', state='Election' if i == 0 else 'Boom') for i in range(500)]
        with patch.object(eng, 'resolve_ref', return_value=('Sol', (0, 0, 0), 0)), \
                patch.object(eng, '_http_json', side_effect=[dict(count=501, results=rows), URLError('offline')]):
            result = tool.search(tool.Criteria(want=2), now=NOW)
        self.assertEqual([r['name'] for r in result['rows']], ['Candidate 0'])
        self.assertTrue(result['paused'])
        self.assertIn('offline', result['error'])
        stop = threading.Event()
        stop.set()
        with patch.object(eng, '_http_json') as http:
            result = tool.search(tool.Criteria(), stop=stop, now=NOW)
            self.assertTrue(result['stopped'])
            self.assertEqual(result['rows'], [])
            http.assert_not_called()
