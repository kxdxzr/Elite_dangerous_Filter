from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

import full_outfitting as tool


def fixture():
    items = [dict(name='Shield Booster', ed_symbol='booster', **{'class': 0, 'rating': 'A'}),
             dict(name='Cargo Rack', ed_symbol='cargo', **{'class': 1, 'rating': 'E'})]
    catalog = dict(items=deepcopy(items), ships=[], armours=[], issues=[])
    row = dict(id=1, name='Port', system_name='System', type='Coriolis Starport',
               modules=deepcopy(items), distance=10, distance_to_arrival=100,
               technology_broker='None', services=[], outfitting_updated_at='stock-time')
    return catalog, row


class OutfittingStockFirstTests(unittest.TestCase):
    def setUp(self):
        self.catalog, self.row = fixture()
        self.criteria = tool.build_criteria('Sol', 100, require_discount=True)

    def search(self, rows, http, criteria=None):
        def candidates(kind, conditions, **kwargs):
            hits = []
            for raw in rows:
                row = deepcopy(raw)
                if kwargs['row_filter'](row):
                    hits.append(row)
                    if len(hits) >= kwargs['want']:
                        break
            kwargs['notes'].append('候选分页已取完')
            return hits, len(rows), len(rows)
        with patch.object(tool.eng, 'search', side_effect=candidates), \
                patch.object(tool, 'request_json', side_effect=http):
            return tool.search(criteria or self.criteria, catalog=self.catalog)

    def test_known_missing_stock_skips_power_and_preserves_later_hit(self):
        rows = [dict(self.row, id=i, name=f'Port{i}', system_name=f'System{i}',
                     modules=self.row['modules'][:1] if i < 9 else self.row['modules']) for i in range(10)]
        def http(url, payload, **kwargs):
            self.assertIn('/systems/', url)
            self.assertEqual(payload['filters']['name']['value'], 'System9')
            return dict(results=[dict(name='System9', controlling_power='Li Yong-Rui',
                                      power_state='Fortified', needs_permit=False)])
        request = Mock(side_effect=http)
        before = deepcopy(rows)
        result = self.search(rows, request)
        self.assertEqual(request.call_count, 1)
        self.assertEqual([r['name'] for r in result['rows']], ['Port9'])
        self.assertEqual(result['incomplete'], 9)
        self.assertEqual(result['rows'][0]['_full_outfitting']['discount_min'], 15)
        self.assertEqual(rows, before)

    def test_stock_preflight_is_never_a_final_hit_and_does_not_price_items(self):
        with patch.object(tool, 'discount_info', side_effect=AssertionError('Not a pricing pass')):
            evidence = tool.check_station(self.row, self.criteria, self.catalog, stock_only=True)
        self.assertEqual(evidence['present'], 2)
        self.assertEqual(evidence['missing'], [])
        self.assertEqual(evidence['problems'], [])
        self.assertFalse(evidence['matched'])

    def test_matching_stock_does_not_bypass_unknown_or_wrong_discount(self):
        for response in ({}, dict(name='System', controlling_power='Other', power_state='Fortified'),
                         dict(name='System', controlling_power='Li Yong-Rui', power_state='Exploited')):
            with self.subTest(response=response):
                result = self.search([self.row], lambda *a, **kw: dict(results=[response]))
                self.assertEqual(result['rows'], [])

    def test_case_insensitive_system_context_shared_with_metadata(self):
        rows = [dict(self.row, id=i, name=f'Port{i}', system_name=name)
                for i, name in enumerate(('System', 'SYSTEM', ' system '))]
        http = Mock(return_value=dict(results=[dict(name='System', controlling_power='Li Yong-Rui',
                                                   power_state='Stronghold', needs_permit=False)]))
        result = self.search(rows, http)
        self.assertEqual(len(result['rows']), 3)
        self.assertEqual(http.call_count, 1)
        self.assertTrue(all(row['needs_permit'] is False for row in result['rows']))

    def test_failed_or_empty_context_is_not_retried_per_station(self):
        for http in (Mock(side_effect=TimeoutError('offline')), Mock(return_value=dict(results=[]))):
            with self.subTest(http=http):
                result = self.search([self.row, dict(self.row, id=2, name='Another')], http)
                self.assertEqual(result['rows'], [])
                self.assertEqual(http.call_count, 1)

    def test_context_failure_cache_is_query_local(self):
        http = Mock(side_effect=TimeoutError('offline'))
        self.search([self.row, dict(self.row, id=2)], http)
        self.search([self.row, dict(self.row, id=2)], http)
        self.assertEqual(http.call_count, 2)

    def test_known_discount_uses_existing_cheap_check_without_stock_preflight(self):
        row = dict(self.row, system_controlling_power='Other', system_power_state='Exploited')
        with patch.object(tool, 'check_station', wraps=tool.check_station) as check:
            http = Mock(side_effect=AssertionError('No background request needed'))
            result = self.search([row], http)
        self.assertEqual(result['rows'], [])
        self.assertEqual(check.call_count, 1)
        self.assertFalse(check.call_args.kwargs.get('stock_only', False))

    def test_context_preserves_punctuation_and_rejects_conflicting_id64(self):
        cache, calls = {}, []
        def http(url, payload):
            name = payload['filters']['name']['value']
            calls.append(name)
            return dict(results=[dict(name=name, id64=10, controlling_power='Li Yong-Rui')])
        self.assertTrue(tool.system_context(dict(system_name='A-B', system_id64=10), http, cache))
        self.assertTrue(tool.system_context(dict(system_name='AB', system_id64=10), http, cache))
        self.assertEqual(tool.system_context(dict(system_name='A-B', system_id64=11), http, cache), {})
        self.assertEqual(len(calls), 3)

    def test_ambiguous_stock_is_not_treated_as_definitely_missing(self):
        self.catalog['module_facts'] = {'enabled': True}
        unknown = dict(matched=False, unknown=['unresolved identity'], missing=[], problems=[], no_discount=[])
        complete = dict(matched=True, unknown=[], missing=[], problems=[], no_discount=[])
        calls = []
        def check(row, criteria, catalog, **kwargs):
            calls.append('stock' if kwargs.get('stock_only') else 'full')
            return deepcopy(complete if row.get('_edsm_modules') else unknown)
        with patch.object(tool.catalogue, 'prepare', side_effect=lambda catalog: catalog), \
                patch.object(tool, 'check_station', side_effect=check), \
                patch.object(tool.identity, 'edsm_stock', return_value=[dict(fdev_id=1)]) as second, \
                patch.object(tool, 'complete_result_metadata'):
            result = self.search([self.row], lambda *a, **kw: dict(results=[dict(
                name='System', controlling_power='Li Yong-Rui', power_state='Fortified')]))
        self.assertEqual(len(result['rows']), 1)
        second.assert_called_once()
        self.assertEqual(calls[0], 'stock')

    def test_real_ambiguous_identity_can_still_be_resolved_after_power_lookup(self):
        base = dict(ed_id=128049456, ed_symbol='Hpt_MultiCannon_Fixed_Medium',
                    name='Multi-Cannon', category='hardpoint', **{'class': 2, 'rating': 'E'})
        special = dict(base, ed_id=129045433, category='mercgear', name='Rapid Phase Multi-Cannon')
        self.catalog = dict(items=[base], special_items=[special], module_facts=[base, special],
                            issues=[], ships=[], armours=[], special_issues=[])
        raw = {key: value for key, value in special.items() if key != 'ed_id'}
        row = dict(self.row, market_id=123, modules=[raw])
        calls = []
        def http(url, payload=None, **kwargs):
            if '/systems/' in url:
                calls.append('power')
                return dict(results=[dict(name='System', controlling_power='Li Yong-Rui', power_state='Fortified')])
            self.assertIn('edsm.net', url)
            calls.append('edsm')
            return dict(marketId=123, name='System', sName='Port', outfitting=[dict(
                id=base['ed_symbol'], name='2E Multi-Cannon (Fixed)')])
        result = self.search([row], http)
        self.assertEqual(calls, ['power', 'edsm'])
        self.assertEqual(len(result['rows']), 1)
        evidence = result['rows'][0]['_full_outfitting']
        self.assertTrue(evidence['matched'])
        self.assertEqual(evidence['unknown'], [])
        self.assertEqual(evidence['discount_min'], 15)
