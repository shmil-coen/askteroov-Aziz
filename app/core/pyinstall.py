# -*- coding: utf-8 -*-
"""
התקנה אוטומטית של פייתון + הספריות של mtkclient (לגרסת Lite, בלי פייתון מובנה).

שלבים (הכול למשתמש הנוכחי — בלי הרשאת מנהל):
  1. אם כבר מותקן פייתון במחשב — משתמשים בו (מדלגים על ההורדה).
  2. הורדת מתקין פייתון 3.12 הרשמי מ-python.org.
  3. הרצה במצב אוטומטי עם PATH מסומן (PrependPath=1) — המשתמש רואה רק פס התקדמות.
  4. התקנת הספריות של mtkclient דרך pip (החובה, ואחריהן הרשות — כשל ברשות לא מפיל).
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from . import config

PY_VERSION = "3.12.10"   # הגרסה האחרונה של 3.12 עם מתקין רשמי לווינדוס
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-amd64.exe"

# ספריות שבלעדיהן mtkclient לא עובד
CORE_PACKAGES = ["pyusb", "pyserial", "pycryptodome", "pycryptodomex", "colorama"]
# ספריות לחלק מהפעולות (exploits / מערכת קבצים) — כשל בהן לא מפיל את ההתקנה
OPTIONAL_PACKAGES = ["capstone", "keystone-engine", "fusepy", "mock"]

_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

Progress = Callable[[float, str], None]


def installed_python() -> Optional[Path]:
    """פייתון 3.12 שהותקן למשתמש הנוכחי (המיקום הקבוע של המתקין הרשמי)."""
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
    for name in ("Python312", "Python313", "Python311"):
        p = base / name / "python.exe"
        if p.is_file():
            return p
    return None


def _download(dest: Path, progress: Progress) -> None:
    with urllib.request.urlopen(PY_URL, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                progress(min(40.0, done / total * 40.0),
                         f"מוריד את פייתון… {done // (1024 * 1024)}/{total // (1024 * 1024)}MB")


def _pip(py: Path, packages: list[str], timeout: int = 900) -> tuple[bool, str]:
    p = subprocess.run([str(py), "-m", "pip", "install", "--upgrade",
                        "--disable-pip-version-check", *packages],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=_FLAGS)
    tail = "\n".join(((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-6:])
    return p.returncode == 0, tail


def install(progress: Progress) -> tuple[bool, str, Optional[Path]]:
    """מריץ את כל התהליך. מחזיר (הצליח, הודעה למשתמש, נתיב פייתון)."""
    py = installed_python()
    if py is None:
        tmp = Path(tempfile.gettempdir()) / f"python-{PY_VERSION}-amd64.exe"
        try:
            progress(1.0, "מוריד את פייתון מהאתר הרשמי…")
            _download(tmp, progress)
        except Exception as e:
            return False, f"ההורדה נכשלה (אין אינטרנט?): {e}", None
        progress(42.0, "מתקין את פייתון… (חלון התקדמות של פייתון ייפתח)")
        try:
            r = subprocess.run([str(tmp), "/passive", "InstallAllUsers=0", "PrependPath=1",
                                "Include_test=0", "Include_launcher=1", "Shortcuts=0"],
                               timeout=900)
        except Exception as e:
            return False, f"הפעלת מתקין פייתון נכשלה: {e}", None
        py = installed_python()
        if py is None:
            return False, f"התקנת פייתון לא הושלמה (קוד {r.returncode}).", None
    progress(60.0, "מתקין את הספריות של mtkclient…")
    ok, tail = _pip(py, CORE_PACKAGES)
    if not ok:
        return False, "התקנת הספריות נכשלה:\n" + tail, py
    progress(85.0, "מתקין ספריות נוספות (רשות)…")
    missing_opt = []
    for pkg in OPTIONAL_PACKAGES:
        ok_opt, _ = _pip(py, [pkg], timeout=300)
        if not ok_opt:
            missing_opt.append(pkg)
    # מעכשיו mtkclient ירוץ עם הפייתון הזה
    config.PYTHON_EXE = py
    progress(100.0, "הסתיים")
    msg = f"פייתון {py.parent.name} והספריות של mtkclient הותקנו בהצלחה."
    if missing_opt:
        msg += ("\n\nספריות רשות שלא הותקנו (נדרשות רק לחלק מהפעולות המתקדמות): "
                + ", ".join(missing_opt))
    return True, msg, py
