# -*- coding: utf-8 -*-
"""
גשר ל-fastboot (platform-tools של Google).

Fastboot הוא פרוטוקול נפרד מ-mtkclient: הוא רץ על ה-bootloader של המכשיר
(לא ב-BROM/Preloader) ומריץ את fastboot.exe. המחלקה כאן חושפת את אותו ממשק
כמו MtkCommand (start/run_blocking/stop/reset/describe) כדי שתתאים ישירות
ל-Step ו-JobManager הקיימים.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .config import find_fastboot_exe
from .logs import log


class FastbootCommand:
    """פקודת fastboot יחידה — רצה רק לאחר אישור מפורש (דרך JobManager)."""

    # כמה זמן לחכות למכשיר במצב Fastboot ("< waiting for any device >") לפני דיווח "אין מכשיר"
    DEVICE_TIMEOUT = 45.0

    def __init__(self, args: list[str], require: str = ""):
        exe = find_fastboot_exe()
        if exe is None:
            raise RuntimeError(
                "fastboot.exe לא נמצא. שים את תיקיית platform-tools ליד התיקייה הניידת, "
                "או בחר את הקובץ ידנית בלשונית Fastboot, או הגדר ASKATEROOV_FASTBOOT.")
        self.exe = exe
        self.args = args
        self.require = require        # regex שחייב להופיע בפלט כדי להיחשב הצלחה
        self._out = []
        self.process: Optional[subprocess.Popen] = None
        self.returncode: Optional[int] = None
        self._stop_flag = threading.Event()
        self.no_device = False          # לא נמצא מכשיר במצב Fastboot
        self._waiting = threading.Event()

    # ------------------------------------------------------------------
    def reset(self):
        """מאפס לניסיון חוזר (תהליך חדש, ללא דגל עצירה)."""
        self.process = None
        self.returncode = None
        self._out = []
        self._stop_flag = threading.Event()
        self.no_device = False
        self._waiting = threading.Event()

    def _device_watchdog(self, on_progress):
        """fastboot ממתין לנצח למכשיר — כאן מגבילים את ההמתנה ומדווחים 'אין מכשיר'."""
        proc = self.process
        while proc is not None and proc.poll() is None and not self._stop_flag.is_set():
            if self._waiting.wait(timeout=0.5):
                break
        else:
            return
        t0 = time.monotonic()
        log.warn(f"לא נמצא מכשיר במצב Fastboot — ממתין לחיבור עד {int(self.DEVICE_TIMEOUT)} שניות…")
        if on_progress:
            try:
                on_progress(0.0, f"ממתין למכשיר במצב Fastboot (עד {int(self.DEVICE_TIMEOUT)} שניות)…")
            except Exception:
                pass
        while proc.poll() is None and not self._stop_flag.is_set():
            if not self._waiting.is_set():
                return   # המכשיר התחבר — fastboot ממשיך לבד
            if time.monotonic() - t0 >= self.DEVICE_TIMEOUT:
                self.no_device = True
                log.error(f"לא נמצא מכשיר במצב Fastboot תוך {int(self.DEVICE_TIMEOUT)} שניות")
                try:
                    proc.kill()
                except OSError:
                    pass
                try:
                    if proc.stdout is not None:
                        proc.stdout.close()   # משחרר את קורא הפלט מיד
                except Exception:
                    pass
                return
            time.sleep(0.5)

    def stop(self):
        """עוצר מיד — הורג את התהליך."""
        self._stop_flag.set()
        proc = self.process
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    def describe(self) -> str:
        return "fastboot " + " ".join(self.args)

    def _build_env(self) -> dict:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def start(self,
              on_output: Optional[Callable[[str], None]] = None,
              on_progress: Optional[Callable[[float, str], None]] = None) -> threading.Thread:

        def run():
            cmd = [str(self.exe)] + self.args
            log.info(f"רץ: {self.describe()}")
            try:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                self.process = subprocess.Popen(
                    cmd,
                    cwd=str(self.exe.parent),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,  # fastboot כותב הרבה ל-stderr — ממזגים
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=self._build_env(),
                    creationflags=flags,
                )
            except OSError as e:
                log.error(f"הפעלת fastboot נכשלה: {e}")
                self.returncode = -1
                return

            if self._stop_flag.is_set():   # בוטל בזמן שהתהליך עוד עלה — לא משאירים אותו רץ
                try:
                    self.process.kill()
                except OSError:
                    pass
                self.returncode = -2
                log.warn("הפקודה הופסקה על ידי המשתמש")
                return
            assert self.process and self.process.stdout
            threading.Thread(target=self._device_watchdog, args=(on_progress,),
                             daemon=True).start()
            try:
                for line in self.process.stdout:
                    if self._stop_flag.is_set():
                        break
                    line = line.rstrip("\n\r")
                    if not line:
                        continue
                    if "waiting for" in line.lower() and "device" in line.lower():
                        self._waiting.set()
                    elif self._waiting.is_set():
                        self._waiting.clear()   # המכשיר ענה
                    self._out.append(line)
                    if on_output:
                        on_output(line)
                    if on_progress:
                        pct, suffix = _parse_progress(line)
                        if pct is not None:
                            on_progress(pct, suffix)
            except (ValueError, OSError, RuntimeError):
                pass   # ה-pipe נסגר (אין מכשיר / ביטול) — יציאה נקייה

            self.process.wait()
            if self._stop_flag.is_set():
                self.returncode = -2
                log.warn("הפקודה הופסקה על ידי המשתמש")
                return
            rc = self.process.returncode
            joined = "\n".join(self._out)
            low = joined.lower()
            # "< waiting for any device >" אינו כשל בפני עצמו: אם המכשיר התחבר בזמן ההמתנה
            # הפקודה ממשיכה ומצליחה. "אין מכשיר" מטופל ב-no_device (שומר הזמן).
            fail_markers = ("failed", "error:", "no devices/emulators found",
                            "cannot load", "not found")
            fail = any(m in low for m in fail_markers)
            if self.require and not re.search(self.require, joined, re.IGNORECASE):
                fail = True
                if self.args[:1] == ["devices"]:
                    self.no_device = True   # 'fastboot devices' בלי שורת מכשיר
            if "no devices/emulators found" in low:
                self.no_device = True
            if self.no_device:
                rc = rc or 1
            if rc == 0 and fail:
                log.error("fastboot: הפעולה לא הצליחה (אין מכשיר / שגיאה בפלט)")
                rc = 1
            self.returncode = rc
            (log.success if rc == 0 else log.error)(
                f"fastboot הסתיים עם קוד {rc}")

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t

    def run_blocking(self,
                     on_output: Optional[Callable[[str], None]] = None,
                     on_progress: Optional[Callable[[float, str], None]] = None) -> int:
        self.start(on_output, on_progress).join()
        if self.returncode is None:
            self.returncode = -1
        return self.returncode


import re

_PROGRESS_RE = re.compile(r"\((?P<cur>\d+)/(?P<tot>\d+)\)")


def _parse_progress(line: str) -> tuple[Optional[float], str]:
    """fastboot לרוב לא מדווח אחוזים; מזהים '(1/8)' אם קיים."""
    m = _PROGRESS_RE.search(line)
    if m:
        cur, tot = int(m.group("cur")), int(m.group("tot"))
        if tot:
            return min(100.0, cur / tot * 100.0), line.strip()
    return None, ""


# ---------------------------------------------------------------------- בוני פקודות


class FastbootCommands:
    """מחולל ארגומנטים לפקודות fastboot — בונים בקשות, לא מריצים."""

    @classmethod
    def devices(cls) -> FastbootCommand:
        # דורש שורת מכשיר אמיתית (\tfastboot) — אחרת נחשב "אין מכשיר", לא הצלחה
        return FastbootCommand(["devices"], require=r"\t\s*fastboot")

    @classmethod
    def getvar_all(cls) -> FastbootCommand:
        return FastbootCommand(["getvar", "all"])

    @classmethod
    def getvar(cls, var: str) -> FastbootCommand:
        return FastbootCommand(["getvar", var])

    @classmethod
    def flash(cls, partition: str, image: Path) -> FastbootCommand:
        return FastbootCommand(["flash", partition, str(image)])

    @classmethod
    def erase(cls, partition: str) -> FastbootCommand:
        return FastbootCommand(["erase", partition])

    @classmethod
    def reboot(cls, target: str = "") -> FastbootCommand:
        # target: "" (מערכת), "bootloader", "recovery"
        return FastbootCommand(["reboot"] + ([target] if target else []))

    # ------------------------------ ארכיטקטורה 2: Unlock מלא + כתיבה עם דגלים

    @classmethod
    def get_unlock_ability(cls) -> FastbootCommand:
        """fastboot flashing get_unlock_ability — בדיקה לפני כל ניסיון unlock."""
        return FastbootCommand(["flashing", "get_unlock_ability"])

    @classmethod
    def flashing_unlock(cls) -> FastbootCommand:
        """
        fastboot flashing unlock — דורש אישור פיזי בכפתורי עוצמת קול על מסך
        המכשיר; לא ניתן לעקוף מה-PC בכוונה (הגנת אנטי-גניבה). ה-timeout
        הארוך של FastbootCommand (DEVICE_TIMEOUT/reconnect) מכסה את ההמתנה.
        """
        return FastbootCommand(["flashing", "unlock"])

    @classmethod
    def is_userspace(cls) -> FastbootCommand:
        """fastboot getvar is-userspace — 'no' = בוטלאודר אמיתי, 'yes' = fastbootd (שגוי)."""
        return FastbootCommand(["getvar", "is-userspace"])

    @classmethod
    def flash_disable_verity(cls, partition: str, image: "Path") -> FastbootCommand:
        """
        fastboot --disable-verity --disable-verification flash <partition> <image>.
        לפי fastboot.cpp הרשמי: אלו נכנסים לתוקף בפועל רק כשהמחיצה הנצרבת היא
        vbmeta/vbmeta_a/vbmeta_b, או (נפילה) אין מחיצת vbmeta עצמאית כלל
        והמחיצה הנצרבת היא boot/boot_a/boot_b. ראו avb.has_vbmeta_partition().
        """
        return FastbootCommand(["--disable-verity", "--disable-verification",
                               "flash", partition, str(image)])


# ---------------------------------------------------------------------- ניתוח getvar

_UNLOCK_RE = re.compile(r"unlocked\s*:\s*(?P<v>yes|no|true|false)", re.IGNORECASE)
_VAR_RE = re.compile(r"(?:\(bootloader\)\s*)?(?P<k>[\w\-\.]+)\s*:\s*(?P<v>.+?)\s*$")

_INTERESTING = {
    "product": "מוצר",
    "unlocked": "בוטלאודר פתוח",
    "battery-voltage": "מתח סוללה",
    "battery-soc-ok": "סוללה תקינה",
    "secure": "Secure",
    "serialno": "מספר סידורי",
    "current-slot": "Slot נוכחי",
    "slot-count": "מספר Slots",
    "hw-revision": "גרסת חומרה",
}


def parse_fastboot_vars(text: str) -> dict:
    """מחלץ שדות שימושיים מפלט getvar all (product, unlocked וכו')."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _VAR_RE.search(line.strip())
        if not m:
            continue
        k = m.group("k").lower()
        if k in _INTERESTING:
            out[_INTERESTING[k]] = m.group("v").strip()
    return out


def summarize_fastboot(vars_: dict, raw: str = "") -> str:
    """סיכום קריא של מצב ה-Fastboot."""
    lines = [f"{k}: {v}" for k, v in vars_.items()]
    if not lines:
        m = _UNLOCK_RE.search(raw)
        if m:
            v = m.group("v").lower() in ("yes", "true")
            lines.append(f"בוטלאודר פתוח: {'כן' if v else 'לא'}")
    if not lines:
        return "לא זוהו שדות. ודא שהמכשיר במצב Fastboot ושהדרייבר מותקן."
    unlocked = vars_.get("בוטלאודר פתוח", "")
    if unlocked.lower() in ("yes", "true"):
        lines.append("🔓 הבוטלאודר פתוח — <b>בד״כ!</b> ניתן לצרוב.")
    elif unlocked.lower() in ("no", "false"):
        lines.append("🔒 הבוטלאודר נעול — צריבה תיחסם עד לפתיחה (fastboot flashing unlock, מוחק נתונים).")
    return "\n".join(lines)
