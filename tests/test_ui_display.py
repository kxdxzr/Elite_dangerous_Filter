from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import ui_display


PROJECT = Path(__file__).resolve().parents[1]


class DisplayBootstrapTests(unittest.TestCase):
    def test_manifest_declares_system_dpi_without_elevation(self):
        manifest = ET.parse(PROJECT / 'EliteDangerousFilter.manifest')
        self.assertEqual(manifest.find('.//{http://schemas.microsoft.com/SMI/2005/WindowsSettings}dpiAware').text, 'true')
        self.assertEqual(manifest.find('.//{http://schemas.microsoft.com/SMI/2016/WindowsSettings}dpiAwareness').text, 'system')
        level = manifest.find('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')
        self.assertEqual(level.attrib, dict(level='asInvoker', uiAccess='false'))
        self.assertIn('manifest=str(project / "EliteDangerousFilter.manifest")',
                      (PROJECT / 'EliteDangerousFilter.spec').read_text(encoding='utf-8'))

    def test_source_enables_dpi_before_windows_and_preserves_existing_awareness(self):
        api = Mock()
        with patch.object(ui_display.sys, 'platform', 'win32'), \
                patch.object(ui_display.sys, 'frozen', False, create=True), \
                patch.object(ui_display.ctypes, 'WinDLL', return_value=api, create=True), \
                patch.object(ui_display, 'process_dpi_awareness', side_effect=[0, 1]):
            self.assertEqual(ui_display.initialize_display(), 1)
            api.SetProcessDPIAware.assert_called_once_with()
        for existing in (1, 2):
            with patch.object(ui_display.sys, 'platform', 'win32'), \
                    patch.object(ui_display.ctypes, 'WinDLL', create=True) as load, \
                    patch.object(ui_display, 'process_dpi_awareness', return_value=existing):
                self.assertEqual(ui_display.initialize_display(), existing)
                load.assert_not_called()

    def test_frozen_mode_does_not_hide_a_missing_manifest_by_runtime_override(self):
        with patch.object(ui_display.sys, 'platform', 'win32'), \
                patch.object(ui_display.sys, 'frozen', True, create=True), \
                patch.object(ui_display.ctypes, 'WinDLL', create=True) as load, \
                patch.object(ui_display, 'process_dpi_awareness', return_value=0):
            self.assertEqual(ui_display.initialize_display(), 0)
            load.assert_not_called()

    def test_unsupported_platform_or_unavailable_api_is_safe(self):
        with patch.object(ui_display.sys, 'platform', 'linux'), \
                patch.object(ui_display.ctypes, 'WinDLL', create=True) as load:
            self.assertIsNone(ui_display.initialize_display())
            load.assert_not_called()
        with patch.object(ui_display.sys, 'platform', 'win32'), \
                patch.object(ui_display.sys, 'frozen', False, create=True), \
                patch.object(ui_display.ctypes, 'WinDLL', side_effect=OSError('Unavailable'), create=True):
            self.assertIsNone(ui_display.initialize_display())

    def test_font_prefers_cjk_ui_then_falls_back_without_bundling_fonts(self):
        self.assertEqual(ui_display.windows_ui_font(['Segoe UI', 'Microsoft YaHei UI'], 'native'), 'Microsoft YaHei UI')
        self.assertEqual(ui_display.windows_ui_font(['Segoe UI', 'Microsoft YaHei'], 'native'), 'Microsoft YaHei')
        self.assertEqual(ui_display.windows_ui_font(['Segoe UI'], 'native'), 'Segoe UI')
        self.assertEqual(ui_display.windows_ui_font([], 'native'), 'native')
