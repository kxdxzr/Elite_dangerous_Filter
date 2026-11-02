import gc
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'Requires GUI display')
class StreamingGuiTests(unittest.TestCase):
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
        self.release = threading.Event()
        self.finished = threading.Event()

    def tearDown(self):
        self.release.set()
        self.finished.wait(3)
        for callback in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.tk.call('after', 'cancel', callback)
        self.root.destroy()
        gc.collect()
        for item in reversed(self.patches):
            item.stop()
        self.assertEqual(self.errors, [])

    def pump_until(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.root.update()
        self.assertTrue(predicate())

    def test_main_renders_before_search_returns_and_reconciles_without_duplicates(self):
        def search(*args, on_results, **kwargs):
            try:
                first, second = dict(name='First', id64=1), dict(name='Second', id64=2)
                on_results([first])
                self.release.wait(4)
                on_results([second])
                return [first, second], 2, 2
            finally:
                self.finished.set()
        with patch.object(self.app, 'collect', return_value=[]), \
                patch.object(self.gui.messagebox, 'askyesno', return_value=True), \
                patch.object(self.gui.eng, 'search', side_effect=search):
            self.app.kind.set('systems')
            self.app.run()
            self.pump_until(lambda: len(self.app.tree.get_children()) == 1)
            self.assertFalse(self.finished.is_set())
            self.assertEqual(self.app.results[0]['name'], 'First')
            self.app.set_language('en')
            self.assertEqual(len(self.app.tree.get_children()), 1)
            self.release.set()
            self.pump_until(lambda: str(self.app.btn_run['state']) == 'normal')
        self.assertEqual(len(self.app.tree.get_children()), 2)
        self.assertEqual([r['name'] for r in self.app.results], ['First', 'Second'])

    def test_colony_renders_before_final_info_exists(self):
        import colonisation_tool as colony
        def search(*args, on_results, **kwargs):
            try:
                row = dict(name='First', _top_scan_planets=[], _top_scan_complete=False,
                           _neighbour='', _neighbour_distance=None, _body_matches='',
                           _ring_matches='', _relations='')
                on_results([row])
                self.release.wait(4)
                return dict(scanned=1, total=1, complete=True, unknown=0,
                            reason='Candidate pages exhausted.', value_field='estimated_scan_value'), [row]
            finally:
                self.finished.set()
        with patch.object(colony, 'search', side_effect=search):
            win = self.app.colonisation_window()
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            widgets = list(descendants(win))
            button = next(w for w in widgets if isinstance(w, self.gui.ttk.Button) and w.cget('text') == '查询')
            tree = next(w for w in widgets if isinstance(w, self.gui.ttk.Treeview))
            button.invoke()
            self.pump_until(lambda: len(tree.get_children()) == 1)
            self.assertFalse(self.finished.is_set())
            self.release.set()
            self.pump_until(lambda: str(button['state']) == 'normal')
            self.assertEqual(len(tree.get_children()), 1)
