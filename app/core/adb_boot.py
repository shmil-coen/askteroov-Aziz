# -*- coding: utf-8 -*-
"""
בוטלאודר דרך ADB.

קריאה (בטוח, בלי שינוי): מאפייני מערכת שמעידים על מצב הנעילה.
פתיחה/נעילה: ADB לא יכול לפתוח/לנעול ישירות. הרצף הוא:
  1. adb reboot bootloader        — אתחול למצב Fastboot
  2. המתנה עד שהמכשיר מופיע ב-fastboot
  3. fastboot flashing unlock/lock  (ואם לא נתמך — fastboot oem unlock/lock)
  בסוף המשתמש מאשר על מסך הטלפון עם כפתורי הווליום.
הפקודות כאן חושפות את אותו ממשק כמו MtkCommand, כדי לרוץ דרך JobManager
(חלון אישור, ביטול, לוג).
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Callable, Optional

from .config import find_adb_exe, find_fastboot_exe
from .logs import log

_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _run(cmd: list[str], timeout: float = 15) -> str:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=_FLAGS)
        return p.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ---------------------------------------------------------------------- קריאה

_PROPS = ("ro.boot.flash.locked", "ro.boot.verifiedbootstate", "ro.boot.vbmeta.device_state",
          "sys.oem_unlock_allowed", "ro.oem_unlock_supported")


def read_state(adb: str) -> dict:
    """מחזיר {'props': {...}, 'locked': True/False/None, 'oem_allowed': True/False/None}."""
    props = {}
    for p in _PROPS:
        props[p] = _run([adb, "shell", "getprop", p], timeout=8).strip()
    locked = None
    fl = props["ro.boot.flash.locked"]
    ds = props["ro.boot.vbmeta.device_state"].lower()
    vb = props["ro.boot.verifiedbootstate"].lower()
    if fl == "1" or ds == "locked":
        locked = True
    elif fl == "0" or ds == "unlocked":
        locked = False
    elif vb == "green":
        locked = True
    elif vb in ("orange", "yellow"):
        locked = False
    oem = props["sys.oem_unlock_allowed"]
    oem_allowed = True if oem == "1" else (False if oem == "0" else None)
    return {"props": props, "locked": locked, "oem_allowed": oem_allowed}


def summarize(state: dict) -> str:
    p = state.get("props", {})
    locked = state.get("locked")
    lines = []
    if locked is True:
        lines.append("🔒 הבוטלאודר נעול")
    elif locked is False:
        lines.append("🔓 הבוטלאודר פתוח")
    else:
        lines.append("❔ לא ניתן לקבוע את מצב הבוטלאודר מהמכשיר הזה")
    oem = state.get("oem_allowed")
    if oem is True:
        lines.append("✅ 'ביטול נעילת OEM' מופעל בהגדרות המפתחים — אפשר לפתוח")
    elif oem is False:
        lines.append("⚠️ 'ביטול נעילת OEM' כבוי — צריך להפעיל אותו בהגדרות מפתחים לפני פתיחה")
    names = {"ro.boot.flash.locked": "flash.locked",
             "ro.boot.verifiedbootstate": "verifiedbootstate",
             "ro.boot.vbmeta.device_state": "vbmeta.device_state",
             "sys.oem_unlock_allowed": "oem_unlock_allowed",
             "ro.oem_unlock_supported": "oem_unlock_supported"}
    detail = ", ".join(f"{names[k]}={v}" for k, v in p.items() if v)
    if detail:
        lines.append("פרטים: " + detail)
    return "\n".join(lines)


# ---------------------------------------------------------------------- פקודות לרצף

class _ExtCommand:
    """פקודה חיצונית (adb/fastboot) עם ממשק כמו MtkCommand."""

    def __init__(self, exe: str, args: list[str], title: str):
        self.exe, self.args, self.title = exe, args, title
        self.process: Optional[subprocess.Popen] = None
        self.returncode: Optional[int] = None
        self._stop = threading.Event()

    def describe(self) -> str:
        return self.title

    def reset(self):
        self.process = None
        self.returncode = None
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()
        proc = self.process
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    def _exec(self, args: list[str], on_output) -> tuple[int, str]:
        log.info(f"רץ: {os.path.basename(self.exe)} {' '.join(args)}")
        try:
            self.process = subprocess.Popen(
                [self.exe] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", creationflags=_FLAGS)
        except OSError as e:
            log.error(f"הפעלה נכשלה: {e}")
            return -1, ""
        lines = []
        for line in self.process.stdout:
            if self._stop.is_set():
                break
            line = line.rstrip()
            if line:
                lines.append(line)
                if on_output:
                    on_output(line)
        self.process.wait()
        if self._stop.is_set():
            return -2, "\n".join(lines)
        return self.process.returncode, "\n".join(lines)

    def run_blocking(self, on_output: Optional[Callable[[str], None]] = None,
                     on_progress: Optional[Callable[[float, str], None]] = None) -> int:
        rc, _out = self._exec(self.args, on_output)
        self.returncode = rc
        return rc


class RebootToBootloader(_ExtCommand):
    def __init__(self):
        adb = find_adb_exe()
        if adb is None:
            raise RuntimeError("adb.exe לא נמצא בתיקיית tools.")
        super().__init__(str(adb), ["reboot", "bootloader"], "adb reboot bootloader")


class WaitForFastboot(_ExtCommand):
    """ממתין עד שהמכשיר מופיע ב-fastboot (עד timeout שניות)."""

    def __init__(self, timeout: int = 90):
        fb = find_fastboot_exe()
        if fb is None:
            raise RuntimeError("fastboot.exe לא נמצא בתיקיית tools.")
        super().__init__(str(fb), ["devices"],
                         f"המתנה למכשיר במצב Fastboot (עד {timeout} שניות)")
        self.timeout = timeout

    def run_blocking(self, on_output=None, on_progress=None) -> int:
        start = time.time()
        while time.time() - start < self.timeout:
            if self._stop.is_set():
                self.returncode = -2
                return -2
            out = _run([self.exe, "devices"], timeout=10)
            if any("\t" in l and "fastboot" in l for l in out.splitlines()):
                if on_output:
                    on_output("המכשיר זוהה במצב Fastboot")
                self.returncode = 0
                return 0
            if on_progress:
                el = time.time() - start
                on_progress(min(99.0, el / self.timeout * 100), "ממתין ל-Fastboot…")
            self._stop.wait(2)
        if on_output:
            on_output("המכשיר לא הופיע במצב Fastboot בזמן — בדוק דרייבר Fastboot")
        self.returncode = 1
        return 1


class FlashingLockCommand(_ExtCommand):
    """fastboot flashing unlock/lock — ואם הפקודה לא נתמכת: fastboot oem unlock/lock."""

    def __init__(self, unlock: bool):
        fb = find_fastboot_exe()
        if fb is None:
            raise RuntimeError("fastboot.exe לא נמצא בתיקיית tools.")
        self.verb = "unlock" if unlock else "lock"
        super().__init__(str(fb), ["flashing", self.verb], f"fastboot flashing {self.verb}")

    def run_blocking(self, on_output=None, on_progress=None) -> int:
        if on_output:
            on_output("אשר על מסך הטלפון עם כפתורי הווליום (ולחצן ההפעלה לאישור)")
        rc, out = self._exec(["flashing", self.verb], on_output)
        low = out.lower()
        if rc != -2 and ("unknown command" in low or "not supported" in low
                         or "unrecognized" in low or "invalid" in low):
            if on_output:
                on_output(f"הפקודה לא נתמכת — מנסה fastboot oem {self.verb}")
            rc, out = self._exec(["oem", self.verb], on_output)
            low = out.lower()
        if rc == 0 and ("failed" in low or "error" in low):
            rc = 1
        self.returncode = rc
        return rc
