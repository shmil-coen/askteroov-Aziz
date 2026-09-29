# -*- coding: utf-8 -*-
"""
הסקטארוב — ערכת ניהול מכשירי MediaTek
תצורות מרכזיות של היישום.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# ------------------------------------------------------------------ נתיבים

APP_NAME = "Askateroov"
APP_TITLE = "הסקטארוב — ערכת ניהול מכשירי MediaTek"
APP_VERSION = "0.9.0"

# פרטי חלון "אודות" — ממולאים על ידי המשתמש (תזכורת נשמרת בקובץ כללים.txt)
APP_ABOUT = "הסקטארוב ערכה לניהול מכשירי אנדרואיד\nמאפשר את ניהול המכשיר בקלות ולכל רמת ידע"     # תיאור המוצר
APP_AUTHOR = "פותח ע\"י עזיז@ במתמחיםטופ (בסיועAI)\nכל הזכויות שמורות"    # שם המפתח/ת

# שורש הפרויקט.
# • הרצה מקוד המקור: תיקיית הפרויקט (כמו תמיד).
# • גרסה מקומפלת (exe יחיד): C:\\ProgramData\\Askateroov — תיקייה קבועה ישר מתחת לכונן,
#   מחוץ לתיקיית המשתמש, שלא נמחקת ולא זזה עם ה-exe. שם נשמרים workspace (שאיבות,
#   לוגים, בנק, גיבויים) והכלים (tools), שמתעדכנים מתוך ה-exe בכל בנייה חדשה.
FROZEN = bool(getattr(sys, "frozen", False))


def _build_stamp() -> str:
    """חותמת של ה-exe הנוכחי (גרסה + גודל + זמן שינוי) — משתנה בכל בנייה חדשה,
    גם כשמספר הגרסה נשאר אותו דבר."""
    try:
        st = Path(sys.executable).stat()
        return f"{APP_VERSION}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        return APP_VERSION


def _same_file(a: Path, b: Path) -> bool:
    """האם שני הקבצים זהים בתוכן (בודק גודל קודם — מהיר)."""
    import filecmp
    try:
        return a.stat().st_size == b.stat().st_size and filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _sync_tools(src: Path, dst: Path) -> bool:
    """מעדכן את tools מתוך ה-exe: מעתיק רק קבצים חדשים או שהשתנו.

    לא מוחק כלום ולא נוגע בקבצים שאין להם מקבילה ב-exe (למשל קבצים שכלי יצר
    בתיקייה). workspace — שאיבות, גיבויים, לוגים, בנק — נמצא מחוץ ל-tools ולא נוגעים בו.
    מחזיר False אם קובץ כלשהו לא הועתק (למשל נעול כי adb עדיין רץ) — ואז ינוסה שוב
    בהפעלה הבאה.
    """
    ok = True
    for s in src.rglob("*"):
        if not s.is_file():
            continue
        d = dst / s.relative_to(src)
        if d.is_file() and _same_file(s, d):
            continue
        try:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
        except OSError:
            ok = False
    return ok


def _frozen_root() -> Path:
    root = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    src = Path(getattr(sys, "_MEIPASS", "")) / "tools"
    dst = root / "tools"
    marker = dst / ".version"
    stamp = _build_stamp()
    try:
        current = marker.read_text(encoding="utf-8").strip()
    except OSError:
        current = ""
    if src.is_dir() and current != stamp:
        # בנייה חדשה (או גרסה חדשה) — מעדכנים רק את מה שהתחדש
        if _sync_tools(src, dst):
            marker.write_text(stamp, encoding="utf-8")
    return root


PROJECT_ROOT = _frozen_root() if FROZEN else Path(__file__).resolve().parents[2]

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
    """מאתר פייתון זמין להרצת mtkclient. סדר החיפוש:
      1. התיקייה הניידת (משתנה הסביבה ASKATEROOV_PYTHON_ROOT / נתיב ברירת המחדל);
      2. בגרסה מקומפלת: תיקייה MTKCliantPortable ליד קובץ ה-exe (מה שהמשתמש הוריד וחילץ);
      3. פייתון שהותקן למשתמש (גם זה שהתוכנה מתקינה אוטומטית);
      4. פייתון ב-PATH.
    """
    cands = [PORTABLE_ROOT / "python.exe"]
    if FROZEN:
        here = Path(sys.executable).resolve().parent
        cands += [here / "MTKCliantPortable" / "MTKCliantPortable" / "python.exe",
                  here / "MTKCliantPortable" / "python.exe"]
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
    cands += [base / n / "python.exe" for n in ("Python312", "Python313", "Python311")]
    for cand in cands:
        if cand.is_file():
            return cand
    # מותקן במערכת?
    exe = shutil.which("python") or shutil.which("python3")
    if exe and "WindowsApps" not in exe:  # מתעלם מה-stub של Microsoft Store
        return Path(exe)
    if not FROZEN:   # בגרסה מקומפלת sys.base_prefix הוא תיקייה זמנית — לא רלוונטי
        p = Path(sys.base_prefix) / "python.exe"
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

CHECKSUM_ALGO = "sha256"  # ברירת מחדל לחישוב סכומי ביקורת

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


