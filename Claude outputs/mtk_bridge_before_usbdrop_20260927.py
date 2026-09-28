# -*- coding: utf-8 -*-
"""
גשר ל-mtkclient — גרסת מרכז שליטה.

עקרון מכונן: אין כאן תור עבודות או הרצות אוטומטיות.
כל פעולה יוצרת בקשה; רק אישור מפורש של המשתמש מריץ אותה.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from .config import MTK_SCRIPT, PYTHON_EXE
from .logs import log


class MtkCommand:
    """ייצוג פקודת mtk.py — הרצה רק לאחר אישור מפורש."""

    def __init__(self, args: list[str]):
        if PYTHON_EXE is None or not MTK_SCRIPT.is_file():
            raise RuntimeError(
                "mtkclient לא נמצא. הגדר ASKATEROOV_PYTHON_ROOT או ודא ש-MTKCliantPortable קיים."
            )
        self.args = args
        self.process: Optional[subprocess.Popen] = None
        self.returncode: Optional[int] = None
        self._stop_flag = threading.Event()
        self._fail = False           # התגלה סמן כישלון בפלט (גם אם קוד היציאה 0)
        self._fail_reason = ""
        self._saw_device = False      # "Device detected" — כדי לא לסמן כשל על handshake שהצליח בסוף
        self._saw_handshake_fail = False

    def _build_env(self) -> dict:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def start(self,
              on_output: Optional[Callable[[str], None]] = None,
              on_progress: Optional[Callable[[float, str], None]] = None) -> threading.Thread:
        """מפעיל את הפקודה ברקע. נקרא רק על ידי מנהל האישורים."""

        def run():
            cmd = [str(PYTHON_EXE), str(MTK_SCRIPT)] + self.args
            log.info(f"רץ: mtk {' '.join(self.args)}")
            try:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                self.process = subprocess.Popen(
                    cmd,
                    cwd=str(MTK_SCRIPT.parent),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=self._build_env(),
                    creationflags=flags,
                )
            except OSError as e:
                log.error(f"הפעלת mtk נכשלה: {e}")
                self.returncode = -1
                return

            assert self.process and self.process.stdout
            try:
                for line in self.process.stdout:
                    if self._stop_flag.is_set():
                        break
                    line = line.rstrip("\n\r")
                    if not line:
                        continue
                    self._inspect_line(line)
                    if on_output:
                        on_output(line)
                    if on_progress:
                        pct, suffix = parse_progress_line(line)
                        if pct is not None:
                            on_progress(pct, suffix)
            except (ValueError, OSError):
                pass   # ה-pipe נסגר עקב ביטול — יציאה נקייה
            try:
                self.process.wait(timeout=5)
            except Exception:
                pass
            if self._stop_flag.is_set():
                self.returncode = -2
                log.warn("הפקודה הופסקה על ידי המשתמש")
                return
            rc = self.process.returncode
            # mtkclient מחזיר לעיתים קוד 0 גם כשהפעולה נכשלה — לכן בודקים גם את הפלט
            if self._saw_handshake_fail and not self._saw_device:
                self._fail = True
                self._fail_reason = self._fail_reason or "החיבור למכשיר נכשל (Handshake)"
            if rc == 0 and self._fail:
                log.error(f"הפעולה נכשלה למרות קוד יציאה 0: {self._fail_reason}")
                rc = 1
            self.returncode = rc
            (log.success if rc == 0 else log.error)(
                f"mtk הסתיים עם קוד {rc}"
            )

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t

    def reset(self):
        """מאפס את הפקודה לניסיון חוזר (תהליך חדש, ללא דגל עצירה)."""
        self.process = None
        self.returncode = None
        self._stop_flag = __import__('threading').Event()
        self._fail = False
        self._fail_reason = ""
        self._saw_device = False
        self._saw_handshake_fail = False

    def stop(self):
        """עוצר מיד — הורג את כל עץ התהליך ומשחרר את קורא הפלט (ביטול מהיר)."""
        self._stop_flag.set()
        proc = self.process
        if proc is not None and proc.poll() is None:
            killed = False
            if os.name == "nt":
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
                    killed = True
                except Exception:
                    killed = False
            if not killed:
                try:
                    proc.kill()
                except OSError:
                    pass
        # שחרור מיידי של ה-thread הקורא, שלא ייתקע על pipe מת
        try:
            if proc is not None and proc.stdout is not None:
                proc.stdout.close()
        except Exception:
            pass

    @property
    def stopped(self) -> bool:
        return self._stop_flag.is_set()

    # סמני כישלון ודאיים בפלט mtkclient (גם כשקוד היציאה 0)
    _FAIL_MARKERS = (
        "unrecognized arguments",
        "error:",
        "Traceback (most recent call last)",
        "Errno",
        "Please disconnect, start mtkclient and reconnect",
        "No preloader given",
        "is not supported",
    )

    def _inspect_line(self, line: str):
        low = line.lower()
        if "device detected" in low:
            self._saw_device = True
        if "handshake failed" in low:
            self._saw_handshake_fail = True
        for marker in self._FAIL_MARKERS:
            if marker.lower() in low:
                self._fail = True
                if not self._fail_reason:
                    self._fail_reason = line.strip()
                break

    @property
    def needs_reconnect(self) -> bool:
        """הכשל הוא מסוג 'נתק וחבר מחדש' (המכשיר תקוע/לא במצב BROM טרי)."""
        r = (self._fail_reason or "").lower()
        return ("reconnect" in r or "please disconnect" in r
                or (self._saw_handshake_fail and not self._saw_device))

    def describe(self) -> str:
        """מחרוזת הפקודה לתצוגה בחלון האישור."""
        return "mtk " + " ".join(self.args)

    def run_blocking(self,
                     on_output: Optional[Callable[[str], None]] = None,
                     on_progress: Optional[Callable[[float, str], None]] = None) -> int:
        """מריץ ומחכה לסיום (לשימוש מתוך thread רקע). מחזיר קוד יציאה."""
        self.start(on_output, on_progress).join()
        if self.returncode is None:
            self.returncode = -1
        return self.returncode


# ---------------------------------------------------------------------- עזרי פלט

_PROGRESS_RE = re.compile(r"(?P<pct>\d{1,3}(?:\.\d+)?)\s*%\s*(?P<suffix>.*)")


def parse_progress_line(line: str) -> tuple[Optional[float], str]:
    """מחלץ אחוז התקדמות משורת פלט ('12.3% ...')."""
    m = _PROGRESS_RE.search(line)
    if not m:
        return None, ""
    try:
        pct = float(m.group("pct"))
    except ValueError:
        return None, ""
    if 0 <= pct <= 100:
        return pct, m.group("suffix").strip()
    return None, ""


# ---------------------------------------------------------------------- בוני פקודות


class MtkCommands:
    """מחולל ארגומנטים לפקודות mtk — בונים בקשות, לא מריצים."""

    COMMON = ["--noreconnect"]

    @classmethod
    def _common_args(cls, preloader: Optional[str] = None, auth: Optional[str] = None,
                     noreconnect: bool = True) -> list[str]:
        # --noreconnect נתמך ברוב הפקודות, אך לא בכולן (gettargetconfig,
        # dumppreloader לא מכירות אותו) — לכן ניתן לכבות אותו לפי הפקודה.
        args = list(cls.COMMON) if noreconnect else []
        if preloader:
            args += ["--preloader", preloader]
        if auth:
            args += ["--auth", auth]
        return args

    # ------------------------------ זיהוי
    @classmethod
    def printgpt(cls, **kw) -> MtkCommand:
        # ללא --noreconnect: כך המכשיר מתאפס נקי בסיום, ושאיבה/צריבה אחריו
        # מבצעות handshake מלא (קוראות meid) במקום לקרוס על מכשיר שנשאר במצב DA.
        return MtkCommand(["printgpt"] + cls._common_args(noreconnect=False, **kw))

    @classmethod
    def gettargetconfig(cls, **kw) -> MtkCommand:
        # gettargetconfig אינו מקבל --noreconnect בגרסת mtkclient זו
        return MtkCommand(["gettargetconfig"] + cls._common_args(noreconnect=False, **kw))

    # ------------------------------ שאיבה
    @classmethod
    def read_partition(cls, partition: str, output: Path, **kw) -> MtkCommand:
        # ללא --noreconnect: אם המכשיר נפל, mtk ימתין שיחזור במקום לנטוש מיד
        return MtkCommand(["r", partition, str(output)]
                          + cls._common_args(noreconnect=False, **kw))

    @classmethod
    def read_preloader(cls, output: Path, **kw) -> MtkCommand:
        # dumppreloader אינו מקבל --noreconnect בגרסת mtkclient זו
        return MtkCommand(["dumppreloader", "--filename", str(output)]
                          + cls._common_args(noreconnect=False, **kw))

    @classmethod
    def read_full(cls, output: Path, **kw) -> MtkCommand:
        return MtkCommand(["rf", str(output)] + cls._common_args(**kw))

    @classmethod
    def read_all(cls, outdir: Path, **kw) -> MtkCommand:
        return MtkCommand(["rl", str(outdir)] + cls._common_args(noreconnect=False, **kw))

    # ------------------------------ צריבה
    @classmethod
    def write_partition(cls, partition: str, image: Path, **kw) -> MtkCommand:
        return MtkCommand(["w", partition, str(image)] + cls._common_args(**kw))

    # ------------------------------ מחיקה
    @classmethod
    def erase_partition(cls, partition: str, **kw) -> MtkCommand:
        return MtkCommand(["e", partition] + cls._common_args(**kw))

    # ------------------------------ bootloader
    @classmethod
    def seccfg(cls, flag: str, **kw) -> MtkCommand:
        flag = flag.lower()
        assert flag in ("unlock", "lock")
        return MtkCommand(["da", "seccfg", flag] + cls._common_args(**kw))
