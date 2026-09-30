# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

# Collect all assets recursively
assets_dir = Path('assets')
assets_datas = []
exclude_extensions = {'.ase', '.aseprite'}
for f in assets_dir.rglob('*'):
    if f.is_file() and f.suffix.lower() not in exclude_extensions:
        rel = f.relative_to(assets_dir.parent)
        assets_datas.append((str(f), str(rel.parent)))

a = Analysis(
    ['game.py'],
    pathex=['.'],
    binaries=[],
    datas=assets_datas,
    hiddenimports=[
        'PIL',
        'PIL._imaging',
        'PIL.Image',
        'queue',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Grote ongebruikte packages
        'numpy',
        'scipy',
        'matplotlib',
        'pandas',
        # Build/packaging artefacts
        'setuptools',
        'wheel',
        'pip',
        'pkg_resources',
        'distutils',
        'jinja2',
        'lib2to3',
        # Windows-specific onnodig
        'win32com',
        'pythoncom',
        # PyInstaller internals
        'pyinstaller',
        'pyinstaller_hooks_contrib',
        'altgraph',
        'markupsafe',
        # Alleen het losse standalone serverscript. De serverlogica zelf
        # (src.network.server_game) moet er wel in blijven: HOST SERVER start
        # een ServerIO in hetzelfde proces en die importeert ServerGame op
        # regel 88 van network.py. Uitgesloten zijn betekende dat de knop in
        # de verpakte game ModuleNotFoundError gaf.
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GUNK',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/textures/ui/icon.ico',
)

# Alleen de scripts en de PYZ zitten in de exe. De DLL's, de assets en de
# rest gaan via COLLECT naar _internal\ en assets\, zoals PyInstaller het
# standaard ook doet. Stuur je ze ook mee aan EXE, dan worden ze dubbel
# opgeslagen: een keer in GUNK.exe en een keer op schijf.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GUNK',
)
