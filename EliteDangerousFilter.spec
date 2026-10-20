# Build: python -m PyInstaller --noconfirm --clean EliteDangerousFilter.spec
from pathlib import Path

project = Path(SPECPATH)
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
                      "outfitting_snapshot"],
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
    disable_windowed_traceback=False,
)
