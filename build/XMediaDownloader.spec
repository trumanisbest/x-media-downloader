# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 —— 产出桌面版目录 dist/XMediaDownloader/
  XMediaDownloader.exe  = 主程序（GUI，无黑框）
  gdl.exe               = 内置下载引擎（后台子进程，主程序以无窗方式调用）
"""

import os

block_cipher = None
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "build", "app.ico")
HOOKS = os.path.join(ROOT, "build")

common = dict(
    pathex=[ROOT],
    hookspath=[HOOKS],
    runtime_hooks=[],
    excludes=["PIL", "Pillow", "pytest", "numpy", "matplotlib", "IPython",
              "notebook", "pandas"],
    cipher=block_cipher,
    noarchive=False,
)

a_gui = Analysis(
    [os.path.join(ROOT, "x_media_downloader.py")],
    binaries=[],
    datas=[(ICON, ".")],
    hiddenimports=[],
    **common,
)

a_gdl = Analysis(
    [os.path.join(ROOT, "build", "gdl_entry.py")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    **common,
)

pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data, cipher=block_cipher)
pyz_gdl = PYZ(a_gdl.pure, a_gdl.zipped_data, cipher=block_cipher)

# console=False：主程序不弹黑框
exe_gui = EXE(
    pyz_gui, a_gui.scripts, [],
    exclude_binaries=True,
    name="XMediaDownloader",
    icon=ICON,
    console=False,
    disable_windowed_traceback=False,
)

# console=True：子进程必须挂到控制台子系统，否则 stdout 为 None 无法读日志
# （主程序用 STARTF_USESHOWWINDOW 隐藏它的窗口，用户看不到）
exe_gdl = EXE(
    pyz_gdl, a_gdl.scripts, [],
    exclude_binaries=True,
    name="gdl",
    icon=ICON,
    console=True,
)

coll = COLLECT(
    exe_gui, exe_gdl,
    a_gui.binaries, a_gui.datas,
    a_gdl.binaries, a_gdl.datas,
    strip=False,
    upx=False,
    name="XMediaDownloader",
)
