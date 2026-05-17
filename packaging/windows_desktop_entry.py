
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_app_root_on_sys_path() -> None:
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
        root = Path(__file__).resolve().parent.parent
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    os.chdir(root)


def main() -> None:
    _ensure_app_root_on_sys_path()
    from gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
