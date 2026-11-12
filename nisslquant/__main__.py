# -*- coding: utf-8 -*-
"""包入口：python -m nisslquant 启动图形界面。"""
import sys


def main() -> int:
    if sys.platform == "win32":
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    from nisslquant.gui.app import App
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
