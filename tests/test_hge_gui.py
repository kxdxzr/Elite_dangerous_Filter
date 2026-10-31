import gc
import os
import sys
import time
import unittest
from unittest.mock import patch

import hge_tool as tool
from test_hge_tool import NOW, system


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'Requires a GUI display')
class HgeGuiTests(unittest.TestCase):
    def setUp(self):
        import filter_gui as gui
        self.gui = gui
        self.patches = [patch.object(gui.fo, 'prefetch_common', lambda *a: None),
                        patch.object(gui.fo, 'get_options', return_value=[]),
                        patch.object(gui.App, 'restore_session', lambda *a: None)]
        for item in self.patches:
            item.start()
        self.root = gui.tk.Tk()
        self.root.withdraw()
        self.app = gui.App(self.root)
        self.app._closing = True
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(str(args[1]))

    def tearDown(self):
        for callback in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.tk.call('after', 'cancel', callback)
        self.root.destroy()
        gc.collect()
        for item in reversed(self.patches):
            item.stop()
        self.assertEqual(self.errors, [])

    def result(self):
        rows = [system(name='Candidate B'), system(name='Candidate A', id64=2)]
        for row in rows:
            row['_hge'] = tool.candidate(row, tool.Criteria(), NOW)
        return dict(rows=rows, scanned=3, total=3, notes=['候选分页已取完'],
                    fetched_at=NOW.isoformat(), criteria=tool.Criteria(), stopped=False, paused=False, error='')

    def wait(self, win):
        deadline = time.monotonic() + 4
        while win.search_state['busy'] and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(win.search_state['busy'])

    def test_readonly_dropdowns_no_export_and_language_session_roundtrip(self):
        win = self.app.hge_window()
        self.assertEqual(win.title(), 'HGE 可能星系查找器')
        for key in ('material', 'population', 'freshness'):
            self.assertEqual(str(win.control_widgets[key]['state']), 'readonly')
        self.assertFalse(hasattr(win, 'export_csv'))
        self.assertFalse(win.session_variables['require_manufactured_trader'].get())
        win.session_variables['require_manufactured_trader'].set(True)
        win.session_variables['material'].set('proto_radiolic')
        win.session_variables['population'].set('至少 1 亿')
        win.session_variables['freshness'].set('近 3 小时')
        before = win.criteria()
        self.app.set_language('en')
        self.assertEqual(win.title(), 'HGE candidate system finder')
        self.assertIn('Last 3 hours', win.control_widgets['freshness']['values'])
        self.assertEqual(win.criteria(), before)
        saved = self.app._state_dict()['tools']['hge']
        win.destroy()
        self.app._tool_states['hge'] = saved
        restored = self.app.hge_window()
        self.assertEqual(restored.criteria(), before)
        self.assertTrue(restored.criteria().require_manufactured_trader)

    def test_trader_checkbox_result_evidence_and_snapshot_column(self):
        win = self.app.hge_window()
        win.session_variables['require_manufactured_trader'].set(True)
        result = self.result()
        result['criteria'] = tool.Criteria(require_manufactured_trader=True)
        for row in result['rows']:
            row['_hge']['manufactured_trader'] = dict(name='Trade Port', material_trader='Manufactured')
        with patch.object(tool, 'search', return_value=result) as search:
            win.run_search()
            self.wait(win)
            self.assertTrue(search.call_args.args[0].require_manufactured_trader)
        self.assertIn('trader', win.result_tree['displaycolumns'])
        self.assertEqual(win.result_tree.set('0', 'trader'), 'Trade Port')
        win.session_variables['require_manufactured_trader'].set(False)
        self.app.set_language('en')
        self.assertEqual(win.control_widgets['require_manufactured_trader'].cget('text'),
                         'Target system has a Manufactured material trader')
        self.assertIn('trader', win.result_tree['displaycolumns'])
        self.assertTrue(win.search_state['result']['criteria'].require_manufactured_trader)

    def test_worker_search_sorted_copy_and_invalid_query_keeps_results(self):
        import hge_gui as ui
        win = self.app.hge_window()
        with patch.object(tool, 'search', return_value=self.result()) as search:
            win.run_search()
            self.wait(win)
            self.assertEqual(search.call_args.args[0], tool.Criteria())
        tree = win.result_tree
        tree.sort_by('name')
        first = tree.get_children()[0]
        self.assertEqual(tree.set(first, 'name'), 'Candidate A')
        tree.selection_set(first)
        self.assertTrue(win.copy_system())
        self.assertEqual(win.clipboard_get(), 'Candidate A')
        before = tuple(tree.get_children())
        win.session_variables['radius'].set('bad')
        with patch.object(ui.messagebox, 'showerror') as error:
            win.run_search()
            error.assert_called_once()
        self.assertEqual(tuple(tree.get_children()), before)
        self.app.set_language('en')
        self.assertIn('Verified candidates', win.status_variable.get())
        self.assertEqual(win.search_state['result']['criteria'], tool.Criteria())

    def test_network_partial_rows_and_invalid_saved_choices(self):
        self.app._tool_states['hge'] = dict(material='bad', population='bad', freshness='bad')
        win = self.app.hge_window()
        self.assertEqual(win.criteria(), tool.Criteria())
        result = self.result()
        result.update(paused=True, error='offline', notes=['网络暂时异常，已保留核实结果；可继续检索'])
        with patch.object(tool, 'search', return_value=result):
            win.run_search()
            self.wait(win)
        self.assertEqual(len(win.result_tree.get_children()), 2)
        before = len(self.app.localizer.callbacks)
        win.destroy()
        self.assertLess(len(self.app.localizer.callbacks), before)
