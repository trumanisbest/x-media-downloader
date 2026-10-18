@echo off
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo [X] 未检测到 Python，请先安装 Python 3.8+ : https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% -c "import tkinter" >nul 2>nul || (
  echo [X] 当前 Python 缺少 tkinter，请重新运行 Python 安装程序，勾选 "tcl/tk and IDLE"。
  pause
  exit /b 1
)
%PY% -c "import gallery_dl" >nul 2>nul || (
  echo [*] 首次运行，正在安装下载引擎 gallery-dl，请稍候...
  %PY% -m pip install -U gallery-dl -i https://pypi.tuna.tsinghua.edu.cn/simple
  if errorlevel 1 %PY% -m pip install -U gallery-dl
)
%PY% x_media_downloader.py
pause
