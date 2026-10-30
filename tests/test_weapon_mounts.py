import unittest
from unittest.mock import patch

from i18n import translate
from module_spec_pairs import BUNDLED_MODULE_PAIRS
from weapon_mounts import MOUNT_CODES, specification_labels, specification_choices, item_mount


class WeaponMountTests(unittest.TestCase):
    def test_choices_are_separate_and_legacy_raw_code_is_not_reinterpreted(self):
        values, labels = specification_choices(['Beam Laser'], ['2D', '2E'])
        self.assertEqual(values, ['2D|Fixed', '2D|Gimballed', '2E|Turreted'])
        self.assertEqual(labels['2D|Fixed'], '2D（固定）')
        self.assertEqual(labels['2D|Gimballed'], '2D（万向）')

    def test_same_item_mount_matching_unknown_and_export(self):
        import filter_engine as eng
        from main_csv import export_table
        condition = dict(field='modules', op='in', values=['Beam Laser'],
                         **{'class': [2], 'rating': ['D'], 'weapon_mode': 'Gimballed'})
        fixed = dict(name='Beam Laser', **{'class': 2, 'rating': 'D'}, weapon_mode='Fixed')
        gimbal = dict(fixed, weapon_mode='Gimbal')
        self.assertFalse(eng.match_field('stations', {'modules': [fixed]}, condition))
        self.assertTrue(eng.match_field('stations', {'modules': [gimbal]}, condition))
        self.assertFalse(eng.match_field('stations', {'modules': [dict(fixed, weapon_mode=None)]}, condition))
        self.assertFalse(eng.match_field('stations', {'modules': [fixed, dict(gimbal, rating='E')]}, condition))
        symbolic = dict(fixed, weapon_mode=None, ed_symbol='Hpt_BeamLaser_Gimbal_Medium')
        self.assertTrue(eng.match_field('stations', {'modules': [symbolic]}, condition))
        self.assertIsNone(item_mount(dict(symbolic, weapon_mode='Fixed')))
        headers, records = export_table([{'name': 'Station', 'modules': [symbolic]}], 'stations',
                                         [condition], 'en', lambda s: translate(s, 'en'))
        self.assertTrue(any('Weapon mount' in h for h in headers))
        self.assertIn('Gimballed', records[0])
        for value in ['bad', True, ['Fixed']]:
            with self.assertRaises(ValueError):
                eng.normalize_conditions('stations', [dict(condition, weapon_mode=value)])

    def test_search_rejects_wrong_mount_before_result_limit(self):
        import filter_engine as eng
        cond = dict(field='modules', op='in', values=['Beam Laser'],
                    **{'class': [2], 'rating': ['D'], 'weapon_mode': 'Gimballed'})
        item = dict(name='Beam Laser', **{'class': 2, 'rating': 'D'})
        response = dict(count=2, results=[
            dict(id=1, name='Fixed only', modules=[dict(item, weapon_mode='Fixed')]),
            dict(id=2, name='Gimbal', modules=[dict(item, weapon_mode='Gimbal')])])
        with patch.object(eng, '_http_json', return_value=response), \
                patch.object(eng.fo, 'get_options', return_value=['Beam Laser']):
            rows, _, _ = eng.search('stations', [cond], want=1)
        self.assertEqual([r['id'] for r in rows], [2])
        legacy = dict(cond)
        legacy.pop('weapon_mode')
        self.assertTrue(eng.match_field('stations', response['results'][0], legacy))

    def test_same_rating_does_not_imply_same_mount(self):
        self.assertEqual(specification_labels(['Beam Laser'], ['2D', '2E']),
                         {'2D': '2D（固定／万向）', '2E': '2E（炮塔）'})
        self.assertEqual(specification_labels(['Multi-Cannon'], ['2E', '2F']),
                         {'2E': '2E（固定）', '2F': '2F（万向／炮塔）'})

    def test_no_cross_name_merge_and_unknown_is_not_guessed(self):
        self.assertEqual(specification_labels(['Beam Laser', 'Multi-Cannon'], ['2E']), {})
        self.assertEqual(specification_labels(['Fuel Scoop'], ['5A']), {})
        self.assertEqual(specification_labels([], ['2E']), {})
        self.assertEqual(specification_labels(['AX Missile Rack'], ['2E']), {'2E': '2E（支架未知）'})
        self.assertEqual(specification_labels(['beam laser'], ['2D']), {'2D': '2D（固定／万向）'})

    def test_bundled_facts_only_decorate_existing_pairs_and_translate(self):
        for name, codes in MOUNT_CODES.items():
            for part in codes.split():
                code, modes = part.split(':')
                self.assertIn((int(code[0]), code[1]), BUNDLED_MODULE_PAIRS[name])
                self.assertTrue(set(modes) <= set('FGT'))
                label = specification_labels([name], [code])[code]
                english = translate(label, 'en')
                self.assertNotEqual(english, label)
                self.assertTrue(english.startswith(code + ' ('))
                self.assertTrue(english.isascii())
