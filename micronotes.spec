# -*- mode: python ; coding: utf-8 -*-
# Build: .venv/bin/pyinstaller --noconfirm micronotes.spec  ->  dist/micronotes.app

a = Analysis(
    ['micronotes.py'],
    pathex=[],
    binaries=[],
    datas=[('font/*.ttf', 'font'), ('assets/icon.png', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PySide6.QtNetwork', 'PySide6.QtQml', 'PySide6.QtQuick',
              'PySide6.QtWebEngineCore', 'PySide6.QtMultimedia', 'PySide6.QtPdf'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='micronotes',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='micronotes')
app = BUNDLE(
    coll,
    name='micronotes.app',
    icon='assets/micronotes.icns',
    bundle_identifier='app.micronotes',
    version='2.0.0',
    info_plist={
        'CFBundleDisplayName': 'Micronotes',
        'CFBundleName': 'Micronotes',
        'CFBundleShortVersionString': '2.0.0',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,  # allow Dark Mode
        'LSApplicationCategoryType': 'public.app-category.productivity',
    },
)
