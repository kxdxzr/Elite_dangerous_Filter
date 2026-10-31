import os
import sys
import tkinter as tk
import unittest

from i18n import Localizer
from usage_help import usage_help


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'Requires a GUI display')
class UsageHelpTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.localizer = Localizer(self.root)

    def tearDown(self):
        self.root.destroy()

    def test_on_demand_reuse_translation_and_reopen(self):
        button = usage_help(self.root, ('缓存非实时；主要适用于 Bubble。',))
        self.assertFalse(any(isinstance(w, tk.Toplevel) for w in self.root.winfo_children()))
        window = button.open_help()
        self.assertIs(button.open_help(), window)
        self.localizer.set_language('en')
        self.assertEqual(button.cget('text'), 'Usage guide')
        self.assertEqual(window.title(), 'Usage guide')
        self.assertIn('Cached stock is not live', window.help_labels[0].cget('text'))
        window.destroy()
        reopened = button.open_help()
        self.assertIsNot(reopened, window)
        self.assertEqual(reopened.title(), 'Usage guide')

    def test_owner_destruction_closes_help(self):
        owner = tk.Toplevel(self.root)
        button = usage_help(owner, ('暂无缓存',), inline=True)
        window = button.open_help()
        owner.destroy()
        self.assertFalse(window.winfo_exists())
