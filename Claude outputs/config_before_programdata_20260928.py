# -*- coding: utf-8 -*-
"""
הסקטארוב — ערכת ניהול מכשירי MediaTek
תצורות מרכזיות של היישום.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ------------------------------------------------------------------ נתיבים

APP_NAME = "Askateroov"
APP_TITLE = "הסקטארוב — ערכת ניהול מכשירי MediaTek"
APP_VERSION = "0.7.3"

# פרטי חלון "אודות" — ממולאים על ידי המשתמש (תזכורת נשמרת בקובץ כללים.txt)
APP_ABOUT = "הסקטארוב ערכה לניהול מכשירי אנדרואיד\nמאפשר את ניהול המכשיר בקלות ולכל רמת ידע"     # תיאור המוצר
APP_AUTHOR = "פותח ע\"י עזיז@ במתמחיםטופ (בסיועAI)\nכל הזכויות שמורות"    # שם המפתח/ת

# שורש הפרויקט (תיקיית הקוד שלנו)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# תיקיות עבודה
WORKSPACE_DIR = PROJECT_ROOT / "workspace"        # פלטים: dumps, scatter, logs
LOGS_DIR = WORKSPACE_DIR / "logs"
DUMPS_DIR = WORKSPACE_DIR / "dumps"
SCATTER_DIR = WORKSPACE_DIR / "scatter"
BACKUPS_DIR = WORKSPACE_DIR / "backups"
# בנק סקטארים — קבצים שנשמרים ומאורגנים לפי מעבד/מכשיר
SCATTER_BANK_DIR = WORKSPACE_DIR / "scatter_bank"

for _d in (LOGS_DIR, DUMPS_DIR, SCATTER_DIR, BACKUPS_DIR, SCATTER_BANK_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------ סביבת Python ניידת + mtkclient

# נתיב ברירת מחדל ל-Python הניידת (MTKCliantPortable) — ניתן לדריסה במשתנה סביבה
_DEFAULT_PORTABLE = Path(r"C:\Users\karnaf\Downloads\אנדרואיד\MTKCliantPortable\MTKCliantPortable")
PORTABLE_ROOT = Path(os.environ.get("ASKATEROOV_PYTHON_ROOT", _DEFAULT_PORTABLE))

# mtkclient מובנה בתוך התוכנה (tools/mtk) — מועדף; אם חסר, נפילה חזרה לתיקייה הניידת.
_BUNDLED_MTK_DIR = PROJECT_ROOT / "tools" / "mtk"
_BUNDLED_MTK_SCRIPT = _BUNDLED_MTK_DIR / "mtk.py"
_USE_BUNDLED_MTK = _BUNDLED_MTK_SCRIPT.is_file()

# תיקיית mtkclient הפנימית (ספריית הקוד), לצורך import ישיר
MTKCLIENT_DIR = (_BUNDLED_MTK_DIR / "mtkclient") if _USE_BUNDLED_MTK \
    else (PORTABLE_ROOT / "mtkclient")


def find_python_exe() -> Path | None:
    """מאתר מהנדס Python זמין: ניידת קודם, אחר כך מותקן."""
    cand = PORTABLE_ROOT / "python.exe"
    if cand.is_file():
        return cand
    # מותקן במערכת?
    exe = shutil.which("python") or shutil.which("python3")
    if exe and "WindowsApps" not in exe:  # מתעלם מה-stub של Microsoft Store
        return Path(exe)
    for base in (Path(sys.base_prefix), ):
        p = base / "python.exe"
        if p.is_file():
            return p
    return None


PYTHON_EXE = find_python_exe()

# סקריפט mtk.py — מובנה קודם, אחרת מהתיקייה הניידת
MTK_SCRIPT = _BUNDLED_MTK_SCRIPT if _USE_BUNDLED_MTK else (PORTABLE_ROOT / "mtk.py")


def mtk_available() -> bool:
    return PYTHON_EXE is not None and MTK_SCRIPT.is_file()


# ------------------------------------------------------------------ Fastboot (platform-tools)

_FASTBOOT_EXE_NAME = "fastboot.exe" if os.name == "nt" else "fastboot"


def find_fastboot_exe() -> "Path | None":
    """
    מאתר את fastboot.exe לפי סדר עדיפויות:
      1. משתנה סביבה ASKATEROOV_FASTBOOT
      2. העותק שמוטמע בתוך התוכנה (tools) / platform-tools לידה
      3. ב-PATH של המערכת
    """
    cands = []
    env = os.environ.get("ASKATEROOV_FASTBOOT")
    if env:
        cands.append(Path(env))
    # קודם כול — עותק שמוטמע בתוך התוכנה עצמה (נתיב יציב, לא תלוי במחשב):
    for root in (PROJECT_ROOT / "tools", PROJECT_ROOT / "tools" / "platform-tools",
                 PROJECT_ROOT / "bin", PROJECT_ROOT / "platform-tools", PROJECT_ROOT):
        cands.append(root / _FASTBOOT_EXE_NAME)
    # אחר כך — ליד התיקייה הניידת של mtkclient:
    for root in (PORTABLE_ROOT, PORTABLE_ROOT / "platform-tools",
                 PORTABLE_ROOT.parent / "platform-tools"):
        cands.append(root / _FASTBOOT_EXE_NAME)
    for c in cands:
        try:
            if c and c.is_file():
                return c
        except OSError:
            continue
    found = shutil.which("fastboot")
    return Path(found) if found else None


def fastboot_available() -> bool:
    return find_fastboot_exe() is not None


# ------------------------------------------------------------------ ADB (platform-tools)

_ADB_EXE_NAME = "adb.exe" if os.name == "nt" else "adb"


def find_adb_exe() -> "Path | None":
    """מאתר adb.exe — קודם בתוך התוכנה (tools), אחר כך ליד fastboot, ואז ב-PATH."""
    cands = []
    env = os.environ.get("ASKATEROOV_ADB")
    if env:
        cands.append(Path(env))
    # ליד fastboot שכבר אותר (אותה תיקיית platform-tools)
    fb = find_fastboot_exe()
    if fb:
        cands.append(fb.parent / _ADB_EXE_NAME)
    for root in (PROJECT_ROOT / "tools", PROJECT_ROOT / "tools" / "platform-tools",
                 PROJECT_ROOT / "bin", PROJECT_ROOT / "platform-tools", PROJECT_ROOT,
                 PORTABLE_ROOT, PORTABLE_ROOT / "platform-tools"):
        cands.append(root / _ADB_EXE_NAME)
    for c in cands:
        try:
            if c and c.is_file():
                return c
        except OSError:
            continue
    found = shutil.which("adb")
    return Path(found) if found else None


def adb_available() -> bool:
    return find_adb_exe() is not None


# ------------------------------------------------------------------ אבטחה

# מחיצות רגישות שדורשות אזהרה מודגשת לפני צריבה/מחיקה
SENSITIVE_PARTITIONS = {
    "preloader": "Bootloader ראשי — צריבה שגויה עלולה להמית את המכשיר לצמיתות!",
    "lk": "Little Kernel\u200f (bootloader)\u200f — קריטי לאתחול!",
    "lk2": "Little Kernel\u200f (bootloader)\u200f — קריטי לאתחול!",
    "nvram": "מכיל IMEI, כתובות MAC וכיול רדיו — גיבוי חובה לפני שינוי!",
    "nvdata": "מכיל נתוני רשת ומזהי מכשיר — גיבוי חובה לפני שינוי!",
    "protect1": "מחיצת הגנה — מכילה נתוני מערכת רגישים",
    "protect2": "מחיצת הגנה — מכילה נתוני מערכת רגישים",
    "seccfg": "תצורת אבטחת המכשיר (מצב Bootloader)!",
    "frp": "מנגנון הגנת Factory Reset — שינוי עלול לנעול את המכשיר!",
    "efuse": "חשוף לצמיתות — שינוי בלתי הפיך!",
    "md1img": "Firmware של המודם — פגיעה עלולה לפגוע ברשת",
    "md1dsp": "DSP של המודם — פגיעה עלולה לפגוע ברשת",
    "spmfw": "Firmware של מנהל הצריכה",
    "scp": "מעבד העזר (SPM) — קריטי לתפקוד",
    "sspm": "מעבד העזר (SSPM) — קריטי לתפקוד",
    "mcupm": "מעבד העזר (MCUPM) — קריטי לתפקוד",
    "dpm": "מנהל עוצמה — קריטי לתפקוד",
}

# מחיצות שמנקה Factory Reset
FACTORY_RESET_PARTITIONS = ["userdata", "cache"]

CHECKSUM_ALGO = "sha256"  # ברירת מחדל לחישוב סכומי ביקורת

# פסק זמן לזיהוי מכשיר בטעינת BROM (שניות)
BROM_WAIT_TIMEOUT = 60

# ------------------------------------------------------------------ עזרים


def ensure_unique_path(directory: Path, base_name: str, suffix: str) -> Path:
    """מחזיר נתיב ייחודי שלא דורס קובץ קיים."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{base_name}{suffix}"
    i = 1
    while candidate.exists():
        candidate = directory / f"{base_name}_{i}{suffix}"
        i += 1
    return candidate


def relative_to_portable(path: Path) -> Path:
    """מנסה להפוך נתיב ליחסי לתיקיית הניידת (קצר יותר לפקודות)."""
    try:
        return path.relative_to(PORTABLE_ROOT)
    except ValueError:
        return path


_HEB_RE = re.compile(r"[\u0590-\u05FF]")


def path_needs_ansi(path: Path) -> bool:
    """האם הנתיב מכיל עברית (בעייתי ל-subprocess ב-ANSI)?"""
    return bool(_HEB_RE.search(str(path)))
