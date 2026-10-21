# Build: python -m PyInstaller --noconfirm --clean EliteDangerousFilter.spec
from pathlib import Path
import runpy
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct,
)

project = Path(SPECPATH)
# Read build metadata without importing the application, Tk or its runtime paths.
metadata = runpy.run_path(str(project / 'src' / 'app_metadata.py'))
fields = metadata['windows_version_fields']()
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=fields['filevers'], prodvers=fields['prodvers'],
                      mask=0x3f, flags=fields['flags'], OS=0x40004,
                      fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('040904B0', [
        StringStruct(key, value) for key, value in fields['strings'].items()
    ])]), VarFileInfo([VarStruct('Translation', [0x0409, 1200])])],
)
a = Analysis(
    [str(project / "src" / "filter_gui.py")],
    pathex=[str(project / "src")],
    binaries=[],
    datas=[(str(project / "LICENSE"), ".")],
    hiddenimports=["powerplay_gui", "powerplay_tool", "rare_goods", "exe_smoke_test", "exe_session_test",
                   "pve_gui", "pve_tool", "pve_access", "pve_cache", "res_systems", "faction_options", "i18n", "localized_tk",
                   "colonisation_gui", "colonisation_tool", "main_system_gui", "system_filters", "system_filter_fields",
                     "rare_neutron", "result_copy", "result_format", "search_progress", "export_metadata",
                     "engineer_shopping_gui", "engineer_shopping", "form_scroll",
                      "full_outfitting_gui", "full_outfitting", "outfitting_catalog", "outfitting_identity", "catalog_updates",
                       "outfitting_snapshot", "translations"] + [
        "translations." + path.stem for path in (project / "src" / "translations").glob("*.py")
        if path.stem != "__init__"
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EliteDangerousFilter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    manifest=str(project / "EliteDangerousFilter.manifest"),
    version=version_info,
    disable_windowed_traceback=False,
)
