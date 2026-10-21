import copy
import threading
import unittest
import urllib.error
from unittest.mock import patch

import full_outfitting as tool
import outfitting_catalog as catalog
import filter_engine as engine


class FullOutfittingTests(unittest.TestCase):
    def setUp(self):
        network = patch.object(engine, '_http_json', return_value=dict(results=[]))
        network.start()
        self.addCleanup(network.stop)
        self.items = [dict(name='Beam Laser', ed_symbol=f'beam_{mount}',
                           **{'class': 1, 'rating': 'E'}, category='hardpoint', weapon_mode=mount)
                      for mount in ('Fixed', 'Gimballed', 'Turreted')]
        self.items.append(dict(name='Prismatic Shield Generator', ed_symbol='prismatic',
                               **{'class': 2, 'rating': 'A'}))
        self.catalog = dict(items=copy.deepcopy(self.items), ships=['Sidewinder', 'Alliance Chieftain',
                            'Federal Corvette', 'Imperial Cutter'], armours=[], issues=[])
        self.row = dict(name='Discount station', system_name='Test', type='Coriolis Starport',
                        modules=copy.deepcopy(self.items), system_controlling_power='Li Yong-Rui',
                        system_power_state='Fortified')
        self.criteria = tool.build_criteria('Sol', 100, require_discount=True)

    def check(self, **options):
        options.setdefault('require_discount', True)
        return tool.check_station(self.row, tool.build_criteria('Sol', 100, **options), self.catalog)

    def test_ax_equipment_is_optional_without_excluding_mining_equipment(self):
        ax = [dict(name=name, ed_symbol=f'ax_{index}', **{'class': 2, 'rating': 'B'})
              for index, name in enumerate(sorted(catalog.AX_EQUIPMENT))]
        scanner = dict(name='Sub-Surface Displacement Missile', ed_symbol='mining_displacement', **{'class': 2, 'rating': 'B'})
        data = dict(self.catalog, items=[*self.items, scanner, *ax])
        row = dict(self.row, modules=[*self.row['modules'], scanner])
        criteria = tool.build_criteria('Sol', 100)
        before = copy.deepcopy(data)
        result = tool.check_station(row, criteria, data)
        self.assertTrue(result['matched'])
        self.assertEqual(result['required'], len(self.items) + 1)
        self.assertEqual(data, before)
        enabled = tool.build_criteria('Sol', 100, ax_weapons=True)
        self.assertEqual(len(tool.check_station(row, enabled, data)['missing']), len(catalog.AX_EQUIPMENT))
        row['modules'] = [*row['modules'], *ax]
        self.assertTrue(tool.check_station(row, enabled, data)['matched'])
        row['modules'] = [item for item in row['modules'] if item is not scanner]
        self.assertFalse(tool.check_station(row, criteria, data)['matched'])

    def test_enabled_ax_requirement_fails_closed_on_missing_catalogue_family(self):
        evidence = tool.check_station(self.row, tool.build_criteria('Sol', 100, ax_weapons=True), self.catalog)
        self.assertFalse(evidence['matched'])
        self.assertIn('AX装备目录不完整，无法确认齐全', evidence['problems'])

    def test_free_hangars_not_required_but_paid_hangars_and_other_free_items_are(self):
        paid = dict(name='Vessel Hangar', ed_symbol='int_fighterbay_size5_class1',
                    **{'class': 5, 'rating': 'D'})
        free = [dict(paid, ed_symbol=sym) for sym in (
            'int_fighterbay_size5_class1_free', 'int_fighterbaymk2_size5_class1_free',
            'int_largebuggybay_size2_class3_free', 'int_mkiilargebuggybay_size2_class3_free')]
        other = dict(name='Cargo Rack', ed_symbol='int_cargorack_size2_class1_free',
                     **{'class': 2, 'rating': 'E'})
        data = dict(self.catalog, items=[*self.items, paid, other, *free])
        row = dict(self.row, modules=[*self.items, paid, other])
        evidence = tool.check_station(row, self.criteria, data)
        self.assertTrue(evidence['matched'])
        self.assertEqual(evidence['required'], len(self.items) + 2)
        row['modules'] = self.items
        evidence = tool.check_station(row, self.criteria, data)
        self.assertEqual(len(evidence['missing']), 2)

    def test_mkii_vessel_and_large_vehicle_hangars_excluded_but_standard_hangars_remain(self):
        hangars = [dict(name=name, ed_symbol=sym, **{'class': 5, 'rating': 'D'}) for name, sym in (
            ('Mk II Vessel Hangar', 'int_fighterbaymk2_size5_class1'),
            ('Vessel Hangar', 'int_fighterbay_size5_class1'),
            ('Planetary Vehicle Hangar', 'int_buggybay_size2_class1'),
            ('Large Planetary Vehicle Hangar', 'int_largebuggybay_size2_class3'),
            ('Mk II Large Planetary Vehicle Hangar', 'int_mkiilargebuggybay_size2_class3'))]
        data = dict(self.catalog, items=[*self.items, *hangars])
        row = dict(self.row, modules=[*self.items, *hangars[1:]])
        evidence = tool.check_station(row, self.criteria, data)
        self.assertTrue(evidence['matched'])
        self.assertEqual(evidence['required'], len(self.items) + 2)
        row['modules'] = self.items
        self.assertEqual(len(tool.check_station(row, self.criteria, data)['missing']), 2)

    def test_universal_controllers_optional_and_both_variants_required_when_enabled(self):
        universal = [dict(name='Universal Multi Limpet Controller',
                          ed_symbol=f'int_multidronecontrol_universal_size7_class{index}',
                          **{'class': 7, 'rating': rating}) for index, rating in ((3, 'C'), (5, 'A'))]
        other = dict(name='Collector Limpet Controller', ed_symbol='int_dronecontrol_collection_size3_class5',
                     **{'class': 3, 'rating': 'A'})
        data = dict(self.catalog, items=[*self.items, other, *universal])
        row = dict(self.row, modules=[*self.items, other])
        off = tool.build_criteria('Sol', 500)
        on = tool.build_criteria('Sol', 500, universal_limpets=True)
        self.assertTrue(tool.check_station(row, off, data)['matched'])
        self.assertEqual(len(tool.check_station(row, on, data)['missing']), 2)
        row['modules'].append(universal[0])
        self.assertEqual(len(tool.check_station(row, on, data)['missing']), 1)
        row['modules'].append(universal[1])
        self.assertTrue(tool.check_station(row, on, data)['matched'])
        row['modules'] = self.items
        self.assertFalse(tool.check_station(row, off, data)['matched'])
        broken = dict(data, items=[*self.items, universal[0]])
        self.assertIn('通用无人机控制器目录不完整，无法确认齐全',
                      tool.check_station(row, on, broken)['problems'])

    def test_brestla_markup_is_explicit_and_never_a_discount(self):
        row = dict(self.row, name='i Sola Prospect', system_name='Brestla')
        criteria = tool.build_criteria('Sol', 500)
        evidence = tool.check_station(row, criteria, self.catalog)
        self.assertTrue(evidence['matched'])
        self.assertEqual(evidence['surcharge'], 20)
        self.assertIsNone(evidence['discount_min'])
        self.assertEqual(evidence['discount_covered'], 0)
        headers, records = tool.export_table(dict(rows=[dict(row, _full_outfitting=evidence)], criteria=vars(criteria)))
        self.assertEqual(records[0][headers.index('公共折扣')], '公共加价 20%')
        self.assertEqual(records[0][headers.index('已知优惠范围')], '全配件公共加价')
        self.assertFalse(tool.check_station(row, self.criteria, self.catalog)['matched'])
        other = dict(row, name='Other Station')
        self.assertIsNone(tool.check_station(other, criteria, self.catalog)['surcharge'])

    def test_result_metadata_backfills_permit_even_for_named_discount_station(self):
        row = dict(self.row, name='Jameson Memorial', system_name='Shinrarta Dezhra', market_id=123,
                   distance_to_arrival=0, outfitting_updated_at='original-time')
        def http(url, payload):
            if '/systems/' in url:
                return dict(results=[dict(name='Shinrarta Dezhra', needs_permit=True)])
            return dict(results=[dict(name='Jameson Memorial', system_name='Shinrarta Dezhra',
                                     market_id=123, distance=64.4, distance_to_arrival=328,
                                     technology_broker='Guardian', outfitting_updated_at='new-time')])
        tool.complete_result_metadata(row, self.criteria, http)
        self.assertIs(row['needs_permit'], True)
        self.assertEqual(row['technology_broker'], 'Guardian')
        self.assertEqual(row['distance'], 64.4)
        self.assertEqual(row['distance_to_arrival'], 0)
        self.assertEqual(row['outfitting_updated_at'], 'original-time')
        row['_full_outfitting'] = tool.check_station(row, tool.build_criteria('Sol', 500, other_discounts=True), self.catalog)
        headers, records = tool.export_table(dict(rows=[row]))
        self.assertEqual(records[0][headers.index('许可')], '需许可')

    def test_metadata_does_not_merge_wrong_market_or_false_values_or_re_date_stock(self):
        row = dict(self.row, market_id=123, needs_permit=False)
        before = copy.deepcopy(row['modules'])
        def http(url, payload):
            if '/systems/' in url:
                return dict(results=[dict(name='Other', needs_permit=True)])
            return dict(results=[dict(name=row['name'], system_name=row['system_name'],
                                     market_id=124, technology_broker='Guardian', modules=before,
                                     outfitting_updated_at='wrong-market-time')])
        tool.complete_result_metadata(row, self.criteria, http)
        self.assertIs(row['needs_permit'], False)
        self.assertNotIn('technology_broker', row)
        self.assertNotIn('outfitting_updated_at', row)
        self.assertEqual(row['modules'], before)

    def test_metadata_lookup_failure_keeps_inventory_and_records_diagnostic(self):
        row = copy.deepcopy(self.row)
        notes = []
        def fail(*args):
            raise TimeoutError('offline')
        tool.complete_result_metadata(row, self.criteria, fail, notes=notes)
        self.assertTrue(tool.check_station(row, self.criteria, self.catalog)['matched'])
        self.assertEqual(len(notes), 2)

    def test_all_variants_same_station_and_no_inputs_modified(self):
        before = copy.deepcopy((self.row, self.catalog))
        result = self.check()
        self.assertTrue(result['matched'])
        self.assertEqual(result['discount_min'], 15)
        self.assertEqual((self.row, self.catalog), before)
        self.row['modules'].pop(1)
        self.assertFalse(self.check()['matched'])
        self.assertEqual(len(self.check()['missing']), 1)

    def test_different_names_may_share_symbol_without_becoming_same_product(self):
        self.row['modules'][0]['name'] = 'Overloaded Beam Laser'
        evidence = self.check()
        self.assertFalse(evidence['matched'])
        self.assertEqual(len(evidence['unknown']), 1)
        self.assertEqual(evidence['missing'], [])
        self.assertNotEqual(catalog.variant(self.row['modules'][0]), catalog.variant(self.items[0]))

    def test_wrong_rating_cannot_satisfy_symbol_and_no_cartesian_products(self):
        self.row['modules'][0]['rating'] = 'A'
        self.assertFalse(self.check()['matched'])
        self.assertEqual(self.check()['present'], 3)
        self.assertEqual(len(self.check()['unknown']), 1)

    def test_proven_hangar_alias_is_one_requirement_not_two(self):
        first = dict(name='Fighter Hangar', ed_symbol='hangar5', **{'class': 5, 'rating': 'D'})
        alias = dict(first, name='Vessel Hangar')
        prepared = catalog.prepare(dict(items=[first, alias], issues=[], ships=[], armours=[]))
        self.assertEqual(len(prepared['items']), 1)
        row = dict(self.row, modules=[alias])
        self.assertTrue(tool.check_station(row, self.criteria, prepared)['matched'])

    def test_power_rename_never_satisfies_both_base_and_power_requirements(self):
        base = dict(name='Multi-Cannon', ed_symbol='multicannon', **{'class': 2, 'rating': 'E'})
        power = dict(base, name='Enforcer Cannon')
        prepared = catalog.prepare(dict(items=[base, power], issues=[], ships=[], armours=[]))
        evidence = tool.check_station(dict(self.row, modules=[power]), self.criteria, prepared)
        self.assertFalse(evidence['matched'])
        self.assertEqual(evidence['missing'], [])
        self.assertEqual(evidence['present'], 1)
        self.assertEqual(len(evidence['unknown']), 1)
        self.assertEqual(len(prepared['conflicts']), 1)

    def test_carriers_never_qualify_even_with_all_stock_and_lyr(self):
        for kind in ('Drake-Class Carrier', 'Stronghold Carrier', 'Fleet Carrier', ''):
            self.row['type'] = kind
            self.assertFalse(self.check(other_discounts=True)['matched'])
        # Live Spansh observations can even label this as Planetary Outpost.
        for kind in ('Mega ship', 'Planetary Outpost'):
            self.row.update(type=kind, name='Stronghold Carrier')
            self.assertFalse(self.check(other_discounts=True)['matched'])

    def test_power_state_public_policy_and_jameson_opt_in(self):
        self.row['system_power_state'] = 'Exploited'
        self.assertFalse(self.check()['matched'])
        self.row.update(system_name='Shinrarta Dezhra', name='Jameson Memorial')
        self.assertFalse(self.check()['matched'])
        self.assertTrue(self.check(other_discounts=True)['matched'])
        self.assertEqual(self.check(other_discounts=True)['discount_min'], 10)

    def test_personal_weapon_bonus_never_counts_as_all_module_discount(self):
        self.row.update(system_controlling_power='Denton Patreus')
        self.assertFalse(self.check(other_discounts=True)['matched'])

    def test_guardian_requires_explicit_type_not_generic_service(self):
        self.row['services'] = ['Technology Broker']
        self.assertFalse(self.check(guardian=True)['matched'])
        self.row['technology_broker'] = 'Human'
        self.assertFalse(self.check(guardian=True)['matched'])
        self.row['technology_broker'] = 'Guardian'
        self.assertTrue(self.check(guardian=True)['matched'])

    def test_ships_are_optional_alliance_is_neutral_armour_follows_selection(self):
        self.assertTrue(self.check()['matched'])
        self.assertEqual(tool.ship_group('Alliance Chieftain'), 'neutral_ships')
        self.assertEqual(tool.ship_group('Corsair'), 'imperial_ships')
        self.assertFalse(self.check(federal_ships=True)['matched'])
        self.row['ships'] = [dict(name='Federal Corvette')]
        for index, name in enumerate(sorted(catalog.ARMOURS)):
            item = dict(name=name, ed_symbol=f'Corvette_armour_{index}', ship='Federal Corvette',
                        **{'class': 1, 'rating': 'I'})
            self.catalog['armours'].append(item)
            self.row['modules'].append(copy.deepcopy(item))
        self.assertTrue(self.check(federal_ships=True)['matched'])
        self.assertFalse(self.check(federal_ships=True, imperial_ships=True)['matched'])
        self.row['modules'][-1]['ship'] = 'Imperial Cutter'
        self.assertFalse(self.check(federal_ships=True)['matched'])

    def test_no_stock_or_catalogue_never_means_complete(self):
        self.catalog['issues'] = [('missing', 1, 'A')]
        self.assertFalse(self.check()['matched'])
        self.catalog['issues'] = []
        self.row['modules'] = None
        self.assertFalse(self.check()['matched'])

    def test_new_ship_can_have_mkii_armour_instead_of_nonexistent_old_family(self):
        self.catalog['ships'] = ['Caspian Explorer']
        self.row['ships'] = [dict(name='Caspian Explorer')]
        for index, name in enumerate(sorted(catalog.MKII_ARMOURS)):
            item = dict(name=name, ship='Caspian Explorer', ed_symbol=f'caspian_armour_{index}',
                        **{'class': 1, 'rating': 'A'})
            self.catalog['armours'].append(item)
            self.row['modules'].append(copy.deepcopy(item))
        self.assertTrue(self.check(neutral_ships=True)['matched'])

    def test_validation_and_cancellation_before_network(self):
        for radius in ('nan', 'inf', -1, 0):
            with self.assertRaises(ValueError):
                tool.build_criteria('Sol', radius)
        stop = threading.Event()
        stop.set()
        with patch.object(catalog, 'load') as load:
            result = tool.search(self.criteria, stop=stop)
        load.assert_not_called()
        self.assertTrue(result['stopped'])

    def test_context_preserves_per_station_stock_sources_without_repeating_query_columns(self):
        result = dict(rows=[
            dict(system_name='Sol', name='Station A', _stock_sources=['Spansh']),
            dict(system_name='Achenar', name='Station B', _stock_sources=['Spansh', 'EDSM']),
        ], criteria=vars(tool.build_criteria('Sol', 500)), identity_revision='identity-test',
            catalog_revision='catalog-test', partial=True)
        before = copy.deepcopy(result)
        fields = tool.export_context(result)
        self.assertNotIn('购买资格假设', dict(fields))
        self.assertEqual(dict(fields)['物品ID目录版本'], 'identity-test')
        sources = [value for label, value in fields if label == '库存核验来源']
        self.assertEqual(len(sources), 2)
        self.assertIn('Spansh: Sol / Station A', sources)
        self.assertTrue(any('EDSM' in value and 'Achenar / Station B' in value for value in sources))
        headers = {label for _, label in tool.COLUMNS}
        self.assertFalse(headers & {label for label, _ in fields})
        self.assertEqual(result, before)

    def test_common_stock_source_is_written_once_in_context(self):
        fields = tool.export_context(dict(rows=[dict(name='A'), dict(name='B')]))
        self.assertEqual([value for label, value in fields if label == '库存核验来源'], ['Spansh'])

    def test_csv_conditions_include_query_limits_and_all_optional_requirements(self):
        criteria = tool.build_criteria('Sol', 500, ax_weapons=True, universal_limpets=True,
                                       other_discounts=True, neutral_ships=True, guardian=True)
        result = dict(criteria=vars(criteria).copy(), search_limits=dict(want=50, max_pages=25))
        before = copy.deepcopy(result)
        text = tool.export_search_conditions(result)
        for value in ('参考星系: Sol', '检索半径 ly: 500', '最多结果: 50', '最多页数: 25',
                      'AX装备规格齐全: 是', '要求通用无人机控制器7A及7C: 是',
                      '包含其他全配件公共折扣站: 不适用（未要求折扣）', '全部联邦船: 否'):
            self.assertIn(value, text)
        self.assertEqual(result, before)
        self.assertEqual(tool.export_search_conditions({}), '未记录检索条件')

    def test_row_filter_runs_before_result_limit_and_radius_is_preserved(self):
        def search(kind, conditions, **kwargs):
            normalized = engine.normalize_conditions(kind, conditions)
            self.assertEqual(normalized[0]['max_ly'], 100)
            self.assertFalse(kwargs['row_filter'](dict(self.row, type='Stronghold Carrier', name='Stronghold Carrier')))
            row = copy.deepcopy(self.row)
            self.assertTrue(kwargs['row_filter'](row))
            return [row], 2, 2
        with patch.object(engine, 'search', side_effect=search):
            result = tool.search(self.criteria, catalog=self.catalog)
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(result['rejected'], 1)
        headers, records = tool.export_table(result)
        self.assertIn('15%', records[0])
        self.assertEqual(len(headers), len(records[0]))

    def test_other_discounts_use_named_sources_and_lyr_not_a_global_scan(self):
        criteria = tool.build_criteria('Sol', 500, other_discounts=True, require_discount=True)
        sources = tool.candidate_sources(criteria)
        self.assertEqual(len(sources), 2)
        for name, conditions in sources:
            fields = {item['field'] for item in conditions}
            self.assertTrue({'name', 'system_name'} <= fields or 'system_controlling_power' in fields)

    def test_page_failure_retries_once_and_preserves_verified_matches(self):
        row = dict(self.row, id='one', system_name='Sol', has_outfitting=True, system_x=0, system_y=0, system_z=0)
        error = urllib.error.HTTPError('test', 500, 'Internal Server Error', {}, None)
        original = engine.search
        with patch.object(engine, 'resolve_ref', return_value=('Sol', (0, 0, 0), False)), \
                patch.object(engine, '_http_json', side_effect=[dict(results=[row], count=2), dict(results=[]), dict(results=[]), error, error]) as http, \
                patch.object(engine, 'search', side_effect=lambda *a, **kw: original(*a, **dict(kw, page_size=1))), \
                patch.object(tool.time, 'sleep'):
            result = tool.search(self.criteria, catalog=self.catalog)
        self.assertEqual(http.call_count, 5)
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(result['scanned'], 1)
        self.assertEqual(result['total'], 2)
        self.assertTrue(result['partial'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['errors'][0]['page'], 2)
        self.assertEqual(result['errors'][0]['status'], 500)
        headers, records = tool.export_table(result, lambda value: value)
        self.assertNotIn('检索完整性', headers)
        self.assertEqual(dict(tool.export_context(result))['检索完整性'], '部分结果')

    def test_independent_sources_continue_after_failure_and_share_page_budget(self):
        calls = []

        def search(kind, conditions, **kwargs):
            calls.append(kwargs['max_pages'])
            kwargs['progress']('fetch', dict(phase='fetch', page=0, scanned=0, total=1))
            if len(calls) == 1:
                raise urllib.error.HTTPError('test', 500, 'Failed', {}, None)
            row = dict(self.row, id='success')
            self.assertTrue(kwargs['row_filter'](row))
            kwargs['notes'].append('候选分页已取完')
            return [row], 1, 1

        with patch.object(engine, 'search', side_effect=search):
            result = tool.search(tool.build_criteria('Sol', 500, other_discounts=True, require_discount=True),
                                 max_pages=3, catalog=self.catalog)
        self.assertEqual(calls, [3, 2])
        self.assertEqual(len(result['rows']), 1)
        self.assertTrue(result['partial'])
        self.assertEqual(result['errors'][0]['source'], 'Jameson Memorial')

    def test_page_budget_prevents_an_extra_source_query(self):
        calls = []

        def search(kind, conditions, **kwargs):
            calls.append(conditions)
            kwargs['progress']('fetch', dict(phase='fetch', page=0, scanned=0, total=0))
            kwargs['notes'].append('候选分页已取完')
            return [], 0, 0

        with patch.object(engine, 'search', side_effect=search):
            result = tool.search(tool.build_criteria('Sol', 500, other_discounts=True, require_discount=True),
                                 max_pages=1, catalog=self.catalog)
        self.assertEqual(len(calls), 1)
        self.assertTrue(result['partial'])

    def test_successful_retry_and_safety_limit(self):
        error = urllib.error.HTTPError('test', 503, 'Unavailable', {}, None)
        with patch.object(engine, '_http_json', side_effect=[error, dict(results=[])]), \
                patch.object(tool.time, 'sleep'):
            self.assertEqual(tool.request_json('test'), dict(results=[]))
        with patch.object(engine, '_http_json') as http:
            with self.assertRaises(ValueError):
                tool.request_json('https://spansh.co.uk/api/stations/search', dict(size=500, page=20))
        http.assert_not_called()

    def test_merc_coin_equipment_is_optional_and_never_a_power_alias(self):
        base = dict(name='Multi-Cannon', ed_symbol='multicannon', **{'class': 2, 'rating': 'E'})
        special = dict(base, name='Rapid Phase Multi-Cannon')
        with patch.object(catalog, 'SPECIAL_MODULES', {'Rapid Phase Multi-Cannon'}):
            prepared = catalog.prepare(dict(items=[base, special], issues=[], ships=[], armours=[]))
            self.assertEqual(len(prepared['items']), 1)
            self.assertEqual(len(prepared['special_items']), 1)
            row = dict(self.row, modules=[base])
            self.assertTrue(tool.check_station(row, self.criteria, prepared)['matched'])
            self.assertFalse(tool.check_station(row, tool.build_criteria('Sol', 100, special_equipment=True), prepared)['matched'])
            row['modules'].append(special)
            self.assertTrue(tool.check_station(row, tool.build_criteria('Sol', 100, special_equipment=True), prepared)['matched'])
            row['modules'] = [special]
            evidence = tool.check_station(row, self.criteria, prepared)
            self.assertFalse(evidence['matched'])
            self.assertEqual(evidence['present'], 0)
            self.assertEqual(len(evidence['unknown']), 1)
        self.assertNotIn('Rapid Phase Multi-Cannon', catalog.POWER_MODULES)

    def test_high_yield_2b_exclusion_keeps_other_merc_requirements_and_identity_facts(self):
        excluded = dict(name='High-Yield Enzyme Missile Rack', ed_symbol='hpt_causticmissile_fixed_medium',
                        **{'class': 2, 'rating': 'B'}, category='mercgear')
        required = dict(name='Rapid Phase Multi-Cannon', ed_symbol='merc_multicannon',
                        **{'class': 2, 'rating': 'E'}, category='mercgear')
        other_spec = dict(excluded, ed_symbol='future_variant', **{'class': 3, 'rating': 'A'})
        data = dict(self.catalog, special_items=[excluded, required], special_issues=[],
                    module_facts=[])
        criteria = tool.build_criteria('Sol', 500, special_equipment=True)
        row = dict(self.row, modules=[*self.items, required])
        before = copy.deepcopy(data)
        evidence = tool.check_station(row, criteria, data)
        self.assertTrue(evidence['matched'])
        self.assertEqual(evidence['required'], len(self.items) + 1)
        self.assertEqual(data, before)
        row['modules'] = self.items
        self.assertEqual(len(tool.check_station(row, criteria, data)['missing']), 1)
        self.assertFalse(catalog.excluded_merc_spec(other_spec))
        data['special_items'].append(other_spec)
        self.assertEqual(len(tool.check_station(row, criteria, data)['missing']), 2)
        with patch.object(catalog, 'SPECIAL_MODULES', {'High-Yield Enzyme Missile Rack'}):
            self.assertEqual(catalog.special_issues([]), [])

    def test_jameson_reference_remains_visible_outside_radius_and_lyr_scope(self):
        row = dict(self.row, name='Jameson Memorial', system_name='Shinrarta Dezhra', distance=65)
        with patch.object(engine, '_http_json', return_value=dict(results=[row])):
            reference = tool.reference_station(tool.build_criteria('Sol', 1), self.catalog)
        self.assertEqual(reference['name'], 'Jameson Memorial')
        self.assertFalse(reference['counted_as_hit'])
        self.assertFalse(reference['within_radius'])
        self.assertFalse(reference['scope_eligible'])
        self.assertIn('evidence', reference)

    def test_reference_failure_does_not_remove_the_named_reference(self):
        error = urllib.error.HTTPError('test', 500, 'Failed', {}, None)
        with patch.object(engine, '_http_json', side_effect=error), patch.object(tool.time, 'sleep'):
            reference = tool.reference_station(self.criteria, self.catalog)
        self.assertEqual(reference['name'], 'Jameson Memorial')
        self.assertIn('error', reference)
        self.assertFalse(reference['counted_as_hit'])

    def test_reference_is_attached_separately_and_never_added_as_a_hit(self):
        reference = dict(name='Jameson Memorial', counted_as_hit=False, scope_eligible=False)

        def search(kind, conditions, **kwargs):
            kwargs['notes'].append('候选分页已取完')
            return [], 0, 0

        with patch.object(tool, 'reference_station', return_value=reference), \
                patch.object(engine, 'search', side_effect=search):
            result = tool.search(self.criteria, catalog=self.catalog, include_reference=True)
        self.assertEqual(result['rows'], [])
        self.assertEqual(result['reference']['name'], 'Jameson Memorial')

    def test_discount_is_optional_but_full_stock_still_required(self):
        row = dict(self.row, system_controlling_power='Unrelated Power')
        criteria = tool.build_criteria('Sol', 500)
        self.assertFalse(criteria.require_discount)
        evidence = tool.check_station(row, criteria, self.catalog)
        self.assertTrue(evidence['matched'])
        self.assertTrue(evidence['no_discount'])
        self.assertFalse(tool.check_station(row, self.criteria, self.catalog)['matched'])
        headers, records = tool.export_table(dict(rows=[dict(row, _full_outfitting=evidence)], criteria=vars(criteria)))
        self.assertEqual(records[0][headers.index('公共折扣')], '未确认公共折扣')
        self.assertNotIn('None%', records[0])
        row['modules'] = row['modules'][1:]
        self.assertFalse(tool.check_station(row, criteria, self.catalog)['matched'])

    def test_no_discount_scope_ignores_preserved_other_discount_draft(self):
        criteria = tool.build_criteria('Sol', 500, other_discounts=True)
        sources = tool.candidate_sources(criteria)
        self.assertEqual(sources, [('全部配件商店', [])])

    def test_partial_station_discount_does_not_masquerade_as_all_module_discount(self):
        row = dict(self.row, name='Attilius Orbital', system_name='CD-43 11917',
                   system_controlling_power='', system_power_state='')
        evidence = tool.check_station(row, tool.build_criteria('Sol', 500), self.catalog)
        self.assertTrue(evidence['matched'])
        self.assertEqual(evidence['discount_min'], 30)
        self.assertLess(evidence['discount_covered'], evidence['discount_total'])
        headers, records = tool.export_table(dict(rows=[dict(row, _full_outfitting=evidence)], criteria={}))
        self.assertEqual(records[0][headers.index('已知优惠范围')], '部分配件有已知优惠')

    def test_only_identity_only_candidates_are_counted_as_pending(self):
        pending = dict(self.row, id='pending', modules=[dict(item) for item in self.items])
        pending['modules'][0]['name'] = 'Overloaded Beam Laser'
        incomplete = dict(pending, id='incomplete', modules=pending['modules'][:-1])

        def search(kind, conditions, **kwargs):
            self.assertFalse(kwargs['row_filter'](incomplete))
            self.assertFalse(kwargs['row_filter'](pending))
            kwargs['notes'].append('候选分页已取完')
            return [], 2, 2

        with patch.object(engine, 'search', side_effect=search):
            result = tool.search(tool.build_criteria('Sol', 500), catalog=self.catalog)
        self.assertEqual(result['uncertain'], 1)
        self.assertEqual(result['incomplete'], 1)
        self.assertEqual(len(result['identity_candidates']), 1)
        self.assertEqual(result['diagnostics'][0]['_full_outfitting']['review_status'], 'identity_pending')

    def test_required_stock_anchors_are_sent_as_independent_necessary_conditions(self):
        data = dict(items=[dict(name=name, **{'class': 8, 'rating': 'A'})
                           for name in ('Fuel Scoop', 'Prismatic Shield Generator')] + [
            dict(name='Rapid Phase Multi-Cannon', **{'class': 8, 'rating': 'A'}),
            dict(name='Anaconda Reactive Surface Composite', **{'class': 8, 'rating': 'A', 'ship': 'Anaconda'}),
            dict(name='Sensors', **{'class': 7, 'rating': 'A'})])
        anchors = tool.anchor_conditions(data)
        payload = engine.build_server_payload('stations', anchors)
        self.assertEqual(len(payload['filters']['modules']), 2)
        self.assertTrue(all(item['class']['value'] == [8] for item in payload['filters']['modules']))
        self.assertEqual({item['name']['value'][0] for item in payload['filters']['modules']},
                         {'Fuel Scoop', 'Prismatic Shield Generator'})


if __name__ == '__main__':
    unittest.main()
