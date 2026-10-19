import copy
import threading
import unittest
from unittest.mock import patch

import engineer_shopping as tool
import engineer_destinations as destinations
import filter_engine as eng
from i18n import translate


class EngineerShoppingTests(unittest.TestCase):
    def test_personal_bonus_search_export_and_assumption_snapshot(self):
        laser = dict(name='Beam Laser', category='hardpoint', weapon_mode='Fixed', **{'class': 2, 'rating': 'D'})
        condition = dict(field='modules', op='in', values=['Beam Laser'], discounted=True)
        criteria = tool.build_criteria('Start', 'Leesti', 80, '', condition, pledged_power='Jerome Archer')
        row = self.station(1, 160, system_controlling_power='Jerome Archer', modules=[laser])
        before = copy.deepcopy(criteria)
        with patch.object(eng, 'resolve_ref', side_effect=lambda name: (name, (0, 0, 0) if name == 'Start' else (320, 0, 0), False)), \
                patch.object(eng, 'resolve_option_cond'), \
                patch.object(eng, '_http_json', return_value=dict(count=1, results=[row])):
            result = tool.search(criteria)
        self.assertEqual(criteria, before)
        self.assertEqual(len(result['rows']), 1)
        headers, records = tool.export_table(result, 'en', lambda text: translate(text, 'en'))
        self.assertIn('30', records[0])
        self.assertTrue(any('assumed max-rank' in str(value) for value in records[0]))
        self.assertEqual(result['pledged_power'], 'Jerome Archer')
        for kwargs in ({}, dict(pledged_power='无')):
            other = tool.build_criteria('Start', 'Leesti', 80, '', condition, **kwargs)
            self.assertNotIn('personal_power', other.conditions[0])
            self.assertFalse(eng.match_field('stations', row, other.conditions[0]))

    def module(self):
        return dict(type='field', field='modules', op='in', values=['Shield Booster'],
                    **{'class': ['0'], 'rating': ['A'], 'discounted': True})

    def station(self, ident, x, y=0, **kwargs):
        return dict(dict(id=ident, name=f'Station {ident}', system_name=f'Shopping {ident}',
                         type='Coriolis Starport', system_x=x, system_y=y, system_z=0,
                         distance_to_arrival=100, system_controlling_power='Li Yong-Rui',
                         system_power_state='Fortified',
                         modules=[dict(name='Shield Booster', **{'class': 0, 'rating': 'A'})]), **kwargs)

    def run_search(self, rows, direct=320, jump=80, extra=1, want=100, ignore_planetary=False, landing_pad=''):
        criteria = tool.build_criteria('Start', 'Leesti', jump, 1500, self.module(), max_extra_jumps=extra,
                                       ignore_planetary=ignore_planetary, landing_pad=landing_pad)
        def resolve(name):
            return name, (0, 0, 0) if name == 'Start' else (direct, 0, 0), False
        with patch.object(eng, 'resolve_ref', side_effect=resolve), \
                patch.object(eng, 'resolve_option_cond'), \
                patch.object(eng, '_http_json', return_value=dict(count=len(rows), results=rows)):
            return tool.search(criteria, want=want)

    def test_criteria_range_extra_budget_carriers_and_no_single_jump_caps(self):
        for ignore in (True, False):
            criteria = tool.build_criteria(' LHS 336 ', 'Leesti', '93.5', '1500', self.module(), ignore, '2')
            self.assertEqual((criteria.origin, criteria.destination), ('LHS 336', 'Leesti'))
            self.assertEqual((criteria.jump_range, criteria.max_extra_jumps), (93.5, 2))
            self.assertFalse(any(c.get('type') == 'distance' for c in criteria.conditions))
            arrival = next(c for c in criteria.conditions if c.get('field') == 'distance_to_arrival')
            self.assertEqual((arrival['op'], arrival['text']), ('<', 1500))
            exclusions = [c for c in criteria.conditions if c.get('field') == 'type']
            self.assertEqual(bool(exclusions), ignore)

    def test_optional_arrival_and_validation(self):
        module = self.module()
        before = copy.deepcopy(module)
        criteria = tool.build_criteria('Sol', 'Sol', 80, '', module)
        self.assertFalse(any(c.get('field') == 'distance_to_arrival' for c in criteria.conditions))
        self.assertEqual(module, before)
        for jump, arrival in ((0, ''), (-1, ''), ('nan', ''), ('inf', ''),
                              (80, 'nan'), (80, '-1'), ('bad', '')):
            with self.subTest(jump=jump, arrival=arrival), self.assertRaises(ValueError):
                tool.build_criteria('Sol', 'Leesti', jump, arrival, module)
        for extra in ('', '1.5', -1, True, 'nan', 'inf'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                tool.build_criteria('Sol', 'Leesti', 80, '', module, max_extra_jumps=extra)

    def test_landing_pad_criteria_defaults_and_validation(self):
        for value, expected in (('', ''), ('不限', ''), (' S ', 'S'), ('M', 'M'), ('L', 'L')):
            criteria = tool.build_criteria('Sol', 'Leesti', 80, '', self.module(), landing_pad=value)
            self.assertEqual(criteria.landing_pad, expected)
        for value in ('XL', 'Large', 'm', None, [], True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                tool.build_criteria('Sol', 'Leesti', 80, '', self.module(), landing_pad=value)
        self.assertEqual(tool.build_criteria('Sol', 'Leesti', 80, '', self.module()).landing_pad, '')

    def test_confirmed_pad_rejects_missing_invalid_and_zero_counts(self):
        for value in (None, '', 'unknown', True, False, -1, 0, .5, 'nan', 'inf'):
            self.assertIsNone(tool.confirmed_pad(dict(large_pads=value, has_large_pad=False)))
        self.assertEqual(tool.confirmed_pad(dict(large_pads='2')), 'L')
        self.assertEqual(tool.confirmed_pad(dict(has_large_pad=True)), 'L')
        self.assertEqual(tool.confirmed_pad(dict(large_pads=0, medium_pads=1, small_pads=3)), 'M')

    def test_ship_size_filter_accepts_larger_pads_without_assuming_unknowns(self):
        rows = [self.station(1, 160, small_pads=1), self.station(2, 160, medium_pads=1),
                self.station(3, 160, large_pads=1), self.station(4, 160, has_large_pad=True),
                self.station(5, 160), self.station(6, 160, small_pads=0, medium_pads=0, large_pads=0)]
        for pad, expected in (('', [1, 2, 3, 4, 5, 6]), ('S', [1, 2, 3, 4]),
                               ('M', [2, 3, 4]), ('L', [3, 4])):
            with self.subTest(pad=pad):
                result = self.run_search(copy.deepcopy(rows), landing_pad=pad)
                self.assertEqual([row['id'] for row in result['rows']], expected)
                self.assertEqual(result['landing_pad'], pad)

    def test_pad_and_all_stock_must_match_same_station_before_counting_want(self):
        rows = [self.station(1, 160, medium_pads=1), self.station(2, 160),
                self.station(3, 160, has_large_pad=True, modules=[]),
                self.station(4, 160, has_large_pad=True)]
        result = self.run_search(rows, landing_pad='L', want=1)
        self.assertEqual([row['id'] for row in result['rows']], [4])
        self.assertEqual(result['scanned'], 4)
        headers, records = tool.export_table(result, 'en', lambda text: translate(text, 'en'))
        self.assertEqual(records[0][headers.index('Confirmed landing pad')], 'L')

    def test_pad_rejections_keep_fetching_pages_until_a_valid_station(self):
        criteria = tool.build_criteria('Start', 'Leesti', 80, '', self.module(), landing_pad='L')
        before = copy.deepcopy(criteria)
        pages = [dict(count=501, results=[self.station(i, 160, medium_pads=1) for i in range(500)]),
                 dict(count=501, results=[self.station(500, 160, has_large_pad=True)])]
        with patch.object(eng, 'resolve_ref', side_effect=lambda name: (name, (0, 0, 0) if name == 'Start' else (320, 0, 0), False)), \
                patch.object(eng, 'resolve_option_cond'), patch.object(eng, '_http_json', side_effect=pages) as http:
            result = tool.search(criteria, want=1)
        self.assertEqual(http.call_count, 2)
        self.assertEqual([row['id'] for row in result['rows']], [500])
        self.assertEqual(criteria, before)

    def test_multi_jump_candidates_and_extra_jump_budget(self):
        # Both legs are two jumps, yet this is a zero-extra-jump shopping stop.
        result = self.run_search([self.station(1, 160), self.station(2, 81)], extra=0)
        self.assertEqual([row['id'] for row in result['rows']], [1])
        route = result['rows'][0]['_shopping_route']
        self.assertEqual(route, dict(origin_jumps=2, destination_jumps=2, direct_jumps=4,
                                    total_jumps=4, extra_jumps=0, detour_ly=0))
        result = self.run_search([self.station(2, 81)], extra=1)
        self.assertEqual(result['rows'][0]['_shopping_route']['extra_jumps'], 1)
        # Old two-one-jump candidates are naturally supported without a mode switch.
        result = self.run_search([self.station(3, 40)], direct=100, extra=0)
        self.assertEqual(result['rows'][0]['_shopping_route']['total_jumps'], 2)

    def test_planetary_exclusion_is_optional_and_does_not_change_engineer_destination(self):
        rows = [self.station(1, 160, is_planetary=False), self.station(2, 160, is_planetary=True),
                self.station(3, 160)]
        self.assertEqual([r['id'] for r in self.run_search(rows)['rows']], [1, 2, 3])
        result = self.run_search(rows, ignore_planetary=True)
        self.assertEqual([r['id'] for r in result['rows']], [1])
        condition = next(c for c in result['conditions'] if c.get('field') == 'is_planetary')
        self.assertEqual(condition['op'], 'false')
        payload = eng.build_server_payload('stations', result['conditions'])
        # The shared planner deliberately keeps false booleans local because
        # the upstream endpoint mishandles them. The returned flag is rechecked.
        self.assertNotIn('is_planetary', payload['filters'])
        self.assertTrue(any('is_planetary=否' in note for note in result['notes']))
        self.assertIn('Leesti', [c['ref_system'] for c in result['conditions'] if c.get('type') == 'distance'])

    def test_stock_specs_discount_arrival_and_carrier_still_checked(self):
        candidates = [self.station(1, 160), self.station(2, 160, type='Drake-Class Carrier'),
                      self.station(3, 1000), self.station(4, 160, distance_to_arrival=1500),
                      self.station(5, 160, system_controlling_power='Other'),
                      self.station(6, 160, modules=[dict(name='Shield Booster', **{'class': 0, 'rating': 'E'})])]
        self.assertEqual([r['id'] for r in self.run_search(candidates)['rows']], [1])

    def test_rejected_route_does_not_consume_want_and_precision_is_not_rounded(self):
        # First leg displays 80.00 ly but really needs two estimated jumps.
        result = self.run_search([self.station(1, 80.001), self.station(2, 160)], extra=0, want=1)
        self.assertEqual([r['id'] for r in result['rows']], [2])
        self.assertEqual(result['scanned'], 2)

    def test_extra_filter_keeps_fetching_pages_until_a_real_match(self):
        criteria = tool.build_criteria('Start', 'Leesti', 80, '', self.module(), max_extra_jumps=0)
        pages = [dict(count=501, results=[self.station(i, 81) for i in range(500)]),
                 dict(count=501, results=[self.station(500, 160)])]
        with patch.object(eng, 'resolve_ref', side_effect=lambda name: (name, (0, 0, 0) if name == 'Start' else (320, 0, 0), False)), \
                patch.object(eng, 'resolve_option_cond'), patch.object(eng, '_http_json', side_effect=pages) as http:
            result = tool.search(criteria, want=1)
        self.assertEqual(http.call_count, 2)
        self.assertEqual(result['rows'][0]['id'], 500)

    def test_ranking_extra_then_detour_then_discount_and_export_columns(self):
        rows = [self.station(1, 81), self.station(2, 160, y=10), self.station(3, 160),
                self.station(4, 160, name='Jameson Memorial', system_name='Shinrarta Dezhra',
                             system_controlling_power='Other')]
        result = self.run_search(rows, extra=2)
        self.assertEqual([r['id'] for r in result['rows']], [3, 4, 1, 2])
        headers, records = tool.export_table(result, 'en', lambda text: translate(text, 'en'))
        self.assertEqual(headers[-6:], ['Estimated direct jumps', 'Estimated jumps to shop',
                                       'Estimated jumps to engineer', 'Estimated total jumps via shop',
                                       'Estimated extra jumps', 'Detour distance ly'])
        self.assertEqual(records[0][-6:], ['4', '2', '2', '4', '0', '0.00'])

    def test_same_system_zero_distance_and_boundaries(self):
        self.assertEqual(tool.estimated_jumps(0, 80), 0)
        self.assertEqual(tool.estimated_jumps(80, 80), 1)
        self.assertEqual(tool.estimated_jumps(80.001, 80), 2)
        result = self.run_search([self.station(1, 0), self.station(2, 40)], direct=0, extra=0)
        self.assertEqual([r['id'] for r in result['rows']], [1])
        result = self.run_search([self.station(2, 40)], direct=0, extra=2)
        self.assertEqual(result['rows'][0]['_shopping_route']['extra_jumps'], 2)

    def test_result_snapshot_and_cancellation_before_network(self):
        criteria = tool.build_criteria('start', 'Leesti', 80, '', self.module())
        original = copy.deepcopy(criteria)
        stop = threading.Event()
        stop.set()
        with patch.object(eng, 'resolve_ref') as resolve, patch.object(eng, 'search') as search:
            result = tool.search(criteria, stop=stop)
        resolve.assert_not_called()
        search.assert_not_called()
        self.assertEqual(criteria, original)
        self.assertTrue(result['stopped'])

    def test_multiple_names_mean_all_and_each_line_can_have_its_own_specification(self):
        first = self.module()
        second = dict(field='modules', op='in', values=['Plasma Accelerator', 'Rail Gun'],
                      **{'class': [3], 'rating': ['B']}, discounted=True)
        source = copy.deepcopy([first, second])
        criteria = tool.build_criteria('Start', 'Leesti', 80, '', source)
        self.assertEqual([c['values'] for c in criteria.conditions[:3]],
                         [['Shield Booster'], ['Plasma Accelerator'], ['Rail Gun']])
        self.assertEqual(criteria.conditions[0]['class'], [0])
        self.assertEqual(criteria.conditions[1]['class'], [3])
        self.assertEqual(source, [first, second])
        with self.assertRaises(ValueError):
            tool.build_criteria('Start', 'Leesti', 80, '', [])

    def test_station_must_stock_every_item_with_its_own_specs_before_counting_want(self):
        plasma = dict(field='modules', op='in', values=['Plasma Accelerator'],
                      **{'class': [2], 'rating': ['C']}, discounted=True)
        criteria = tool.build_criteria('Start', 'Leesti', 80, '', [self.module(), plasma])
        booster_stock = dict(name='Shield Booster', **{'class': 0, 'rating': 'A'})
        plasma_stock = dict(name='Plasma Accelerator', **{'class': 2, 'rating': 'C'})
        rows = [self.station(1, 160), self.station(2, 160, modules=[plasma_stock]),
                self.station(3, 160, modules=[booster_stock, dict(plasma_stock, rating='B')]),
                self.station(4, 160, modules=[booster_stock, plasma_stock])]
        with patch.object(eng, 'resolve_ref', side_effect=lambda name: (name, (0, 0, 0) if name == 'Start' else (320, 0, 0), False)), \
                patch.object(eng, 'resolve_option_cond'), \
                patch.object(eng, '_http_json', return_value=dict(count=4, results=rows)) as http:
            result = tool.search(criteria, want=1)
        self.assertEqual([row['id'] for row in result['rows']], [4])
        self.assertEqual(result['scanned'], 4)
        self.assertEqual(len(http.call_args.args[1]['filters']['modules']), 2)

    def test_same_name_different_specs_are_independent_requirements(self):
        modules = [dict(field='modules', op='in', values=['Plasma Accelerator'],
                        **{'class': [cls], 'rating': [rating]}) for cls, rating in ((2, 'C'), (3, 'B'))]
        criteria = tool.build_criteria('Start', 'Leesti', 80, '', modules, ignore_carriers=False)
        stock = [dict(name='Plasma Accelerator', **{'class': cls, 'rating': rating})
                 for cls, rating in ((2, 'C'), (3, 'B'))]
        self.assertFalse(eng.match_candidate('stations', {'modules': stock[:1]}, criteria.conditions, {}, {}, set()))
        self.assertTrue(eng.match_candidate('stations', {'modules': stock}, criteria.conditions, {}, {}, set()))

    def test_discount_requirement_is_independent_for_each_purchase(self):
        modules = [dict(field='modules', op='in', values=['Cargo Rack'], discounted=True),
                   dict(field='modules', op='in', values=['Fuel Scoop'])]
        criteria = tool.build_criteria('Start', 'Leesti', 80, '', modules, ignore_carriers=False)
        row = dict(system_controlling_power='Edmund Mahon', system_power_state='Fortified',
                   modules=[dict(name='Cargo Rack'), dict(name='Fuel Scoop')])
        self.assertTrue(eng.match_candidate('stations', row, criteria.conditions, {}, {}, set()))
        criteria.conditions[1]['discounted'] = True
        self.assertFalse(eng.match_candidate('stations', row, criteria.conditions, {}, {}, set()))

    def test_only_ship_engineer_destinations_are_accepted(self):
        self.assertEqual(len(destinations.CHOICES), 25)
        self.assertEqual(len(set(destinations.CHOICES)), 25)
        for (name, system), choice in zip(destinations.SHIP_ENGINEERS, destinations.CHOICES):
            for value in (name, system, choice, f' {system.lower()} '):
                self.assertEqual(destinations.destination_system(value), system)
                self.assertEqual(destinations.destination_choice(value), choice)
        for value in ('LHS 336', 'Maia', 'Domino Green', '', 'Unknown — Leesti'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                destinations.destination_system(value)
        criteria = tool.build_criteria('LHS 336', 'Didi Vatermann — Leesti', 80, '', self.module())
        self.assertEqual(criteria.destination, 'Leesti')
        with self.assertRaises(ValueError):
            tool.build_criteria('Leesti', 'LHS 336', 80, '', self.module())
