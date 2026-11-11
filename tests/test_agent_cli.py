"""Tests for the headless agent CLI: protocol, adapters, and process entry."""
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'agent_tools'))
import agent_cli

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')


def request(operation, arguments=None, **extra):
    return dict(interface_version='1', operation=operation,
                arguments=arguments or {}, **extra)


def run(operation, arguments=None, **extra):
    return agent_cli.run_request(request(operation, arguments, **extra))


def fake_search(kind, conditions, *, want, max_pages, stop=None,
                corrections=None, notes=None, **kwargs):
    if corrections is not None:
        corrections.append(('Sol', 'Sol'))
    if notes is not None:
        notes.append('候选分页已取完')
    rows = [dict(name=f'System {i}', population=1000 + i, distance=10.0 + i,
                 nan_field=math.nan) for i in range(want + 3)]
    return rows, 500, 42


class ProtocolTests(unittest.TestCase):
    def test_capabilities_lists_operations_and_limits(self):
        response = run('capabilities')
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(response['interface_version'], '1')
        self.assertEqual(response['application_version'], agent_cli.app_metadata.PROJECT_VERSION)
        names = [item['name'] for item in response['operations']]
        self.assertEqual(len(names), 15)
        self.assertEqual(names, sorted(names))
        self.assertIn('read_current_system', names)
        offline = {item['name'] for item in response['operations'] if not item['network']}
        self.assertIn('capabilities', offline)
        self.assertIn('read_current_system', offline)
        self.assertNotIn('search_pve', offline)
        self.assertEqual(response['limits']['max_return_rows'], 10000)

    def test_describe_returns_schema(self):
        response = run('describe', dict(operation='search_pve'))
        self.assertEqual(response['status'], 'ok')
        self.assertTrue(response['arguments']['reference']['required'])
        self.assertFalse(response['arguments']['prefer_low']['required'])

    def test_describe_unknown_operation(self):
        response = run('describe', dict(operation='nope'))
        self.assertEqual(response['status'], 'error')
        self.assertEqual(response['error']['code'], 'invalid_request')
        self.assertIn('capabilities', response['error']['message'])

    def test_interface_version_must_match(self):
        response = agent_cli.run_request(dict(interface_version='2', operation='capabilities'))
        self.assertEqual(response['error']['code'], 'invalid_request')

    def test_request_must_be_object(self):
        response = agent_cli.run_request([1, 2])
        self.assertEqual(response['error']['code'], 'invalid_request')

    def test_options_lists_groups_and_values(self):
        response = run('options')
        self.assertEqual(response['status'], 'ok')
        self.assertIn('rare_goods_sources', response['groups'])
        self.assertIn('engineer_module_specs', response['groups'])
        one = run('options', dict(group='powerplay_powers'))
        self.assertIn('A. Lavigny-Duval', one['values'])
        self.assertGreaterEqual(len(one['values']), 12)

    def test_options_unknown_group_is_invalid_request(self):
        response = run('options', dict(group='nope'))
        self.assertEqual(response['error']['code'], 'invalid_request')
        self.assertIn('rare_goods_sources', response['error']['message'])

    def test_invalid_limits_do_not_reach_the_search(self):
        for limits in (dict(return_rows=0), dict(return_rows='all'),
                       dict(deadline_seconds=0), dict(deadline_seconds=90000),
                       dict(fields=[]), dict(fields=['name', 3])):
            with self.subTest(limits=limits), \
                    patch('agent_cli.eng.search') as never:
                response = agent_cli.run_request(
                    request('search_systems', dict(conditions=[dict(type='distance',
                                                                    ref_system='Sol', max_ly=10)]),
                            limits=limits))
                self.assertEqual(response['status'], 'error', limits)
                self.assertEqual(response['error']['code'], 'invalid_request', limits)
                never.assert_not_called()

    def test_generic_search_projects_fields_and_truncates(self):
        with patch('agent_cli.eng.normalize_conditions', lambda kind, c: c), \
                patch('agent_cli.eng.search', fake_search):
            response = run('search_systems',
                           dict(conditions=[dict(type='distance', ref_system='Sol', max_ly=10)]),
                           limits=dict(return_rows=3, fields=['name', 'distance']))
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(len(response['results']), 3)
        self.assertEqual(response['results'][0], dict(name='System 0', distance=10.0))
        self.assertTrue(response['coverage']['truncated'])
        self.assertEqual(response['coverage']['server_count'], 500)
        self.assertEqual(response['coverage']['scanned'], 42)
        self.assertTrue(response['coverage']['complete'])
        self.assertEqual(response['kind'], 'systems')

    def test_generic_search_reports_partial_on_page_limit(self):
        def partial_search(kind, conditions, *, notes=None, **kwargs):
            notes.append('达到翻页上限，检索未完成；当前命中数不是全库结果数')
            return [], 0, 0

        with patch('agent_cli.eng.normalize_conditions', lambda kind, c: c), \
                patch('agent_cli.eng.search', partial_search):
            response = run('search_stations',
                           dict(conditions=[dict(type='distance', ref_system='Sol', max_ly=10)]))
        self.assertEqual(response['status'], 'partial')
        self.assertFalse(response['coverage']['complete'])

    def test_generic_search_reports_cancelled_on_stop(self):
        def stopped_search(kind, conditions, *, stop=None, notes=None, **kwargs):
            stop.set()
            notes.append('已手动停止')
            return [], 0, 0

        with patch('agent_cli.eng.normalize_conditions', lambda kind, c: c), \
                patch('agent_cli.eng.search', stopped_search):
            response = run('search_stations',
                           dict(conditions=[dict(type='distance', ref_system='Sol', max_ly=10)]))
        self.assertEqual(response['status'], 'cancelled')
        self.assertIn('verified hits', response['coverage']['reason'])

    def test_non_finite_floats_are_nulled(self):
        with patch('agent_cli.eng.normalize_conditions', lambda kind, c: c), \
                patch('agent_cli.eng.search', fake_search):
            response = run('search_systems',
                           dict(conditions=[dict(type='distance', ref_system='Sol', max_ly=10)]),
                           limits=dict(return_rows=1))
        self.assertIsNone(response['results'][0]['nan_field'])
        json.dumps(response, allow_nan=False)  # must not raise

    def test_invalid_conditions_are_invalid_requests(self):
        for arguments in (dict(), dict(conditions=[]), dict(conditions='distance')):
            with self.subTest(arguments=arguments), \
                    patch('agent_cli.eng.search') as never:
                response = run('search_systems', arguments)
                self.assertEqual(response['error']['code'], 'invalid_request')
                never.assert_not_called()

    def test_deadline_cancels_a_slow_operation(self):
        def slow_read(directory):
            deadline.event.wait(5)
            raise InterruptedError

        deadline = threading.Event()
        started = threading.Event()

        def gated_read(directory):
            started.set()
            deadline.wait(5)
            raise InterruptedError

        def on_timer():
            started.wait(5)
            deadline.set()

        with patch('agent_cli.journal_location.read_current_system', gated_read), \
                patch('agent_cli.journal_location.default_directory', lambda: 'nowhere'):
            timer = threading.Timer(0.2, on_timer)
            timer.start()
            try:
                response = run('read_current_system', limits=dict(deadline_seconds=0.1))
            finally:
                timer.cancel()
                deadline.set()
        self.assertEqual(response['status'], 'cancelled')
        self.assertFalse(response['coverage']['complete'])
        self.assertIn('request_id', response)

    def test_network_failure_is_retryable_operation_failed(self):
        import urllib.error
        with patch('agent_cli.eng.resolve_ref',
                   lambda name: (_ for _ in ()).throw(urllib.error.URLError('down'))):
            response = run('resolve_system', dict(name='Sol'))
        self.assertEqual(response['status'], 'error')
        self.assertEqual(response['error']['code'], 'operation_failed')
        self.assertTrue(response['error']['retryable'])
        self.assertEqual(response['error']['exception_type'], 'URLError')

    def test_resolve_system_returns_coordinates(self):
        with patch('agent_cli.eng.resolve_ref', lambda name: ('Sol', (0.0, 1.0, 2.0), True)):
            response = run('resolve_system', dict(name='sol'))
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(response['system'], 'Sol')
        self.assertEqual(response['coords'], dict(x=0.0, y=1.0, z=2.0))
        self.assertTrue(response['corrected'])
        self.assertIn('warnings', response)

    def test_read_current_system_reports_journal_evidence(self):
        location = SimpleNamespace(system='Sol', timestamp='2026-11-10T17:33:11Z',
                                   filename='Journal.01.log')
        with patch('agent_cli.journal_location.read_current_system',
                   side_effect=lambda directory: location) as reader:
            response = run('read_current_system', dict(directory='D:/Games'))
        reader.assert_called_once_with('D:/Games')
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(response['system'], 'Sol')
        self.assertEqual(response['source'], 'Elite Dangerous Journal')


