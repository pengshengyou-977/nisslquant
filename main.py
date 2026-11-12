# -*- coding: utf-8 -*-
"""NisslQuant 启动入口。

双击 exe 或运行 python main.py 均进入图形界面；
带 --cli 参数时进入批处理模式（需提供工程文件）。
"""
from __future__ import annotations

import os
import sys


def _dpi_aware() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main() -> int:
    _dpi_aware()
    if "--cli" in sys.argv:
        from nisslquant.cli import run_cli
        return run_cli(sys.argv[1:])

    from nisslquant.gui.app import App
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
