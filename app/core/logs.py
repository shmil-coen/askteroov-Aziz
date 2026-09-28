# -*- coding: utf-8 -*-
"""
מערכת לוגים מרכזית — כתיבה לקובץ log.txt וגם פלט למסוף.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .config import LOGS_DIR


class EventLog:
    """לוג מרכזי שמפיץ אירועים למנויים (UI) וכותב לקובץ."""

    def __init__(self, log_dir: Path = LOGS_DIR):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"log_{stamp}.txt"
        self._subscribers: list[Callable[[str, str], None]] = []
        self._logger = logging.getLogger("askateroov")
        self._logger.setLevel(logging.DEBUG)
        if not self._logger.handlers:
            fh = logging.FileHandler(self.log_file, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            self._logger.addHandler(fh)
            sh = logging.StreamHandler()
            sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
            self._logger.addHandler(sh)

    # ------------------------------------------------------------------
    def flush(self) -> None:
        """מרוקן את ה-buffer של כל ה-handlers לדיסק — כדי שהלוג יישמר תמיד בפועל."""
        for h in self._logger.handlers:
            try:
                h.flush()
            except Exception:
                pass

    def subscribe(self, callback: Callable[[str, str], None]) -> None:
        """רישום מנוי: callback(level, message)."""
        self._subscribers.append(callback)

    def _emit(self, level: str, message: str) -> None:
        # flush בכל אירוע: בלי זה FileHandler אוגר בזיכרון וכותב לדיסק רק מדי פעם —
        # ואז הפעלה קצרה שנסגרת (או שנתקעת) משאירה קובץ לוג ריק/חלקי.
        self.flush()
        for cb in list(self._subscribers):
            try:
                cb(level, message)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def info(self, message: str) -> None:
        self._logger.info(message)
        self._emit("info", message)

    def success(self, message: str) -> None:
        self._logger.info(message)
        self._emit("success", message)

    def warn(self, message: str) -> None:
        self._logger.warning(message)
        self._emit("warning", message)

    def error(self, message: str) -> None:
        self._logger.error(message)
        self._emit("error", message)

    def raw(self, message: str) -> None:
        """פלט גולמי מתהליך חיצוני (בלי תחילית רמה)."""
        self._logger.debug(message.rstrip())
        self._emit("raw", message.rstrip())

    def export_summary(self, extra: str = "") -> Path:
        """כותב סיכום מפורש לסוף הלוג ומרוקן לדיסק."""
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 60 + "\n")
            f.write(f"סיכום הפעלה — {datetime.now().isoformat()}\n")
            if extra:
                f.write(extra + "\n")
        self.flush()
        return self.log_file


# לוג גלובלי
log = EventLog()
