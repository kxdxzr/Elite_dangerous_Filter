import itertools
import math
import threading
import unittest
from unittest.mock import patch

import waypoint_route as tool


def station(name, x, y=0, system=None, ident=None):
    return tool.point('stations', dict(name=name, system_name=system or name, id=ident or name,
        system_x=x, system_y=y, system_z=0, updated_at='2026-11-02T00:00:00Z'))


def system(name, x):
    return tool.point('systems', dict(name=name, x=x, y=0, z=0))


class WaypointRouteTests(unittest.TestCase):
    def solve(self, pools, extra=100):
        return tool.solve((0, 0, 0), (10, 0, 0), pools, extra)

    def test_fewer_stops_beats_shorter_distance(self):
        shared = station('Shared', 5, 10)
        result = self.solve([[station('First', 2), shared], [station('Second', 8), shared]])
        self.assertEqual(result['stops'], 1)
        self.assertEqual(result['route'][0]['name'], 'Shared')
        self.assertEqual(result['route'][0]['requirements'], [0, 1])
        self.assertEqual(set(result['route'][0]['evidence']), {0, 1})

    def test_budget_can_require_two_stops(self):
        shared = station('Shared', 5, 10)
        result = self.solve([[station('First', 2), shared], [station('Second', 8), shared]], extra=0)
        self.assertEqual(result['stops'], 2)
        self.assertEqual(result['total_ly'], 10)

    def test_same_count_chooses_shortest_and_orders_stops(self):
        result = self.solve([[station('Far', 8), station('Near', 2)], [station('Middle', 5)]], 0)
        self.assertEqual(result['stops'], 2)
        self.assertEqual(result['total_ly'], 10)
        self.assertEqual(result['route'][0]['leg_ly'] + result['route'][1]['leg_ly']
                         + result['final_leg_ly'], result['total_ly'])

    def test_no_cross_station_inventory_merge_or_cross_system_name_merge(self):
        result = self.solve([[station('Port A', 5, system='Shared')],
                             [station('Port B', 5, system='Shared')]])
        self.assertEqual(result['stops'], 2)
        result = self.solve([[station('Same', 2, system='One')],
                             [station('Same', 8, system='Two')]])
        self.assertEqual(result['stops'], 2)

    def test_station_covers_system_requirements_but_not_other_station(self):
        result = self.solve([[system('Shared', 5)], [station('Port', 5, system='Shared')]])
        self.assertEqual(result['stops'], 1)
        self.assertEqual(result['route'][0]['requirements'], [0, 1])

    def test_endpoints_free_for_systems_not_for_stations(self):
        result = self.solve([[system('A', 0)], [system('B', 10)]], 0)
        self.assertEqual(result['route'], [])
        self.assertEqual(result['endpoint_requirements'], [0, 1])
        self.assertEqual(result['stops'], 0)
        result = self.solve([[station('Port', 0)]], 0)
        self.assertEqual(result['stops'], 1)

    def test_endpoint_identity_is_not_inferred_from_coordinates(self):
        result = tool.solve((0, 0, 0), (10, 0, 0), [[system('Different', 0)]], 0,
                            endpoint_names=('A', 'B'))
        self.assertEqual(result['stops'], 1)
        self.assertEqual(result['endpoint_requirements'], [])

    def test_missing_and_distance_infeasible_never_return_partial_cover(self):
        result = self.solve([[station('Port', 5)], []])
        self.assertIsNone(result['route'])
        self.assertEqual(result['missing'], [1])
        result = self.solve([[station('Port', 5, 10)]], 0)
        self.assertIsNone(result['route'])
        self.assertEqual(result['missing'], [])

    def test_duplicate_records_and_input_immutability(self):
        item = station('Port', 5)
        result = self.solve([[item, item], [item]])
        self.assertEqual(result['stops'], 1)
        self.assertEqual(item['mask'], 0)
        self.assertEqual(item['evidence'], {})
        conflicting = station('Port', 6)
        with self.assertRaises(ValueError):
            self.solve([[item], [conflicting]])

    def test_optimum_matches_small_brute_force(self):
        a, b, c, d = station('A', 1, 2), station('B', 5, 1), station('C', 9, 0), station('D', 6, 4)
        pools = [[a, b], [b, c], [c, d]]
        for extra in (0, 3, 10):
            expected = (math.inf, math.inf)
            for length in range(1, 4):
                for route in itertools.permutations([a, b, c, d], length):
                    if not all(any(item['key'] in {r['key'] for r in route} for item in pool) for pool in pools):
                        continue
                    coords = [(0, 0, 0)] + [r['coords'] for r in route] + [(10, 0, 0)]
                    distance = sum(tool.eng.dist3(x, y) for x, y in zip(coords, coords[1:]))
                    if distance <= 10 + extra + 1e-8:
                        expected = min(expected, (length, distance))
            actual = self.solve(pools, extra)
            if math.isinf(expected[0]):
                self.assertIsNone(actual['route'])
            else:
                self.assertEqual(actual['stops'], expected[0])
                self.assertAlmostEqual(actual['total_ly'], expected[1])

    def test_validation_and_cancel(self):
        for value in (-1, float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                tool.Criteria('A', 'B', max_extra_ly=value).validate()
        for count in (0, 31, True):
            with self.assertRaises(ValueError):
                tool.Criteria('A', 'B', candidates_per_group=count).validate()
        for groups in ([], [dict(kind='stations', conditions=[])]):
            with self.assertRaises(ValueError):
                tool.validate_groups(groups)
        stop = threading.Event()
        stop.set()
        with self.assertRaises(InterruptedError):
            tool.solve((0, 0, 0), (10, 0, 0), [[station('X', 5)]], 0, stop=stop)

    def test_search_bounds_filters_candidates_before_limits_and_preserves_snapshot(self):
        groups = [dict(kind='stations', conditions=[dict(field='name', op='=', text='Port')])]
        observed = []
        def search(kind, conditions, **kwargs):
            observed.append(conditions)
            good, far = station('Port', 5)['row'], station('Far', 5, 100)['row']
            self.assertTrue(kwargs['row_filter'](good))
            self.assertFalse(kwargs['row_filter'](far))
            return [good], 1, 1
        with patch.object(tool.eng, 'resolve_ref', side_effect=[('A', (0, 0, 0), False), ('B', (10, 0, 0), False)]), \
                patch.object(tool.eng, 'search', side_effect=search):
            result = tool.search(tool.Criteria('A', 'B', max_extra_ly=3), groups)
        self.assertEqual(result['stops'], 1)
        self.assertEqual(len(groups[0]['conditions']), 1)
        self.assertEqual([c['max_ly'] for c in observed[0][-2:]], [13, 13])
        groups[0]['conditions'][0]['text'] = 'Changed'
        self.assertEqual(result['groups'][0]['conditions'][0]['text'], 'Port')

    def test_unknown_coordinates_rejected(self):
        self.assertIsNone(tool.point('systems', dict(name='Missing')))
        self.assertIsNone(tool.point('systems', dict(name='NaN', x=float('nan'), y=0, z=0)))

    def test_cross_match_finds_shared_station_outside_other_group_cap(self):
        shared = station('Shared', 5)
        shared['row']['services'] = ['Repair', 'Refuel']
        other = station('Other', 7)
        other['row']['services'] = ['Refuel']
        groups = [dict(kind='stations', conditions=[dict(field='services', op='in', values=[value])])
                  for value in ('Repair', 'Refuel')]
        pools = [[shared], [other]]
        tool.cross_match(groups, pools)
        result = self.solve(pools, 0)
        self.assertEqual(result['stops'], 1)
        self.assertEqual(result['route'][0]['name'], 'Shared')
        self.assertEqual(len(pools[0]), 1)
        self.assertEqual(len(pools[1]), 2)

    def test_cross_match_unknown_negative_field_is_not_evidence(self):
        groups = [dict(kind='stations', conditions=[dict(field='name', op='=', text='Port')]),
                  dict(kind='stations', conditions=[dict(field='services', op='not in', values=['Repair'])])]
        pools = [[station('Port', 5)], []]
        tool.cross_match(groups, pools)
        self.assertEqual(pools[1], [])

    def test_cross_match_does_not_invent_detailed_outcomes(self):
        group = dict(kind='systems', conditions=[dict(type='system_details', bodies=[])])
        pools = [[system('Known', 5)], []]
        tool.cross_match([dict(kind='systems', conditions=[dict(field='name', op='=', text='Known')]), group], pools)
        self.assertEqual(pools[1], [])
