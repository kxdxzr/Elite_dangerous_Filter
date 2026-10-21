from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app_metadata import PROJECT_AUTHOR, PROJECT_NAME, PROJECT_VERSION, windows_version_fields
import export_metadata


PROJECT = Path(__file__).resolve().parents[1]


class ExeVersionTests(unittest.TestCase):
    def test_build_resource_uses_the_same_metadata_without_build_dependencies(self):
        # Execute the actual spec with inert constructors: no PyInstaller/Tk needed.
        modules = {name: ModuleType(name) for name in
                   ('PyInstaller', 'PyInstaller.utils', 'PyInstaller.utils.win32',
                    'PyInstaller.utils.win32.versioninfo')}
        versioninfo = modules['PyInstaller.utils.win32.versioninfo']
        for name in ('VSVersionInfo', 'FixedFileInfo', 'StringFileInfo', 'StringTable',
                     'StringStruct', 'VarFileInfo', 'VarStruct'):
            setattr(versioninfo, name, Mock(side_effect=lambda *args, **kw: SimpleNamespace(args=args, **kw)))
        analysis = SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
        exe = Mock()
        with patch.dict(sys.modules, modules):
            result = runpy.run_path(str(PROJECT / 'EliteDangerousFilter.spec'), init_globals=dict(
                SPECPATH=str(PROJECT), Analysis=Mock(return_value=analysis), PYZ=Mock(), EXE=exe))
        resource = result['version_info']
        self.assertIs(exe.call_args.kwargs['version'], resource)
        expected = windows_version_fields()
        self.assertEqual(resource.ffi.filevers, expected['filevers'])
        self.assertEqual(resource.ffi.prodvers, resource.ffi.filevers)
        self.assertEqual(resource.ffi.flags, expected['flags'])
        strings = dict(call.args for call in versioninfo.StringStruct.call_args_list)
        self.assertEqual(strings['FileVersion'], '.'.join(map(str, resource.ffi.filevers)))
        self.assertEqual(strings['ProductVersion'], PROJECT_VERSION)
        self.assertEqual(strings['ProductName'], PROJECT_NAME)
        self.assertEqual(strings['CompanyName'], PROJECT_AUTHOR)
        self.assertEqual(strings['OriginalFilename'], 'EliteDangerousFilter.exe')

    def test_csv_metadata_remains_backwards_compatible(self):
        self.assertEqual(export_metadata.PROJECT_VERSION, PROJECT_VERSION)
        self.assertEqual(export_metadata.PROJECT_NAME, PROJECT_NAME)
        self.assertEqual(export_metadata.PROJECT_AUTHOR, PROJECT_AUTHOR)

    def test_prerelease_version_and_numeric_windows_fields(self):
        fields = windows_version_fields('1.2.3-beta.4')
        self.assertEqual(fields['filevers'], (1, 2, 3, 0))
        self.assertEqual(fields['flags'], 0x2)
        self.assertEqual(fields['strings']['ProductVersion'], '1.2.3-beta.4')
        self.assertEqual(windows_version_fields('1.2.3+build.4')['flags'], 0)

    def test_invalid_or_out_of_range_versions_fail_before_building(self):
        for version in ('v1.2.3', '1.2', '1.2.3.4', '65536.0.0', '1.2.3-', ''):
            with self.subTest(version=version), self.assertRaises(ValueError):
                windows_version_fields(version)
