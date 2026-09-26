# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from pathlib import Path
import sys

root = Path(SPECPATH).parent
platform = 'win' if sys.platform == 'win32' else 'macosx' if sys.platform == 'darwin' else 'linux'

a = Analysis(
    [str(root / 'scripts' / 'entrypoint.py')],
    pathex=[str(root / 'src')],
    binaries=[],
    datas=collect_data_files('korea_war_alarm') + collect_data_files('plyer'),
    hiddenimports=collect_submodules('uvicorn') + collect_submodules('plyer.platforms.' + platform) + ['paho.mqtt.client'],
    hookspath=[],
    excludes=['pytest', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='kwa', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='kwa')
