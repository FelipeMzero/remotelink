# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('core', 'core'), ('gui', 'gui')]
binaries = []
hiddenimports = ['tkinter', 'tkinter.ttk', 'tkinter.font', 'tkinter.messagebox', 'PIL._tkinter_finder', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFilter', 'PIL.ImageTk', 'mss', 'mss.windows', 'mss.linux', 'mss.darwin', 'pyautogui', 'pynput', 'pynput.mouse', 'pynput.keyboard', 'uuid', 'hashlib', 'ipaddress', 'zlib', 'struct']
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('mss')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyautogui')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'scipy', 'matplotlib', 'pandas', 'cv2', 'tensorflow', 'torch', 'pytest', 'unittest', 'doctest', 'pdb', 'IPython', 'notebook', 'setuptools', 'pip'],
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
    name='RemoteLink',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='c:\\Users\\Felipe Monteiro\\Documents\\anypy\\build\\version_info.txt',
    icon=['c:\\Users\\Felipe Monteiro\\Documents\\anypy\\assets\\icon.ico'],
)
