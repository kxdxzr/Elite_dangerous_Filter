import os
import re
import sys
import csv
import gc
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch

import i18n
import filter_gui as gui


class TranslationTests(unittest.TestCase):
    def test_shared_action_labels_are_translated(self):
        for source, expected in (('查询', 'Search'), ('复制站名', 'Copy station name'), ('关闭', 'Close')):
            self.assertEqual(i18n.translate(source, 'en'), expected)
            self.assertEqual(i18n.translate(source, 'zh'), source)

    def test_all_literal_button_and_section_labels_have_english_translations(self):
        import ast
        folder = Path(__file__).resolve().parents[1] / 'src'
        for path in folder.glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                if not isinstance(node, ast.Call) or getattr(node.func, 'attr', '') not in (
                        'Button', 'Checkbutton', 'Radiobutton', 'LabelFrame'):
                    continue
                for keyword in node.keywords:
                    if keyword.arg == 'text' and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                        text = keyword.value.value
                        with self.subTest(file=path.name, line=node.lineno, text=text):
                            self.assertFalse(re.search(r'[\u3400-\u9fff]', i18n.translate(text, 'en')))

    def test_pve_new_labels_and_progress_are_english(self):
        for text in ('RES（星环推定）', '情况未知', '刷新数据并查询',
                     '获取配对与地点数据（优先有效缓存）…',
                     '按控制派系批量预筛选：Skyline Monopoly',
                     '按控制 Power 批量预筛选：Yuri Grom',
                     '控制 Power 分页：Yuri Grom；第 2 页；已读取 500 个星系',
                     '查询派系详情：12 个星系，最多 4 并发…',
                     '本地复核：138 条候选…', '显示结果：200/401',
                     '检索完成：137 条结果；耗时 0.13 秒',
                     '明确 RES：0；星环推定：78；情况未知：59；用时 0.13 s。 数据获取时间：2026-10-14 00:00:00；缓存命中 2/2。'):
            rendered = i18n.translate(text, 'en')
            self.assertFalse(re.search(r'[\u3400-\u9fff]', rendered), rendered)

    def test_operator_and_freshness_catalog(self):
        for value in gui.OP_LABELS + gui.FRESH_OPTS:
            translated = i18n.translate(value, 'en')
            self.assertFalse(re.search(r'[\u3400-\u9fff]', translated), translated)
            self.assertEqual(i18n.translate(value, 'zh'), value)

    def test_field_labels_preserve_api_keys(self):
        for kind, fields in [('stations', gui.STATION_FIELDS), ('systems', gui.SYSTEM_FIELDS)]:
            for key in fields:
                label = i18n.translate(gui.field_label(kind, key), 'en')
                self.assertFalse(re.search(r'[\u3400-\u9fff]', label), label)
                self.assertEqual(gui.parse_field_label(label), key)

    def test_names_and_arbitrary_inputs_are_not_translated(self):
        for value in ('Sol', 'Fuel Scoop', 'A. Lavigny-Duval', 'Izumo Heavy Industries Ltd', '5; 3'):
            self.assertEqual(i18n.translate(value, 'en'), value)

    def test_live_progress_and_validation_errors_are_english(self):
        for text in ('正在请求第1页 (每页500条)，已命中 7...',
                     '服务器直查第2页, 已扫 700, 命中 8 (有效率1%)...',
                     '7 个条件服务器直查 + 距离范围',
                     '第1条条件: 数字必须有限', '第2条条件: 新鲜度天数必须是正整数',
                     '服务器候选计数已封顶 (10000)，不代表全库总数',
                     '标准范围（未完成）', '大概率有靠近主星的车位',
                     'modules in [Fuel Scoop] [5级/B级] [数据7天内]', '距Sol0~50ly范围内',
                      'has_market=否由本地过滤 (服务器不支持)',
                     '航母车位查找', '航母类型数据不完整', '按已收录航母统计',
                     'Sol 周围 15 ly：扫描 51 个星系，显示 17 个；范围内分页已取完。航母数量未知 2 个。',
                     'Sol 周围 15 ly：扫描 51 个星系，显示 17 个；范围内分页已取完。站点数据未知 0 个。'):
            rendered = i18n.translate(text, 'en')
            self.assertFalse(re.search(r'[\u3400-\u9fff]', rendered), rendered)


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'Requires a GUI display')
class LocalizedGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import field_options as fo
        cls.patches = [patch.object(fo, 'prefetch_common', lambda *a: None),
                       patch.object(fo, 'get_options', lambda *a: []),
                       patch.object(gui.App, 'restore_session', lambda *a: None)]
        for item in cls.patches:
            item.start()
        cls.root = gui.tk.Tk()
        cls.root.withdraw()
        cls.app = gui.App(cls.root)
        cls.app._closing = True  # Never touch normal user sessions.
        cls.errors = []
        cls.root.report_callback_exception = lambda *a: cls.errors.append(str(a[1]))
        cls.app.add_distance()
        cls.app.add_field()
        row = cls.app.rows[1]
        row.field.set(gui.field_label('stations', 'modules'))
        row.val.set('Fuel Scoop')
        row.v_class.set('5')
        row.v_rating.set('B')
        row.v_fresh.set('近7天')
        row.refresh_options()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        for item in reversed(cls.patches):
            item.stop()

    def tearDown(self):
        self.root.update_idletasks()
        gc.collect()  # Dispose any closed Tk fixtures on the GUI thread.
        self.assertFalse(self.errors)

    def test_switch_preserves_query_and_raw_state(self):
        before = self.app._state_dict()
        self.app.set_language('en')
        after = self.app._state_dict()
        self.assertEqual(before['rows'], after['rows'])
        self.assertEqual(before['conditions'], after['conditions'])
        self.assertEqual(after['language'], 'en')
        self.assertIn('System / Station', self.root.title())
        row = self.app.rows[1]
        self.assertEqual(row.cb_op.cget('values')[0], 'Is one of')
        self.assertEqual(row.cb_op.get(), '属于其一')
        row.cb_op._display.set('Equals')  # Actual display edit/selection.
        self.assertEqual(row.op.get(), '等于')
        self.assertEqual(row.to_cond()['op'], '=')
        row.op.set('属于其一')
        self.app.set_language('zh')
        self.assertEqual(row.cb_op._display.get(), '属于其一')

    def test_open_tools_switch_and_pve_state(self):
        self.app.set_language('en')
        self.app.rare_goods_window()
        self.app.carrier_parking_window()
        self.app.midpoint_window()
        pve = self.app.pve_window()
        self.assertEqual(pve.title(), 'Pirate massacre finder')
        pve.session_variables['radius'].set('0')
        pve.session_variables['power_scope'].set('双方')
        before = self.app._state_dict()['tools']['pve']
        self.app.set_language('zh')
        self.assertEqual(pve.title(), '海盗任务查找器')
        self.assertEqual(before, self.app._state_dict()['tools']['pve'])
        self.app.set_language('en')
        # Scan actual visible labels/headings/status variables for incomplete English.
        unexpected = []
        def scan(widget):
            for key in ('text',):
                try:
                    text = str(widget.cget(key))
                    if text != '语言 / Language' and re.search(r'[\u3400-\u9fff]', text):
                        unexpected.append(text)
                except gui.tk.TclError:
                    pass
            if isinstance(widget, gui.ttk.Label):
                variable = widget.cget('textvariable')
                if variable:
                    text = str(widget.getvar(variable))
                    if re.search(r'[\u3400-\u9fff]', text):
                        unexpected.append(text)
            for child in widget.winfo_children():
                if isinstance(child, gui.ttk.Treeview) and 'ls' in child['columns']:
                    self.assertEqual(tuple(child['displaycolumns']), ('power', 'system', 'station', 'ly', 'ls', 'age'))
                    self.assertEqual(tuple(child['columns'])[:6], ('power', 'system', 'station', 'ly', 'ls', 'age'))
                scan(child)
        scan(self.root)
        self.assertEqual(unexpected, [])

    def test_new_widgets_and_result_rows_follow_language(self):
        self.app.set_language('en')
        label = gui.ttk.Label(self.root, text='就绪')
        self.assertEqual(label.cget('text'), 'Ready')
        label['text'] = '查询失败'
        self.assertEqual(label.cget('text'), 'Search failed')
        self.app.tree.set_columns(('name', 'status', 'permit', 'extra'))
        item = self.app.tree.insert('', 'end', values=('Sol', '未知', '免许可', ''))
        self.assertEqual(self.app.tree.item(item, 'values')[1], 'Unknown')
        self.app.set_language('zh')
        self.assertEqual(self.app.tree.item(item, 'values')[1], '未知')
        label.destroy()
        self.app.tree.delete(item)

    def test_res_mode_real_search_and_export_reuses_mission_source_column(self):
        import pve_gui
        from test_res_systems import system, ring
        self.app.set_language('en')
        win = self.app.pve_window()
        win.session_variables['min_factions'].set('0')
        win.session_variables['site_type'].set('任意 RES（允许星环推定）')
        win.session_variables['radius'].set('50')
        win.session_variables['target_controller'].set('Test Faction')
        win.session_variables['power'].set('')
        actual_search = pve_gui.tool.search
        pairs = {'Mission Source': dict(target='Known', x=0, y=0, z=0)}
        def offline_search(criteria, **kw):
            from test_pve_tool import page
            if 'resolver' in kw:
                return actual_search(criteria, **kw)
            return actual_search(criteria, **kw, resolver=lambda name: (name, (0, 0, 0), False),
                page_loader=lambda *args: page(),
                details_loader=lambda name: dict(controlling_minor_faction='Test Faction'),
                systems_loader=lambda *args: [system('No source', 1), system('Known', 20)],
                dataset_loader=lambda url: pairs if url == pve_gui.tool.PAIRS_URL else {},
                ring_loader=lambda names: {name.casefold(): ring() for name in names})
        def find_button(text):
            stack = [win]
            while stack:
                widget = stack.pop()
                if isinstance(widget, gui.ttk.Button) and widget.cget('text') == text:
                    return widget
                stack.extend(widget.winfo_children())
            self.fail('Button missing: ' + text)
        with patch.object(pve_gui.tool, 'search', side_effect=offline_search), \
                patch.object(pve_gui.messagebox, 'showerror') as errors:
            find_button('Search').invoke()
            deadline = time.monotonic() + 5
            while win.search_state['info'] is None and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
        self.assertIsNotNone(win.search_state['info'], errors.call_args)
        errors.assert_not_called()
        items = win.result_tree.get_children()
        self.assertEqual(len(items), 2)
        self.assertEqual(win.result_tree.item(items[0], 'values')[0], 'Mission Source')
        self.assertEqual(win.result_tree.item(items[1], 'values')[0], 'No data')
        self.assertEqual(win.result_tree.item(items[0], 'values')[7], 'Test Faction')
        self.assertEqual(win.result_tree.item(items[1], 'values')[7], '-')
        self.assertEqual(win.result_tree.item(items[1], 'values')[4], '-')
        with tempfile.TemporaryDirectory() as folder:
            output = str(Path(folder) / 'res.csv')
            with patch.object(pve_gui.filedialog, 'asksaveasfilename', return_value=output):
                find_button('Export CSV').invoke()
            with open(output, encoding='utf-8-sig', newline='') as file:
                records = list(csv.reader(file))
            data = [row for row in records if row and not row[0].startswith('#')]
            self.assertEqual(data[0][0], 'Mission source')
            self.assertEqual(data[-1][0], 'No data')
            self.assertEqual(data[-1][7], '-')
            self.assertEqual(data[-1][4], '-')
        win.session_variables['min_factions'].set('1')
        win.session_variables['target_controller'].set('')

    def test_res_mode_disables_mission_filters_preserves_drafts_and_localizes(self):
        self.app.set_language('zh')
        win = self.app.pve_window()
        variables = win.session_variables
        variables['min_factions'].set('0')
        variables['cnb_fallback'].set(True)
        variables['site_type'].set('仅 Low RES')
        variables['source_station_max_ls'].set('unfinished draft')
        variables['target_controller'].set('Test Faction')
        criteria = win.criteria()
        self.assertEqual(criteria.search_mode, 'expanded')
        self.assertTrue(criteria.cnb_fallback)
        self.assertEqual(criteria.site_type, 'low')
        self.assertEqual(criteria.min_factions, 0)
        self.assertEqual(criteria.source_station_max_ls, None)
        self.assertEqual(criteria.target_controller, 'Test Faction')
        self.assertEqual(str(win.control_widgets['min_factions']['state']), 'readonly')
        self.assertEqual(str(win.control_widgets['source_controller']['state']), 'disabled')
        self.assertEqual(str(win.control_widgets['target_controller']['state']), 'normal')
        self.app.set_language('en')
        self.assertEqual(win.control_widgets['site_type']._display.get(), 'Low RES only')
        self.assertEqual(win.criteria(), criteria)
        self.assertEqual(variables['source_station_max_ls'].get(), 'unfinished draft')
        snapshot = self.app._state_dict()['tools']['pve']
        self.app._tool_states['pve'] = snapshot
        win.destroy()
        restored = self.app.pve_window()
        self.assertEqual(restored.criteria(), criteria)
        restored.session_variables['min_factions'].set('8')
        self.assertEqual(str(restored.control_widgets['min_factions']['state']), 'readonly')
        self.assertEqual(restored.session_variables['min_factions'].get(), '8')
        # Leave subsequent GUI tests with a valid mission draft.
        restored.session_variables['source_station_max_ls'].set('')
        restored.session_variables['min_factions'].set('0')
        restored.session_variables['target_controller'].set('')

    def test_pve_import_search_export_and_copy_real_ui(self):
        import pve_gui
        import pve_tool
        from test_pve_tool import candidate, html_page
        self.app.set_language('en')
        window = self.app.pve_window()
        window.session_variables['radius'].set('50')
        window.session_variables['min_factions'].set('1')
        # This test owns its query; prior GUI tests may have changed preferences.
        for key in ('source_faction', 'source_controller', 'target_controller', 'power'):
            window.session_variables[key].set('')

        def button(text):
            def find(widget):
                for child in widget.winfo_children():
                    if isinstance(child, gui.ttk.Button) and child.cget('text') == text:
                        return child
                    result = find(child)
                    if result:
                        return result
            return find(window)

        def wait(predicate):
            deadline = time.monotonic() + 5
            while not predicate() and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertTrue(predicate())

        with tempfile.TemporaryDirectory() as folder:
            html = Path(folder) / 'pve.html'
            output = Path(folder) / 'pve.csv'
            html.write_text(html_page([candidate()]), encoding='utf-8')
            with patch.object(pve_gui.filedialog, 'askopenfilename', return_value=str(html)):
                button('Import PvE HTML').invoke()
                wait(lambda: window.search_state['page'] is not None)
            actual_search = pve_tool.search
            def offline_search(criteria, **kw):
                from test_pve_tool import DETAILS
                return actual_search(criteria, **kw, resolver=lambda name: (name, (0, 0, 0), False),
                                     details_loader=lambda name: DETAILS['Alpha'])
            with patch.object(pve_gui.tool, 'search', side_effect=offline_search):
                button('Search').invoke()
                wait(lambda: window.search_state['info'] is not None)
            self.assertEqual(window.search_state['rows'][0]['site'], 'RES Low')
            tree = window.result_tree
            tree.selection_set(tree.get_children()[0])
            with patch.object(window, 'clipboard_clear') as clear, patch.object(window, 'clipboard_append') as append:
                button('Copy target system').invoke()
                clear.assert_called_once()
                append.assert_called_once_with('Target')
            with patch.object(window, 'clipboard_clear'), patch.object(window, 'clipboard_append') as append:
                button('Copy mission source system').invoke()
                append.assert_called_once_with('Alpha')
            with patch.object(pve_gui.filedialog, 'asksaveasfilename', return_value=str(output)):
                button('Export CSV').invoke()
            with output.open(encoding='utf-8-sig', newline='') as file:
                rows = list(csv.reader(file))
            self.assertEqual(rows[6][0], 'Mission source')
            self.assertEqual(rows[7][:4], ['Alpha', 'Target', '20.00', 'RES Low'])
            from test_export_metadata import assert_provenance
            assert_provenance(self, rows, len(rows[0]))
            from test_export_metadata import assert_english_csv
            assert_english_csv(self, rows)
        self.app.set_language('zh')

    def test_pve_refresh_and_chunked_render_real_ui(self):
        import pve_gui
        from test_pve_tool import candidate
        self.app.set_language('en')
        window = self.app.pve_window()
        window.session_variables['min_factions'].set('1')
        def find(widget, text):
            for child in widget.winfo_children():
                if isinstance(child, gui.ttk.Button) and child.cget('text') == text:
                    return child
                result = find(child, text)
                if result:
                    return result
        rows = [dict(candidate(f'Source {n}'), site='RES（星环推定）') for n in range(401)]
        window.session_variables['source_pad'].set('L')
        window.session_variables['source_station_max_ls'].set('500')
        window.session_variables['target_ring_max_ls'].set('1500')
        info = dict(reference='Sol', mode='RES', scanned=401, complete=True, errors=[], notes=[],
                    confirmed_res=0, inferred_res=401, diagnostics={}, timings={'total': 0.1})
        window.search_state['page'] = {'imported': True}
        with patch.object(pve_gui.tool, 'search', return_value=(info, rows)) as search:
            find(window, 'Refresh data and search').invoke()
            deadline = time.monotonic() + 5
            while len(window.result_tree.get_children()) != 401 and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertEqual(len(window.result_tree.get_children()), 401)
            self.assertIsNone(window.search_state['page'])
            self.assertTrue(search.call_args.kwargs['refresh'])
            self.assertIsNone(search.call_args.kwargs['page'])
            self.assertEqual(search.call_args.args[0].source_pad, 'L')
            self.assertEqual(search.call_args.args[0].source_station_max_ls, 500)
            self.assertEqual(search.call_args.args[0].target_ring_max_ls, 1500)
            self.assertEqual(window.result_tree.item(window.result_tree.get_children()[0], 'values')[3],
                             'RES (inferred from rings)')
            self.assertEqual(str(find(window, 'Search').cget('state')), 'normal')
        for key in ('source_pad', 'source_station_max_ls', 'target_ring_max_ls'):
            window.session_variables[key].set('')
        window.destroy()

    def test_faction_boxes_async_choices_preserve_query_until_selected(self):
        import faction_options
        with patch.object(faction_options, 'suggest_factions', return_value=['Izumo Heavy Industries Ltd']):
            window = self.app.pve_window()
            window.session_variables['min_factions'].set('1')
            self.assertEqual(len(window.faction_boxes), 3)
            box = window.faction_boxes['source_controller']
            variable = window.session_variables['source_controller']
            variable.set('Izumo')
            # Invoke the same dropdown postcommand used by an actual click.
            box.tk.call(box.cget('postcommand'))
            deadline = time.monotonic() + 3
            while not box.cget('values') and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertEqual(tuple(box.cget('values')), ('Izumo Heavy Industries Ltd',))
            self.assertEqual(variable.get(), 'Izumo')
            box.set('Izumo Heavy Industries Ltd')
            box.event_generate('<<ComboboxSelected>>')
            self.assertEqual(variable.get(), 'Izumo Heavy Industries Ltd')
            self.app.set_language('en')
            self.assertEqual(variable.get(), 'Izumo Heavy Industries Ltd')
            self.assertEqual(window.faction_feedback.get(), '已选择完整名称')
            window.destroy()

    def test_faction_typing_paste_and_mouse_selection_without_opening_dropdown(self):
        import faction_options
        choices = ['Izumo Heavy Industries Ltd', 'Izumo Other Party']
        with patch.object(faction_options, 'suggest_factions', return_value=choices) as lookup:
            window = self.app.pve_window()
            window.session_variables['min_factions'].set('1')
            box = window.faction_boxes['source_controller']
            window.deiconify()
            window.lift()
            box.focus_force()
            self.root.update()
            box.delete(0, 'end')
            box.insert(0, 'Izumo')  # Actual display edit, not model.set/postcommand.
            popup = gui.SuggestPopup.inst()
            deadline = time.monotonic() + 4
            while not popup.visible_for(box) and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertTrue(popup.visible_for(box))
            self.assertEqual(window.session_variables['source_controller'].get(), 'Izumo')
            lookup.assert_called_with('Izumo')
            self.root.update()
            rect = popup.lb.bbox(1)
            popup.lb.event_generate('<ButtonPress-1>', x=5, y=rect[1] + 2)
            self.root.update()
            self.assertEqual(window.session_variables['source_controller'].get(), choices[1])
            self.assertFalse(popup.visible_for(box))
            # Simulate paste/IME writing the displayed variable, no KeyRelease.
            box.focus_force()
            self.root.update()
            box._display.set("People's")
            deadline = time.monotonic() + 4
            while (not lookup.call_args or lookup.call_args.args != ("People's",)) and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertEqual(lookup.call_args.args, ("People's",))
            self.app._tool_collectors.pop('pve', None)
            self.app._tool_states.pop('pve', None)
            window.destroy()
