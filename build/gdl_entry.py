#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包版内置的下载引擎启动器（无窗口后台进程）

桌面版主程序会以子进程方式调用它，等价于命令行执行 `gallery-dl ...`。
输出全部走 stdout（主程序设置了 PYTHONUNBUFFERED，实时读取）。
"""
import sys

try:
    from gallery_dl import main as gdl_main
except Exception as exc:  # noqa: BLE001
    sys.stderr.write("gallery-dl not available: %s\n" % exc)
    sys.exit(90)

if __name__ == "__main__":
    try:
        sys.exit(gdl_main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        sys.stderr.write("gdl launcher crashed: %s\n" % exc)
        sys.exit(91)
