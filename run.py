# -*- coding: utf-8 -*-
"""
Launcher — מוסיף את שורש הפרויקט ל-sys.path ומריץ את האפליקציה.
נדרש כי ה-Python הניידת משתמשת ב-python312._pth שמתעלם מ-CWD ומ-PYTHONPATH.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
