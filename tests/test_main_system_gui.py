import csv
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'Requires a GUI display')
class MainSystemGuiTests(unittest.TestCase):
    def test_visible_copy_actions_across_result_windows(self):
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        self.app.results = [dict(name='Station One', system_name='Sol')]
        item = self.app.tree.insert('', 'end', values=('Station One', 'Sol', '', ''))
        self.app.tree.selection_set(item)
        buttons = {getattr(w, '_raw_text', ''): w for w in descendants(self.root)
                   if isinstance(w, self.gui.ttk.Button)}
        buttons['复制名称'].invoke()
        self.assertEqual(self.root.clipboard_get(), 'Station One')
        buttons['复制星系名'].invoke()
        self.assertEqual(self.root.clipboard_get(), 'Sol')

        for open_tool, title, expected in (
            (self.app.carrier_parking_window, '航母车位查找', {'复制星系名': 'name'}),
            (self.app.midpoint_window, '两系中点 - 离中点最近的星系', {'复制星系名': 'name'}),
            (self.app.rare_goods_window, '稀有商品目标查找器', {'复制星系名': 'system', '复制空间站名': 'station'}),
            (self.app.pve_window, '海盗任务查找器', {'复制目标星系': 'target', '复制任务来源星系': 'source', '复制来源空间站': 'source_station'}),
        ):
            open_tool()
            win = next(w for w in self.root.winfo_children() if getattr(w, '_raw_title', '') == title)
            widgets = list(descendants(win))
            tree = next(w for w in widgets if isinstance(w, self.gui.ttk.Treeview)
                        and set(expected.values()).issubset(w['columns']))
            values = [f'Original {key}' for key in tree['columns']]
            item = tree.insert('', 'end', values=values)
            tree.selection_set(item)
            buttons = {getattr(w, '_raw_text', ''): w for w in widgets if isinstance(w, self.gui.ttk.Button)}
            for label, key in expected.items():
                buttons[label].invoke()
                self.assertEqual(win.clipboard_get(), f'Original {key}')
            win.destroy()

    def setUp(self):
        from test_colonisation_gui import ColonisationGuiTests
        ColonisationGuiTests.setUp(self)

    def tearDown(self):
        from test_colonisation_gui import ColonisationGuiTests
        ColonisationGuiTests.tearDown(self)

    def test_main_details_and_counts_survive_language_session_and_condition_loading(self):
        self.app.kind.set('systems')
        self.app._append_cond(dict(field='station_count', op='=', text=0))
        win = self.app.add_system_details()
        row = self.app.rows[-1]
        win.group_editors['body_groups'].add_group([
            dict(field='is_landable', op='=', value='true'),
            dict(field='gravity', op='<=', value='1')])
        win.group_editors['ring_groups'].add_group([dict(field='ring.type', op='=', value='Metallic')])
        row.variables['population_min'].set('100')
        row.variables['nearest_min'].set('3')
        row.variables['nearest_max'].set('10')
        before = self.app.collect()
        self.app.set_language('en')
        self.assertEqual(win.title(), 'Main-window system details')
        self.assertEqual(self.app.collect(), before)
        state = self.app._state_dict()
        self.app._apply_state(state)
        self.assertEqual(self.app.collect(), before)
        self.app._apply_state(dict(kind='systems', conditions=before))
        self.assertEqual(self.app.collect(), before)
        self.assertIn('station_count', self.gui.parse_field_label(self.app.rows[0].field.get()))
        self.app.kind.set('stations')
        self.app.refresh_fields()
        with self.assertRaises(ValueError):
            self.app.rows[-1].to_cond()

    def test_invalid_group_draft_is_preserved(self):
        self.app.kind.set('systems')
        win = self.app.add_system_details()
        win.group_editors['body_groups'].add_group()
        row = self.app.rows[-1]
        row.variables['nearest_min'].set('unfinished')
        state = self.app._state_dict()
        self.assertEqual(state['rows'][0]['settings']['nearest_min'], 'unfinished')
        self.app._apply_state(state)
        self.assertEqual(self.app.rows[0].editor_state(), state['rows'][0])
        with self.assertRaises(ValueError):
            self.app.collect()

    def test_sale_discount_controls_and_session_roundtrip(self):
        self.app.clear()
        self.app.kind.set('stations')
        for field in ('ships', 'modules'):
            self.app._append_cond(dict(field=field, op='=', text='Anaconda' if field == 'ships' else 'Frame Shift Drive',
                                       discounted=field == 'ships'))
        before = self.app.collect()
        self.assertEqual([c.get('discounted') for c in before], [True, None])
        self.root.update()
        for row in self.app.rows:
            self.assertTrue(row.cb_discount.winfo_manager())
            self.assertEqual(tuple(row.cb_discount['values']), ('不限', '是'))
        state = self.app._state_dict()
        self.app.set_language('en')
        self.assertEqual(self.app.collect(), before)
        self.assertEqual(self.app.rows[0].lbl_discount.cget('text'), 'Discounted')
        self.app._apply_state(state)
        self.assertEqual(self.app.collect(), before)
        self.app._apply_state(dict(kind='stations', conditions=before))
        self.assertEqual(self.app.collect(), before)
        row = self.app.rows[0]
        row.op.set('不属于')
        row.refresh_options()
        self.assertFalse(row.cb_discount.winfo_manager())
        self.assertNotIn('discounted', row.to_cond())

    def test_one_spec_selector_uses_real_pairs_and_preserves_legacy_filters(self):
        self.app.clear()
        self.app.kind.set('stations')
        condition = dict(field='modules', op='=', text='Plasma Accelerator', **{'class': [2], 'rating': ['C']})
        self.app._append_cond(condition)
        row = self.app.rows[0]
        self.assertTrue(row.cb_spec.winfo_manager())
        self.assertEqual(tuple(row.cb_spec['values']), ('不限', '2C', '3B', '4A'))
        self.assertEqual(row.v_spec.get(), '2C')
        row.v_spec.set('3B')
        actual = row.to_cond()
        self.assertEqual(actual['class'], ['3'])
        self.assertEqual(actual['rating'], ['B'])
        before = self.app.collect()
        self.app.set_language('en')
        self.assertEqual(row.lbl_spec.cget('text'), 'Specification')
        self.assertEqual(self.app.collect(), before)
        row.v_spec.set('不限')
        self.assertNotIn('class', row.to_cond())
        self.assertNotIn('rating', row.to_cond())
        # A legacy multi-class/partial filter remains exactly that, not a guessed variant.
        row.v_class.set('2; 3')
        row.v_rating.set('')
        row._refresh_spec_options()
        legacy = row.to_cond()
        self.assertEqual(legacy['class'], ['2', '3'])
        state = self.app._state_dict()
        self.app._apply_state(state)
        self.assertEqual(self.app.rows[0].to_cond(), legacy)
        self.app.rows[0].v_spec.set('unfinished')
        state = self.app._state_dict()
        self.app._apply_state(state)
        self.assertEqual(self.app.rows[0].v_spec.get(), 'unfinished')
        with self.assertRaises(ValueError):
            self.app.rows[0].to_cond()

    def test_sorted_main_results_copy_the_selected_system_not_original_row_index(self):
        self.app.results = [dict(name='Shop 10', system_name='System 10'),
                            dict(name='Shop 2', system_name='System 2')]
        self.app._result_kind, self.app._result_conditions = 'stations', []
        self.app.render_main_results()
        self.app.tree.sort_by('name')
        item = self.app.tree.get_children()[0]
        self.assertEqual(self.app.tree.set(item, 'name'), 'Shop 2')
        self.app.tree.selection_set(item)
        self.app.copy_result_system()
        self.assertEqual(self.root.clipboard_get(), 'System 2')
        self.assertEqual([r['name'] for r in self.app.results], ['Shop 10', 'Shop 2'])

    def test_search_copy_and_close_buttons_follow_language_in_new_windows(self):
        from main_system_gui import DetailsRow
        self.app.set_language('en')
        colony = self.app.colonisation_window()
        shopping = self.app.engineer_shopping_window()
        row = DetailsRow(self.app.inner, 'systems')
        editor = row.open_editor()
        def buttons(parent):
            result = {}
            for widget in parent.winfo_children():
                if isinstance(widget, self.gui.ttk.Button):
                    result[getattr(widget, '_raw_text', '')] = widget
                result.update(buttons(widget))
            return result
        checks = [(buttons(colony)['查询'], '查询', 'Search'),
                  (buttons(shopping)['查询'], '查询', 'Search'),
                  (buttons(shopping)['复制站名'], '复制站名', 'Copy station name'),
                  (buttons(editor)['关闭'], '关闭', 'Close')]
        for widget, _, expected in checks:
            self.assertEqual(widget.cget('text'), expected)
        self.app.set_language('zh')
        for widget, expected, _ in checks:
            self.assertEqual(widget.cget('text'), expected)
        self.app.set_language('en')
        for widget, _, expected in checks:
            self.assertEqual(widget.cget('text'), expected)

    def test_all_result_windows_have_sortable_headers(self):
        with patch.object(self.gui.fo, 'get_options', return_value=[]):
            self.app.midpoint_window()
            self.app.carrier_parking_window()
            self.app.rare_goods_window()
            self.app.pve_window()
            self.app.colonisation_window()
            self.app.engineer_shopping_window()
        trees = []
        def scan(parent):
            for child in parent.winfo_children():
                if isinstance(child, self.gui.ttk.Treeview):
                    trees.append(child)
                scan(child)
        scan(self.root)
        self.assertGreaterEqual(len(trees), 8)
        editors = [tree for tree in trees if not tree._sortable]
        self.assertEqual(len(editors), 0)
        for tree in trees:
            for column in tree['columns']:
                command = tree.heading(column, 'command')
                if tree._sortable:
                    self.assertTrue(command, (tree, column))
                    tree.tk.call(command)
                else:
                    self.assertFalse(command)

    def test_condition_groups_and_module_slot_menu_roundtrip(self):
        self.app.clear()
        self.app.kind.set('stations')
        self.app.add_field()
        row = self.app.rows[-1]
        row.v_category.set('商品与舰船模组')
        row.change_category()
        keys = [self.gui.parse_field_label(v) for v in row.cb_field._raw_values]
        self.assertIn('modules', keys)
        self.assertNotIn('primary_economy', keys)
        row.field.set(self.gui.field_label('stations', 'modules'))
        row.val.set('Frame Shift Drive')
        row.v_slot.set('核心内部')
        with patch.object(self.gui.fo, 'get_options', return_value=['Frame Shift Drive', 'Beam Laser', 'Fuel Scoop']):
            row.refresh_options()
            deadline = time.monotonic() + 3
            while row._options != ['Frame Shift Drive'] and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
        self.assertEqual(row._options, ['Frame Shift Drive'])
        self.assertTrue(row.cb_slot.winfo_manager())
        condition = row.to_cond()
        self.assertEqual(condition['module_slot'], '核心内部')
        state = self.app._state_dict()
        self.app.set_language('en')
        self.assertEqual(row.to_cond(), condition)
        self.assertEqual(row.lbl_slot.cget('text'), 'Slot type')
        self.app._apply_state(state)
        restored = self.app.rows[0]
        self.assertEqual(restored.v_category.get(), '商品与舰船模组')
        self.assertEqual(restored.v_slot.get(), '核心内部')
        self.assertEqual(restored.to_cond(), condition)
        self.app._apply_state(dict(kind='stations', conditions=[condition]))
        self.assertEqual(self.app.rows[0].v_slot.get(), '核心内部')

    def test_main_result_columns_shrink_and_discounts_remain_separate(self):
        self.app.results = [dict(name='Jameson Memorial', system_name='Shinrarta Dezhra',
                                 modules=[dict(name='Frame Shift Drive', **{'class': 5, 'rating': 'A'})])]
        self.app._result_kind = 'stations'
        self.app._result_conditions = [dict(field='modules', op='=', text='Frame Shift Drive', discounted=True)]
        self.app.render_main_results()
        values = self.app.tree.item(self.app.tree.get_children()[0], 'values')
        self.assertEqual(values[-5:], ('Frame Shift Drive', '5', 'A', '10', 'Jameson Memorial'))
        self.app._result_conditions = []
        self.app.render_main_results()
        self.app.set_language('en')
        self.app.set_language('zh')
        self.assertEqual(tuple(self.app.tree['columns']), ('name', 'system'))
        self.assertEqual(len(self.app.tree.item(self.app.tree.get_children()[0], 'values')), 2)

    def test_csv_exports_condition_values_without_raw_json(self):
        self.app.set_language('en')
        row = dict(name='A', station_count=0, _distances={'Sol': 12.346}, body_data='x' * 10000,
                   _system_details=dict(counts={'station_count': 0}, neighbours=[{'name': 'Nearest'}]),
                   diagnostic='情况未知')
        self.app.results = [row]
        self.app._result_kind = 'systems'
        self.app._result_conditions = [dict(field='station_count'), dict(type='distance', ref_system='Sol')]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'results.csv')
            with patch.object(self.gui.filedialog, 'asksaveasfilename', return_value=path):
                self.app.export()
            with open(path, encoding='utf-8-sig', newline='') as file:
                csv_rows = list(csv.reader(file))
        from test_export_metadata import assert_provenance
        result_rows = assert_provenance(self, csv_rows, 3)
        exported = [dict(zip(result_rows[0], data)) for data in result_rows[1:]]
        self.assertEqual(exported[0]['Station count'], '0')
        self.assertEqual(exported[0]['Distance to Sol (ly)'], '12.35')
        self.assertNotIn('raw_json', result_rows[0])
        self.assertNotIn('distances_json', result_rows[0])
        from export_metadata import PROJECT_URL
        self.assertEqual(csv_rows[4][1], PROJECT_URL)
        from test_export_metadata import assert_english_csv
        assert_english_csv(self, csv_rows)

    def test_carrier_csv_has_provenance_footer(self):
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        self.app.set_language('en')
        self.app.carrier_parking_window()
        win = next(w for w in self.root.winfo_children() if getattr(w, '_raw_title', '') == '航母车位查找')
        widgets = list(descendants(win))
        tree = next(w for w in widgets if isinstance(w, self.gui.ttk.Treeview))
        tree.insert('', 'end', values=('Sol', '1.00', '2', '5', '航母类型数据不完整', '否', '3天前'))
        button = next(w for w in widgets if getattr(w, '_raw_text', '') == '导出 CSV')
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'carrier.csv')
            with patch.object(self.gui.filedialog, 'asksaveasfilename', return_value=path):
                button.invoke()
            with open(path, encoding='utf-8-sig', newline='') as file:
                rows = list(csv.reader(file))
        from test_export_metadata import assert_provenance
        assert_provenance(self, rows, len(rows[0]))
        from test_export_metadata import assert_english_csv
        assert_english_csv(self, rows)
        self.assertEqual(rows[7][0], 'Sol')

    def test_main_search_renders_prepared_evidence(self):
        import system_filters
        self.app.kind.set('systems')
        self.app._append_cond(dict(field='population', op='>', text=0))
        self.app._append_cond(dict(field='station_count', op='=', text=0))
        self.app._append_cond(dict(type='system_details', body_groups=[[
            dict(field='is_landable', op='=', value='true')]]))
        candidate = dict(name='Populated', population=100, stations=[])
        body = dict(name='Populated 1', type='Planet', is_landable=True)
        with patch.object(self.gui.eng, '_http_json', return_value={'count': 1, 'results': [candidate]}), \
                patch.object(system_filters.bodies, 'load_bodies', return_value={'populated': [body]}):
            self.app.run()
            deadline = time.monotonic() + 5
            while str(self.app.btn_run.cget('state')) != 'normal' and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.02)
        self.assertEqual(str(self.app.btn_run.cget('state')), 'normal')
        self.assertEqual(len(self.app.results), 1)
        items = self.app.tree.get_children()
        self.assertEqual(len(items), 1)
        rendered = self.app.tree.item(items[0], 'values')
        self.assertEqual(rendered[2], '0')
        self.assertIn('Populated 1', rendered[3])
        self.assertEqual(len(rendered), 4)
        self.assertNotIn('info', self.app.tree['columns'])
        self.app.clear()
        self.app._append_cond(dict(field='security', op='=', text='High'))
        self.app.set_language('en')
        self.assertEqual(self.app.tree.heading('value_2', 'text'), 'Station count')
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'snapshot.csv')
            with patch.object(self.gui.filedialog, 'asksaveasfilename', return_value=path):
                self.app.export()
            with open(path, encoding='utf-8-sig', newline='') as file:
                exported = list(csv.reader(file))[6:]
        self.assertIn('Station count', exported[0])
        self.assertNotIn('Security', exported[0])
        self.assertIn('Populated 1', '; '.join(exported[1]))
        self.assertEqual(list(self.app.tree.item(self.app.tree.get_children()[0], 'values')), exported[1])


if __name__ == '__main__':
    unittest.main()
