# -*- mode: python ; coding: utf-8 -*-


from pathlib import Path


project_root = Path(SPECPATH)
assets_dir = project_root / "assets"
src_dir = project_root / "src"
icon_path = assets_dir / "onesauce_icon.png"
data_dir = src_dir / "onesauce_companion" / "data"
version_file = src_dir / "onesauce_companion" / "VERSION"
scripts_dir = project_root / "scripts"
conf_dir = project_root / "conf"

datas = [
    (str(assets_dir), "assets"),
    (str(data_dir), "onesauce_companion/data"),
    (str(version_file), "onesauce_companion"),
    (str(scripts_dir), "scripts"),
    (str(conf_dir), "conf"),
    (str(project_root / "LICENSE"), "."),
    (str(project_root / "THIRD_PARTY_NOTICES.md"), "."),
    (str(project_root / "licenses"), "licenses"),
]

analysis = Analysis(
    ["src/onesauce_companion/app.py"],
    pathex=[str(src_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=["onesauce_companion.data"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="OnesaUCECompanion",
    contents_directory=".onesauce_companion",
    icon=str(icon_path),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="OnesaUCECompanion",
)

