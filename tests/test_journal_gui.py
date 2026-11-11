import gc
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import journal_gui as ui
from journal_location import JournalLocation


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'Requires a GUI display')
class JournalGuiTests(unittest.TestCase):
    def setUp(self):
        import filter_gui as gui
        self.gui = gui
        self.patches = [patch.object(gui.fo, 'prefetch_common', lambda *a: None),
                        patch.object(gui.fo, 'get_options', return_value=[]),
                        patch.object(gui.App, 'restore_session', lambda *a: None)]
        for item in self.patches:
            item.start()
        self.temp = tempfile.TemporaryDirectory()
        self.root = gui.tk.Tk()
        self.root.withdraw()
        self.root._journal_directory = self.temp.name
        self.app = gui.App(self.root)
        self.app._closing = True
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(str(args[1]))
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        for callback in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.tk.call('after', 'cancel', callback)
        self.root.destroy()
        gc.collect()
        self.temp.cleanup()
        for item in reversed(self.patches):
            item.stop()
        self.assertEqual(self.errors, [])

    def pump(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(predicate())

    def descendants(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.descendants(child)

    def location(self, name='Colonia'):
        return JournalLocation(name, '2026-11-06T12:00:00Z', 'Journal.test.01.log')

    def test_buttons_in_all_tools_only_read_on_click(self):
        import edtools_snapshot
        with patch.object(edtools_snapshot, 'check', return_value=dict(status='recent')), \
                patch.object(ui.journal_location, 'read_current_system', return_value=self.location()) as read:
            for method in ('full_outfitting_window', 'pve_window', 'colonisation_window',
                           'engineer_shopping_window', 'waypoint_route_window', 'hge_window',
                           'carrier_parking_window', 'midpoint_window'):
                with self.subTest(tool=method):
                    before = read.call_count
                    existing = set(self.root.winfo_children())
                    win = getattr(self.app, method)()
                    if win is None:
                        win = next(w for w in self.root.winfo_children() if w not in existing)
                    buttons = [w for w in self.descendants(win) if hasattr(w, 'journal_variable')]
                    self.assertEqual(len(buttons), 1)
                    self.assertEqual(read.call_count, before)
                    button = buttons[0]
                    before = read.call_count
                    button.invoke()
                    self.pump(lambda: not button.journal_state['busy'])
                    self.assertEqual(read.call_count, before + 1)
                    self.assertEqual(button.journal_variable.get(), 'Colonia')
                    self.assertEqual(button.journal_state['location'].timestamp, self.location().timestamp)
                    win.destroy()
            row = self.gui.Row(self.root, 'systems', 'distance')
            button = next(w for w in self.descendants(row.frame) if hasattr(w, 'journal_variable'))
            button.invoke()
            self.pump(lambda: not button.journal_state['busy'])
            self.assertEqual(row.ref.get(), 'Colonia')
            row.destroy()

    def test_rare_goods_accepts_supported_system_only(self):
        before = set(self.root.winfo_children())
        self.app.rare_goods_window()
        win = next(w for w in self.root.winfo_children() if w not in before)
        button = next(w for w in self.descendants(win) if hasattr(w, 'journal_variable'))
        main_thread = threading.get_ident()
        def read(folder):
            self.assertNotEqual(threading.get_ident(), main_thread)
            return self.location('Ngurii')
        with patch.object(ui.journal_location, 'read_current_system', side_effect=read):
            button.invoke()
            self.pump(lambda: not button.journal_state['busy'])
            self.assertEqual(button.journal_variable.get(), 'Ngurii')

    def test_failure_preserves_input(self):
        var = self.gui.tk.StringVar(self.root, value='Sol')
        button = ui.current_system_button(self.root, var)
        with patch.object(ui.journal_location, 'read_current_system', side_effect=ValueError('bad record')), \
                patch.object(ui.messagebox, 'showerror') as error:
            button.invoke()
            self.pump(lambda: not button.journal_state['busy'])
            self.assertEqual(var.get(), 'Sol')
            error.assert_called_once()

    def test_user_edits_and_closed_window_discard_late_result(self):
        var = self.gui.tk.StringVar(self.root, value='Sol')
        def read(folder):
            self.release.wait(3)
            return self.location()
        with patch.object(ui.journal_location, 'read_current_system', side_effect=read):
            button = ui.current_system_button(self.root, var)
            button.invoke()
            var.set('User choice')
            self.release.set()
            self.pump(lambda: not button.journal_state['busy'])
            self.assertEqual(var.get(), 'User choice')
            self.release.clear()
            button.invoke()
            button.destroy()
            self.release.set()
            self.root.update()
            self.assertEqual(var.get(), 'User choice')

    def test_directory_selection_and_cancel(self):
        var = self.gui.tk.StringVar(self.root, value='Sol')
        self.root._journal_directory = str(Path(self.temp.name) / 'missing')
        button = ui.current_system_button(self.root, var)
        with patch.object(ui.filedialog, 'askdirectory', return_value=''), \
                patch.object(ui.journal_location, 'read_current_system') as read:
            button.invoke()
            read.assert_not_called()
            self.assertEqual(var.get(), 'Sol')
        with patch.object(ui.filedialog, 'askdirectory', return_value=self.temp.name), \
                patch.object(ui.journal_location, 'read_current_system', return_value=self.location()):
            button.invoke()
            self.pump(lambda: not button.journal_state['busy'])
            self.assertEqual(var.get(), 'Colonia')
            self.assertEqual(self.root._journal_directory, self.temp.name)

    def test_restricted_source_and_language(self):
        var = self.gui.tk.StringVar(self.root, value='Ngurii')
        button = ui.current_system_button(self.root, var, allowed_systems=('Ngurii',))
        self.app.set_language('en')
        self.assertEqual(button.cget('text'), 'Use current system')
        with patch.object(ui.journal_location, 'read_current_system', return_value=self.location()), \
                patch.object(ui.messagebox, 'showwarning') as warning:
            button.invoke()
            self.pump(lambda: not button.journal_state['busy'])
            self.assertEqual(var.get(), 'Ngurii')
            warning.assert_called_once()