class SearchAdapterTests(unittest.TestCase):
    def search(self, arguments, **extra):
        with patch('agent_cli.eng.normalize_conditions', lambda kind, c: c), \
                patch('agent_cli.eng.search', fake_search):
            return run('search_systems', arguments, **extra)

    def test_conditions_echoed_in_response(self):
        conditions = [dict(type='distance', ref_system='Sol', min_ly=None, max_ly=10, mode='inside')]
        response = self.search(dict(conditions=conditions))
        self.assertEqual(response['conditions'], conditions)

    def test_notes_and_corrections_surfaced(self):
        response = self.search(dict(conditions=[dict(type='distance', ref_system='Sol', max_ly=10)]))
        self.assertIn('候选分页已取完', response['notes'])


class ToolAdapterTests(unittest.TestCase):
    def test_pve_complete_scan(self):
        info = dict(complete=True, scanned=7, mode='missions', confirmed_res=3,
                    inferred_res=1, hits=2, notes=['ok'], errors=[])
        with patch('agent_cli.pve_tool.search', lambda criteria, stop=None: (info, [dict(source='A')])):
            response = run('search_pve', dict(reference='Sol', radius=30))
        self.assertEqual(response['status'], 'ok')
        self.assertTrue(response['coverage']['complete'])
        self.assertEqual(response['coverage']['confirmed_res'], 3)
        self.assertEqual(response['results'], [dict(source='A')])
        self.assertEqual(response['criteria']['reference'], 'Sol')

    def test_pve_stopped_is_cancelled(self):
        def stopped(criteria, stop=None):
            stop.set()
            return dict(complete=False, scanned=1, mode='missions', notes=[], errors=[]), []

        with patch('agent_cli.pve_tool.search', stopped):
            response = run('search_pve', dict(reference='Sol'))
        self.assertEqual(response['status'], 'cancelled')

    def test_hge_accepts_numeric_option_bounds(self):
        tables = dict(POPULATION_OPTIONS={'不限': None, '最少1万': 10000},
                      FRESHNESS_OPTIONS={'不限': None, '近1天': 24})
        result = dict(rows=[dict(name='X')], total=1, scanned=2, notes=['候选分页已取完'],
                      fetched_at='2026-11-10T00:00:00Z', paused=False, error='', stopped=False)
        captured = {}
        with patch('agent_cli.hge_tool.POPULATION_OPTIONS', tables['POPULATION_OPTIONS']), \
                patch('agent_cli.hge_tool.FRESHNESS_OPTIONS', tables['FRESHNESS_OPTIONS']), \
                patch('agent_cli.hge_tool.search',
                      lambda criteria, stop=None: captured.update(criteria=criteria) or result):
            response = run('search_hge', dict(reference='Sol', radius=50,
                                              population=10000, freshness=24))
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(captured['criteria'].population, '最少1万')
        self.assertEqual(captured['criteria'].freshness, '近1天')

    def test_hge_rejects_unmatched_numeric_option(self):
        with patch('agent_cli.hge_tool.POPULATION_OPTIONS', {'不限': None}), \
                patch('agent_cli.hge_tool.FRESHNESS_OPTIONS', {'不限': None}):
            response = run('search_hge', dict(reference='Sol', radius=50, population=7))
        self.assertEqual(response['error']['code'], 'invalid_request')
        self.assertIn('hge_population_options', response['error']['message'])

    def test_engineer_shopping_builds_purchase_conditions(self):
        criteria = SimpleNamespace(origin='Sol', destination='Farseer — Deciat',
                                   jump_range=20.0, conditions=[], landing_pad='',
                                   pledged_power='', max_extra_jumps=1)
        result = dict(rows=[dict(name='X', _shopping_route=dict(total_jumps=1))],
                      total=1, scanned=3, notes=['候选分页已取完'], stopped=False)
        captured = {}
        with patch('agent_cli.engineer_shopping.build_criteria',
                   lambda *a, **kw: captured.update(args=a, kwargs=kw) or criteria), \
                patch('agent_cli.engineer_shopping.search',
                      lambda criteria, want, max_pages, stop=None:
                      captured.update(want=want) or result):
            response = run('search_engineer_shopping',
                           dict(origin='Sol', destination='Elvira Martuuk — Khun',
                                jump_range=20, purchases=[{'name': 'Frame Shift Drive', 'class': 5}]))
        self.assertEqual(response['status'], 'ok')
        purchases = captured['args'][4]
        self.assertEqual(purchases[0]['field'], 'modules')
        self.assertEqual(purchases[0]['text'], 'Frame Shift Drive')
        self.assertEqual(purchases[0]['class'], ['5'])
        self.assertTrue(purchases[0]['discounted'])
        self.assertEqual(response['results'][0]['_shopping_route']['total_jumps'], 1)

    def test_engineer_shopping_requires_purchases(self):
        response = run('search_engineer_shopping',
                       dict(origin='Sol', destination='Khun', jump_range=20, purchases=[]))
        self.assertEqual(response['error']['code'], 'invalid_request')

    def test_full_outfitting_local_filter_is_complete_but_not_live(self):
        criteria = SimpleNamespace(reference='Sol', radius=100.0)
        result = dict(rows=[dict(name='Jameson Memorial')], notes=['本地筛完'],
                      scanned=5, total=9000, rejected=1, uncertain=0, incomplete=0,
                      condition_failures=0, stopped=False, complete=True, errors=[],
                      criteria=dict(reference='Sol', radius=100.0),
                      catalog_revision='2026.1', snapshot_created_at='2026-11-01T00:00:00Z')
        captured = {}
        with patch('agent_cli.full_outfitting.build_criteria',
                   lambda reference, radius, **options:
                   captured.update(reference=reference, radius=radius, options=options) or criteria), \
                patch('agent_cli.outfitting_snapshot.search',
                      lambda criteria, want, max_pages, stop=None, refresh=False:
                      captured.update(refresh=refresh) or result):
            response = run('search_full_outfitting',
                           dict(reference='Sol', radius=100, require_discount=True))
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(captured['reference'], 'Sol')
        self.assertEqual(captured['options'], dict(require_discount=True))
        self.assertFalse(captured['refresh'])
        self.assertIn('not live stock', response['coverage']['reason'])
        self.assertIn('refresh=true', response['warnings'][0])

    def test_full_outfitting_rejects_non_boolean_options(self):
        response = run('search_full_outfitting',
                       dict(reference='Sol', radius=100, require_discount='yes'))
        self.assertEqual(response['error']['code'], 'invalid_request')

    def test_waypoint_route_complete_pools(self):
        criteria = SimpleNamespace(origin='Sol', destination='Deciat')
        result = dict(route=[dict(name='W1', leg_ly=5.0)], stops=1, total_ly=50.0,
                      direct_ly=40.0, extra_ly=10.0, final_leg_ly=5.0, missing=[],
                      endpoint_requirements=[], origin='Sol', destination='Deciat',
                      notes=['1: 候选分页已取完', '2: 候选分页已取完'], groups=[{}, {}])
        with patch('agent_cli.waypoint_route.Criteria',
                   lambda **kw: SimpleNamespace(validate=lambda: criteria)), \
                patch('agent_cli.waypoint_route.search',
                      lambda criteria, groups, stop=None: result):
            response = run('search_waypoint_route',
                           dict(origin='Sol', destination='Deciat',
                                groups=[dict(kind='stations', conditions=[]),
                                        dict(kind='systems', conditions=[])]))
        self.assertEqual(response['status'], 'ok')
        self.assertTrue(response['coverage']['route_found'])
        self.assertTrue(all(pool['complete'] for pool in response['coverage']['pools']))
        self.assertEqual(response['stops'], 1)
        self.assertIn('not a galaxy-wide optimum', response['coverage']['reason'])

    def test_waypoint_route_no_route_over_complete_pools_is_ok(self):
        criteria = SimpleNamespace(origin='Sol', destination='Deciat')
        result = dict(route=None, direct_ly=40.0, missing=[1], notes=['1: 候选分页已取完'],
                      groups=[{}], origin='Sol', destination='Deciat')
        with patch('agent_cli.waypoint_route.Criteria',
                   lambda **kw: SimpleNamespace(validate=lambda: criteria)), \
                patch('agent_cli.waypoint_route.search',
                      lambda criteria, groups, stop=None: result):
            response = run('search_waypoint_route',
                           dict(origin='Sol', destination='Deciat',
                                groups=[dict(kind='systems', conditions=[])]))
        self.assertEqual(response['status'], 'ok')
        self.assertFalse(response['coverage']['route_found'])
        self.assertIn('No feasible route', response['coverage']['reason'])

    def test_waypoint_route_incomplete_pool_is_partial(self):
        criteria = SimpleNamespace(origin='Sol', destination='Deciat')
        result = dict(route=[dict(name='W1')], stops=1, total_ly=50.0, direct_ly=40.0,
                      extra_ly=10.0, missing=[], notes=['1: 达到翻页上限，检索未完成'],
                      groups=[{}], origin='Sol', destination='Deciat')
        with patch('agent_cli.waypoint_route.Criteria',
                   lambda **kw: SimpleNamespace(validate=lambda: criteria)), \
                patch('agent_cli.waypoint_route.search',
                      lambda criteria, groups, stop=None: result):
            response = run('search_waypoint_route',
                           dict(origin='Sol', destination='Deciat',
                                groups=[dict(kind='systems', conditions=[])]))
        self.assertEqual(response['status'], 'partial')
        self.assertFalse(response['coverage']['complete'])

    def test_waypoint_route_requires_groups(self):
        response = run('search_waypoint_route', dict(origin='Sol', destination='Deciat'))
        self.assertEqual(response['error']['code'], 'invalid_request')

    def test_colonisation_reports_unknown_records(self):
        info = dict(scanned=9, total=1000, complete=True, unknown=2,
                    reason='', value_field='estimated_mapping_value')
        with patch('agent_cli.colonisation_tool.search',
                   lambda criteria, stop=None: (info, [dict(name='Colonia')])):
            response = run('search_colonisation', dict(reference='Sol', radius=500))
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(response['coverage']['unknown'], 2)
        self.assertEqual(response['coverage']['value_field'], 'estimated_mapping_value')

    def test_rare_goods_validates_known_sources(self):
        info = dict(complete=True, scanned=11, unverifiable=0, notes=[], corrections=[])
        groups = {'A. Lavigny-Duval': dict(rows=[dict(name='Station')], status='standard')}
        captured = {}
        with patch('agent_cli.powerplay_tool.search_powerplay',
                   lambda **kw: captured.update(kw) or (info, groups)):
            response = run('search_rare_goods', dict(reference='16 lyrae'))
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(captured['reference'], '16 Lyrae')
        self.assertEqual(captured['power'], 'A. Lavigny-Duval')
        self.assertEqual(response['results'][0]['powerplay_power'], 'A. Lavigny-Duval')
        self.assertEqual(response['results'][0]['group_status'], 'standard')

    def test_rare_goods_unknown_source_needs_opt_in(self):
        info = dict(complete=True, scanned=1, unverifiable=0, notes=[], corrections=[])
        groups = {'A. Lavigny-Duval': dict(rows=[], status='standard')}
        with patch('agent_cli.powerplay_tool.search_powerplay',
                   return_value=(info, groups)) as never:
            response = run('search_rare_goods', dict(reference='Sol'))
            self.assertEqual(response['error']['code'], 'invalid_request')
            self.assertIn('rare_goods_sources', response['error']['message'])
            never.assert_not_called()
            response = run('search_rare_goods', dict(reference='Sol', allow_unknown_source=True))
            self.assertEqual(response['status'], 'ok')
            self.assertEqual(never.call_args.kwargs['reference'], 'Sol')

    def test_rare_goods_rejects_unknown_power(self):
        response = run('search_rare_goods', dict(reference='16 Lyrae', power='Nobody'))
        self.assertEqual(response['error']['code'], 'invalid_request')

    def test_midpoint_reports_geometry(self):
        info = dict(a='Sol', b='Deciat', mid=(1.0, 2.0, 3.0), ab=654.2, complete=True)
        with patch('agent_cli.eng.midpoint_search', lambda *a, **kw: (info, [dict(name='M')])):
            response = run('search_midpoint', dict(system_a='Sol', system_b='Deciat'))
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(response['coverage']['midpoint'], [1.0, 2.0, 3.0])
        self.assertEqual(response['coverage']['ab_ly'], 654.2)


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def write(self, name, text):
        path = os.path.join(self.temp.name, name)
        with open(path, 'w', encoding='utf-8') as file:
            file.write(text)
        return path

    def output(self, argv):
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = agent_cli.main(argv)
        return code, buffer.getvalue()

    def test_main_single_json_envelope_and_exit_zero(self):
        path = self.write('request.json', json.dumps(request('capabilities')))
        code, text = self.output(['--input', path])
        self.assertEqual(code, 0)
        lines = text.strip().splitlines()
        self.assertEqual(len(lines), 1)
        envelope = json.loads(lines[0])
        self.assertEqual(envelope['status'], 'ok')
        self.assertEqual(envelope['operation'], 'capabilities')

    def test_main_invalid_json_exits_one(self):
        path = self.write('bad.json', 'not json')
        code, text = self.output(['--input', path])
        self.assertEqual(code, 1)
        envelope = json.loads(text)
        self.assertEqual(envelope['error']['code'], 'invalid_request')

    def test_main_unknown_operation_exits_one(self):
        path = self.write('request.json', json.dumps(request('nope')))
        code, text = self.output(['--input', path])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(text)['error']['code'], 'unknown_operation')

    def test_main_operation_failed_exits_two(self):
        path = self.write('request.json', json.dumps(request('resolve_system', dict(name='Sol'))))
        with patch('agent_cli.eng.resolve_ref',
                   lambda name: (_ for _ in ()).throw(TimeoutError('slow'))):
            code, text = self.output(['--input', path])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(text)['error']['code'], 'operation_failed')

    def test_main_pretty_prints_indented_json(self):
        path = self.write('request.json', json.dumps(request('capabilities')))
        code, text = self.output(['--input', path, '--pretty'])
        self.assertEqual(code, 0)
        self.assertGreater(text.count('\n'), 5)
        json.loads(text)

    def test_import_does_not_pull_tkinter(self):
        code = ('import sys; sys.path.insert(0, r"%s"); '
                'sys.path.insert(0, r"%s"); import agent_cli; print("tkinter" in sys.modules)' %
                (SRC, os.path.join(SRC, 'agent_tools')))
        result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                                text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'False')


if __name__ == '__main__':
    unittest.main()
