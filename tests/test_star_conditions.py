"""Shared star filters must behave identically in both search entry points."""
import unittest
from unittest.mock import patch

import colonisation_tool as tool
import filter_engine as eng


def condition(field, value, op='='):
    return dict(field=field, op=op, value=value)


class StarConditionTests(unittest.TestCase):
    def records(self):
        return [dict(name='Example A', type='Star', subtype='G (White-Yellow) Star', is_main_star=True),
                dict(name='Example B', type='Star', subtype='Neutron Star', is_main_star=False),
                dict(name='Example 1', type='Planet', subtype='Water world', surface_temperature=500)]

    def test_star_type_and_primary_are_same_object_constraints(self):
        group = [condition('star_subtype', 'Neutron Star'), condition('is_main_star', 'true')]
        self.assertFalse(tool.match_groups(self.records(), [group], 'AND')[0])
        group[1]['value'] = 'false'
        hit, names = tool.match_groups(self.records(), [group], 'AND')
        self.assertTrue(hit)
        self.assertIn('Example B', names)
        self.assertNotIn('Example A', names)
        group[0]['value'] = 'G (White-Yellow) Star|Neutron Star'
        group[0]['op'] = 'in'
        self.assertTrue(tool.match_groups(self.records(), [group], 'AND')[0])

    def test_category_and_legacy_planet_semantics(self):
        self.assertTrue(tool.match_body_group(self.records()[0], [condition('type', 'Star')]))
        self.assertFalse(tool.match_body_group(self.records()[0], [condition('type', 'Planet')]))
        old = [condition('surface_temperature', '1000', '<')]
        star = dict(self.records()[0], surface_temperature=500)
        self.assertFalse(tool.match_body_group(star, old))
        self.assertTrue(tool.match_body_group(self.records()[2], old))
        self.assertFalse(tool.match_body_group(self.records()[2], [condition('is_main_star', 'false')]))
        self.assertFalse(tool.match_body_group(star, [condition('subtype', 'G (White-Yellow) Star')]))

    def test_primary_requires_boolean_evidence_not_names_or_distance(self):
        for flag in (None, 'true', 1):
            row = dict(type='Star', name='Sol', distance_to_arrival=0, is_main_star=flag)
            for op in ('=', '!='):
                self.assertIsNone(tool.match_body_group(row, [condition('is_main_star', 'false', op)]))
        with self.assertRaises(ValueError):
            tool.Criteria(body_groups=[[condition('is_main_star', '1')]]).validate()

    def test_star_group_modes(self):
        groups = [[condition('star_subtype', 'Neutron Star')], [condition('subtype', 'Earth-like world')]]
        self.assertFalse(tool.match_groups(self.records(), groups, 'AND')[0])
        self.assertTrue(tool.match_groups(self.records(), groups, 'OR')[0])

    def test_free_category_search_includes_companions_without_primary_flags(self):
        records = self.records()
        del records[1]['is_main_star']
        hit, names = tool.match_groups(records, [[condition('type', 'Star')]], 'AND')
        self.assertTrue(hit)
        self.assertIn('Example A', names)
        self.assertIn('Example B', names)
        self.assertNotIn('Example 1', names)
        for row in records:
            row['surface_temperature'] = 500
        group = [condition('type', 'Star|Planet', 'in'), condition('surface_temperature', '600', '<')]
        hit, names = tool.match_groups(records, [group], 'AND')
        self.assertTrue(hit)
        for row in records:
            self.assertIn(row['name'], names)

    def test_both_search_pipelines_and_csv_use_real_matching_names(self):
        from main_csv import export_table
        group = [condition('star_subtype', 'G (White-Yellow) Star'), condition('is_main_star', 'true')]
        candidate = dict(name='Example', id64=42, population=0, stations=[], needs_permit=False)
        with patch.object(tool, 'load_bodies', return_value={'example': self.records()}), \
                patch.object(eng, '_http_json', return_value=dict(count=1, results=[candidate])):
            info, colony_rows = tool.search(tool.Criteria(body_groups=[group]))
            self.assertIn('Example A', colony_rows[0]['_body_matches'])
            self.assertTrue(info['complete'])
            spec = dict(type='system_details', body_groups=[group])
            main_rows, _, _ = eng.search('systems', [spec])
            self.assertEqual(len(main_rows), 1)
            titles, values = export_table(main_rows, 'systems', [spec], 'en', str)
            self.assertIn('Matched bodies (1)', titles)
            self.assertIn('Example A', str(values))
            self.assertNotIn('Example B', str(values))


if __name__ == '__main__':
    unittest.main()
