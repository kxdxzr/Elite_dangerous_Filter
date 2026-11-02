from copy import deepcopy
import math
import random
import unittest
from unittest.mock import patch

import filter_engine as eng
from route_geometry import Envelope


class RouteGeometryTests(unittest.TestCase):
    def test_known_ellipsoid_is_smaller_than_endpoint_intersection(self):
        envelope = Envelope((0, 0, 0), (100, 0, 0), 120)
        self.assertEqual(envelope.center, (50, 0, 0))
        self.assertEqual(envelope.radius, 60)
        minor = math.sqrt(60**2 - 50**2)
        self.assertAlmostEqual(envelope.box[0][0], -10, places=5)
        self.assertAlmostEqual(envelope.box[1][1], minor, places=5)
        old_radius = math.sqrt(110**2 - 50**2)
        self.assertLess(envelope.radius, old_radius)

    def test_zero_detour_retains_entire_segment_and_same_endpoints_form_sphere(self):
        envelope = Envelope((0, 0, 0), (100, 0, 0), 100)
        for point in ((0, 0, 0), (50, 0, 0), (100, 0, 0)):
            self.assertTrue(envelope.contains(point))
        self.assertFalse(envelope.contains((50, 1, 0)))
        same = Envelope((5, 6, 7), (5, 6, 7), 20)
        self.assertTrue(same.contains((15, 6, 7)))
        self.assertFalse(same.contains((16, 6, 7)))
        self.assertAlmostEqual(same.box[0][0], -5, places=5)

    def test_nearly_zero_detour_keeps_narrow_ellipsoid_boundary(self):
        direct = 100000.0
        budget = math.nextafter(direct, math.inf)
        envelope = Envelope((0, 0, 0), (direct, 0, 0), budget)
        minor = math.sqrt(budget - direct) * math.sqrt(budget / 4 + direct / 4)
        point = (direct / 2, minor, 0)
        self.assertTrue(envelope.contains(point))
        self.assertGreaterEqual(envelope.box[1][1], minor)

    def test_random_feasible_points_are_never_cut_off_by_sphere_or_box(self):
        rng = random.Random(821)
        for _ in range(20):
            a, b = [tuple(rng.uniform(-100, 100) for _ in range(3)) for _ in range(2)]
            budget = math.dist(a, b) + rng.uniform(1, 100)
            envelope = Envelope(a, b, budget)
            for _ in range(500):
                point = tuple(rng.uniform(c - envelope.radius, c + envelope.radius) for c in envelope.center)
                if math.dist(a, point) + math.dist(point, b) <= budget:
                    self.assertTrue(envelope.contains(point))
                    self.assertLessEqual(math.dist(point, envelope.center), envelope.radius + envelope.epsilon)
                    for value, (lo, hi) in zip(point, envelope.box):
                        self.assertLessEqual(lo, value)
                        self.assertLessEqual(value, hi)

    def test_payload_preserves_input_and_tightens_existing_coordinate_bounds(self):
        envelope = Envelope((0, 0, 0), (100, 0, 0), 120)
        payload = dict(filters={'distance': {'max': 110}, 'x': dict(comparison='<=>', value=[0, 100])},
                       reference_system='A', sort=[{'distance': {'direction': 'asc'}}])
        original = deepcopy(payload)
        result = envelope.tighten('systems', payload, [], [])
        self.assertEqual(payload, original)
        self.assertNotIn('reference_system', result)
        self.assertEqual(result['reference_coords'], dict(x=50, y=0, z=0))
        self.assertEqual(result['filters']['x']['value'], [0, 100])
        self.assertLess(result['filters']['distance']['max'], 60.001)
        self.assertIn('y', result['filters'])
        stations = envelope.tighten('stations', payload, [], [])
        self.assertNotIn('y', stations['filters'])

    def test_ordinary_distance_keeps_reference_and_lower_bound(self):
        envelope = Envelope((0, 0, 0), (100, 0, 0), 120)
        payload = dict(filters={'distance': {'min': 5, 'max': 110}}, reference_system='A')
        conditions = [dict(type='field', field='distance', op='>', text=5)]
        result = envelope.tighten('stations', payload, conditions, [])
        self.assertEqual(result, payload)

    def test_stricter_existing_sphere_is_not_replaced(self):
        envelope = Envelope((0, 0, 0), (100, 0, 0), 120)
        payload = dict(filters={'distance': {'max': 10}}, reference_system='A')
        self.assertEqual(envelope.tighten('stations', payload, [], []), payload)

    def test_invalid_budget_finite_coordinates_and_conflicting_bounds(self):
        for budget in (-1, float('nan'), float('inf'), 9):
            with self.assertRaises(ValueError):
                Envelope((0, 0, 0), (10, 0, 0), budget)
        with self.assertRaises(ValueError):
            Envelope((float('inf'), 0, 0), (10, 0, 0), 20)
        with self.assertRaises(eng.Contradiction):
            Envelope((0, 0, 0), (10, 0, 0), 20).tighten('systems',
                dict(filters={'x': dict(comparison='<=>', value=[100, 110])}), [], [])

    def test_route_precheck_runs_before_detailed_enrichment_and_result_limit(self):
        rows = [dict(name='Off route', id64=1, x=50, y=50, z=0),
                dict(name='On route', id64=2, x=50, y=0, z=0)]
        conditions = [dict(type='distance', ref_system='A', max_ly=200),
                      dict(type='distance', ref_system='B', max_ly=200),
                      dict(field='station_count', op='>=', text=0)]
        captured = []
        def prepare(block, *args, **kwargs):
            captured.extend(row['name'] for row in block)
            for row in block:
                row['station_count'] = 1
        def resolve(name):
            return name, (0, 0, 0) if name == 'A' else (100, 0, 0), False
        import system_filters
        with patch.object(eng, 'resolve_ref', side_effect=resolve), \
                patch.object(eng, '_http_json', return_value=dict(results=rows, count=2)) as http, \
                patch.object(system_filters, 'prepare', side_effect=prepare):
            result, _, _ = eng.search('systems', conditions, want=1,
                route_bound=((0, 0, 0), (100, 0, 0), 100))
        self.assertEqual(captured, ['On route'])
        self.assertEqual([row['name'] for row in result], ['On route'])
        payload = http.call_args.args[1]
        self.assertLess(payload['filters']['distance']['max'], 50.001)

    def test_route_bound_participates_in_resume_identity(self):
        resume = {}
        with patch.object(eng, '_http_json', return_value=dict(results=[], count=0)):
            eng.search('systems', [], resume=resume, route_bound=((0, 0, 0), (10, 0, 0), 20))
            with self.assertRaises(ValueError):
                eng.search('systems', [], resume=resume, route_bound=((0, 0, 0), (10, 0, 0), 30))

    def test_same_complete_results_with_fewer_candidate_pages(self):
        origin, destination, budget = (0, 0, 0), (100, 0, 0), 120
        conditions = [dict(type='distance', ref_system=name, max_ly=110) for name in ('A', 'B')]
        rows = [dict(id=index, name=f'Port {index}', system_name=f'System {index}',
                     system_x=x, system_y=y, system_z=0)
                for index, (x, y) in enumerate(( (x, y) for x in range(-50, 151, 10)
                                               for y in range(-100, 101, 10)))]
        calls = []
        def http(url, payload):
            calls.append(payload)
            center = tuple(payload['reference_coords'][key] for key in ('x', 'y', 'z'))
            radius = payload['filters']['distance']['max']
            candidates = sorted([row for row in rows if math.dist(
                eng.result_coords('stations', row), center) <= radius],
                key=lambda row: math.dist(eng.result_coords('stations', row), center))
            start = payload['page'] * payload['size']
            return dict(count=len(candidates), results=deepcopy(candidates[start:start + payload['size']]))
        def resolve(name):
            return name, origin if name == 'A' else destination, False
        def on_route(row):
            point = eng.result_coords('stations', row)
            return math.dist(origin, point) + math.dist(point, destination) <= budget
        with patch.object(eng, 'resolve_ref', side_effect=resolve):
            old, _, old_scanned = eng.search('stations', conditions, want=1000, max_pages=100,
                page_size=20, row_filter=on_route, http=http)
            old_requests = len(calls)
            calls.clear()
            new, _, new_scanned = eng.search('stations', conditions, want=1000, max_pages=100,
                page_size=20, row_filter=on_route, http=http, route_bound=(origin, destination, budget))
        self.assertEqual({row['id'] for row in old}, {row['id'] for row in new})
        self.assertLess(len(calls), old_requests)
        self.assertLess(new_scanned, old_scanned)
