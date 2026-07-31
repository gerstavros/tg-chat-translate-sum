# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all

datas = [('package/src/tg_translate/assets', 'tg_translate/assets'), ('package/src/tg_translate/locales', 'tg_translate/locales')]
binaries = []
hiddenimports = ['customtkinter', 'PIL._tkinter_finder', 'telethon', 'cryptg', 'socks', 'openai', 'dotenv', 'vlc', 'PIL', 'cairosvg', 'tkinter', 'tkinter.messagebox', 'tkinter.simpledialog', 'tkinter.ttk', 'io', 're', 'threading', 'json']
datas += collect_data_files('customtkinter')
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['run.py'],
    pathex=['package/src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='tg-translate',
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
)
