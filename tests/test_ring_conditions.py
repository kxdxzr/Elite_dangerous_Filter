import copy
import unittest
from unittest.mock import patch

import filter_engine as eng
import ring_conditions as rings


class RingConditionTests(unittest.TestCase):
    def condition(self, mode='types', values=None):
        return rings.validate(dict(mode=mode, values=['Metallic'] if values is None else values))

    def bodies(self):
        return [dict(name='X 1', rings=[dict(name='X 1 A', type='Metallic')]),
                dict(name='X 2', rings=[dict(name='X 2 A', type='Icy')])]

    def test_scope_and_multiple_types(self):
        c = self.condition()
        self.assertTrue(rings.evaluate('systems', {}, self.bodies(), c)[0])
        self.assertFalse(rings.evaluate('stations', dict(body_name='X 2'), self.bodies(), c)[0])
        c = self.condition(values=['Icy', 'Metallic'])
        self.assertTrue(rings.evaluate('stations', dict(body_name='X 2'), self.bodies(), c)[0])
        self.assertIsNone(rings.evaluate('stations', {}, self.bodies(), c)[0])
        self.assertIsNone(rings.evaluate('stations', dict(body_name='X 3'), self.bodies(), c)[0])

    def test_unknown_is_not_absence(self):
        c = self.condition('absent')
        for records in (None, [], [dict(name='X 1')], [None], [dict(name='X 1', rings=None)]):
            self.assertIsNone(rings.evaluate('systems', {}, records, c)[0])
        records = [dict(name='X 1', rings=[])]
        self.assertTrue(rings.evaluate('systems', {}, records, c)[0])
        self.assertIsNone(rings.evaluate('systems', dict(body_count=2), records, c)[0])
        self.assertFalse(rings.evaluate('systems', {}, self.bodies(), c)[0])
        self.assertIsNone(rings.evaluate('systems', {}, [dict(name='X', rings=[{}])], self.condition())[0])

    def test_validation_and_legacy_copy(self):
        for c in (dict(mode='bad'), dict(mode='types', values=[]), dict(mode='types', values=['bad'])):
            with self.assertRaises(ValueError):
                eng.normalize_conditions('systems', [dict(type='rings', **c)])
        old = dict(field='body_has_rings', op='false')
        original = copy.deepcopy(old)
        self.assertEqual(eng.normalize_conditions('stations', [old])[0]['mode'], 'absent')
        self.assertEqual(old, original)
        payload = eng.build_server_payload('systems', [self.condition()])
        self.assertNotIn('__rings__', payload['filters'])
        payload = eng.build_server_payload('stations', [self.condition()])
        self.assertEqual(payload['filters']['body_has_rings'], {'value': True})
        payload = eng.build_server_payload('stations', [self.condition('absent')])
        self.assertNotIn('body_has_rings', payload['filters'])

    def test_search_filters_before_fetch_and_limits_after_verification(self):
        candidates = [dict(id=1, name='Bad', system_name='X', body_name='X 2'),
                      dict(id=2, name='Good', system_name='X', body_name='X 1')]
        with patch('colonisation_tool.load_bodies', return_value={'x': self.bodies()}) as load:
            rows, _, _ = eng.search('stations', [self.condition()], want=1,
                                    http=lambda *a: dict(count=2, results=candidates))
            self.assertEqual([r['name'] for r in rows], ['Good'])
            load.assert_called_once()
            self.assertIn('X 1 A [Metallic]', rings.evidence_text(rows[0], self.condition()))
        with patch('colonisation_tool.load_bodies') as load:
            rows, _, _ = eng.search('stations', [self.condition(), dict(field='name', op='=', text='Missing')],
                                    http=lambda *a: dict(count=2, results=candidates))
            self.assertEqual(rows, [])
            load.assert_not_called()

    def test_station_boolean_and_unlimited_do_not_fetch_bodies(self):
        row = dict(body_has_rings=False, body_name='X 1', system_name='X')
        with patch('colonisation_tool.load_bodies') as load:
            c = self.condition('absent')
            rings.prepare('stations', [row], [c])
            self.assertTrue(rings.outcome(row, c))
            rings.prepare('systems', [dict(name='X')], [self.condition('any')])
            load.assert_not_called()

    def test_counts_and_cancellation_precede_ring_acceptance(self):
        import threading
        row = dict(name='X', stations=[], id64=1)
        with patch('colonisation_tool.load_bodies') as load:
            rows, _, _ = eng.search('systems', [self.condition(), dict(field='station_count', op='>', text=0)],
                                    http=lambda *a: dict(results=[row]))
            self.assertEqual(rows, [])
            load.assert_not_called()
        stop = threading.Event()
        def cancelled(*args, **kwargs):
            stop.set()
            return {'x': self.bodies()}
        with patch('colonisation_tool.load_bodies', side_effect=cancelled):
            rows, _, _ = eng.search('systems', [self.condition()], stop=stop,
                                    http=lambda *a: dict(results=[row]))
            self.assertEqual(rows, [])

    def test_diagnostics_and_csv(self):
        from main_csv import export_table
        c = self.condition()
        row = dict(name='X')
        with patch('colonisation_tool.load_bodies', return_value={'x': self.bodies()}), \
                patch.object(eng, '_http_json', return_value=dict(results=[row])):
            stats, size = eng.diagnose('systems', [c], pages=1)
            self.assertEqual((stats[0][1], size), (1, 1))
        titles, values = export_table([row], 'systems', [c], 'en', str)
        self.assertIn('Verified ring evidence', titles)
        self.assertIn('X 1 A [Metallic]', values[0][-1])


if __name__ == '__main__':
    unittest.main()
