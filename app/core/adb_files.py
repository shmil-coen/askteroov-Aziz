# -*- coding: utf-8 -*-
"""
סייר קבצים דרך ADB — ניווט, הורדה/העלאה, מחיקה, שינוי שם, יצירת תיקייה ועריכת טקסט.

בלי root הגישה מוגבלת ל-/sdcard (אחסון פנימי). במכשיר rooted ניתן לנווט לכל השורש.
כל הפקודות רצות עם adb.exe מתיקיית tools; פעולות ארוכות נקראות מ-thread רקע ב-GUI.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .logs import log

_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# סוגי קבצים שנחשבים "טקסט לעריכה"
TEXT_SUFFIXES = {
    ".txt", ".xml", ".json", ".prop", ".conf", ".cfg", ".ini", ".log",
    ".sh", ".rc", ".csv", ".md", ".html", ".js", ".css", ".py", ".yaml", ".yml",
}


@dataclass
class FileEntry:
    name: str
    path: str          # נתיב מלא בפורמט posix על המכשיר
    is_dir: bool
    size: int = -1
    is_link: bool = False

    @property
    def is_text(self) -> bool:
        return (not self.is_dir) and Path(self.name).suffix.lower() in TEXT_SUFFIXES

    @property
    def size_str(self) -> str:
        if self.is_dir:
            return ""
        if self.size < 0:
            return "?"
        n = float(self.size)
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
        return f"{self.size} B"


# שגיאות adb נפוצות (באנגלית) -> הסבר בעברית. הסדר חשוב: הראשון שמתאים מנצח.
_ADB_ERRORS = (
    (("no devices/emulators found", "device not found", "no devices found"),
     "לא נמצא מכשיר מחובר. חבר את המכשיר בכבל USB, ודא שניפוי באגים USB פועל ונסה שוב."),
    (("unauthorized",),
     "המכשיר לא אישר את המחשב. אשר במסך המכשיר את הבקשה 'לאפשר ניפוי באגים USB?' ונסה שוב."),
    (("device offline", "is offline"),
     "המכשיר מחובר אבל לא מגיב (offline). נתק וחבר את הכבל ונסה שוב."),
    (("more than one device",),
     "מחוברים כמה מכשירים בבת אחת. נתק את המיותרים ונסה שוב."),
    (("cannot connect to daemon", "daemon not running", "failed to start daemon"),
     "שרת ה-ADB לא עלה. סגור תוכנות אחרות שמשתמשות ב-ADB (כמו Android Studio) ונסה שוב."),
    (("no such file or directory", "does not exist", "failed to stat remote object"),
     "הקובץ או התיקייה לא נמצאו במכשיר."),
    (("permission denied", "operation not permitted"),
     "אין הרשאת גישה (ייתכן שנדרש root)."),
    (("read-only file system", "read-only"),
     "מערכת הקבצים במצב קריאה בלבד — נסה תיקייה תחת /sdcard."),
    (("no space left", "not enough space"),
     "אין מספיק מקום פנוי במכשיר או במחשב."),
    (("protocol fault", "connection reset", "broken pipe", "error: closed"),
     "החיבור למכשיר נותק באמצע הפעולה. בדוק את הכבל ונסה שוב."),
)


def friendly_error(out: str, default: str) -> str:
    """הודעת שגיאה של adb (באנגלית) -> הסבר בעברית. אם הטקסט כבר בעברית — כמו שהוא;
    שגיאה לא מוכרת -> default, והמקור נכתב ללוג (כדי שאפשר יהיה לבדוק)."""
    text = (out or "").strip()
    if not text:
        return default
    if any("֐" <= ch <= "׿" for ch in text):
        return text
    low = text.lower()
    for keys, msg in _ADB_ERRORS:
        if any(k in low for k in keys):
            return msg
    log.warn(f"שגיאת adb לא מוכרת: {text}")
    return default


def _run(cmd: list[str], timeout: float = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=_FLAGS)
        return p.returncode, p.stdout or ""
    except subprocess.TimeoutExpired:
        return -1, "התקשורת עם המכשיר נתקעה (timeout)"
    except OSError as e:
        return -1, str(e)


def _sh(path: str) -> str:
    """מצטט נתיב לשל של המכשיר (single-quote עם escape לגרש)."""
    return "'" + path.replace("'", "'\\''") + "'"


def _posix_join(base: str, name: str) -> str:
    if base.endswith("/"):
        return base + name
    return base + "/" + name


def posix_parent(path: str) -> str:
    path = path.rstrip("/") or "/"
    if path == "/":
        return "/"
    parent = path.rsplit("/", 1)[0]
    return parent or "/"


_LS_L = re.compile(r"^([\-dlbcps])\S*\s+\d+\s+\S+\s+\S+\s+(\d+)\s+")


def list_dir(adb: str, path: str) -> tuple[list[FileEntry], str]:
    """מחזיר (רשימת פריטים, שגיאה). שגיאה ריקה = הצליח."""
    path = path or "/sdcard"
    # שמות + סוג (מקור אמין: שורה לכל שם, עם / בסוף לתיקיות)
    rc, out = _run([adb, "shell", f"ls -1Ap {_sh(path)}"], timeout=25)
    low = out.lower()
    if "no such file" in low:
        return [], "התיקייה לא קיימת"
    if "permission denied" in low:
        return [], "אין הרשאת גישה לתיקייה זו (ייתכן שנדרש root)"
    if "not a directory" in low:
        return [], "זו אינה תיקייה"
    # שגיאה של adb עצמו (אין מכשיר / לא מאושר / offline) — בעברית, ולא כשורות ברשימה
    if rc != 0 and any(k in low for k in (
            "no devices/emulators", "device not found", "unauthorized", "offline",
            "more than one device", "cannot connect to daemon", "error: closed")):
        return [], friendly_error(out, "אין תשובה מהמכשיר — בדוק חיבור ADB")
    if rc != 0 and not out.strip():
        return [], "אין תשובה מהמכשיר — בדוק חיבור ADB"

    names: list[tuple[str, bool, bool]] = []   # (name, is_dir, is_link)
    for line in out.splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        is_link = line.endswith("@")
        is_dir = line.endswith("/")
        name = line[:-1] if (is_dir or is_link) else line
        if name in (".", ".."):
            continue
        names.append((name, is_dir, is_link))

    # גדלים (best-effort) — מיפוי לפי שם
    sizes: dict[str, int] = {}
    rc2, out2 = _run([adb, "shell", f"ls -lAp {_sh(path)}"], timeout=25)
    if rc2 == 0:
        for line in out2.splitlines():
            m = _LS_L.match(line)
            if not m:
                continue
            size = int(m.group(2))
            # השם הוא מה שאחרי העמודות; מתאימים לפי סיומת ידועה
            for nm, is_dir, _lnk in names:
                if is_dir:
                    continue
                if line.endswith("/" + nm) or line.endswith(" " + nm):
                    sizes[nm] = size
                    break

    entries = [
        FileEntry(name=nm, path=_posix_join(path, nm), is_dir=is_dir,
                  size=(-1 if is_dir else sizes.get(nm, -1)), is_link=is_link)
        for nm, is_dir, is_link in names
    ]
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return entries, ""


def is_rooted(adb: str) -> bool:
    """בדיקה best-effort אם יש הרשאת root (su)."""
    rc, out = _run([adb, "shell", "su -c id 2>/dev/null || echo __NO__"], timeout=8)
    return "uid=0" in out


def pull(adb: str, remote: str, local: Path) -> tuple[bool, str]:
    local = Path(local)
    local.parent.mkdir(parents=True, exist_ok=True)
    rc, out = _run([adb, "pull", remote, str(local)], timeout=1800)
    low = out.lower()
    if rc == 0 and ("pulled" in low or local.exists()):
        return True, f"הורד אל: {local}"
    return False, friendly_error(out, "ההורדה נכשלה")


def push(adb: str, local: Path, remote_dir: str) -> tuple[bool, str]:
    local = Path(local)
    if not local.exists():
        return False, f"הקובץ לא נמצא: {local}"
    remote = _posix_join(remote_dir, local.name)
    rc, out = _run([adb, "push", str(local), remote], timeout=1800)
    low = out.lower()
    if rc == 0 and ("pushed" in low or "1 file" in low):
        return True, f"הועלה אל: {remote}"
    if "read-only" in low:
        return False, "התיקייה לכתיבה בלבד למערכת (read-only) — נסה תיקייה תחת /sdcard"
    return False, friendly_error(out, "ההעלאה נכשלה")


def delete(adb: str, remote: str, is_dir: bool) -> tuple[bool, str]:
    cmd = f"rm -rf {_sh(remote)}" if is_dir else f"rm -f {_sh(remote)}"
    rc, out = _run([adb, "shell", cmd], timeout=60)
    low = out.lower()
    if "permission denied" in low or "read-only" in low:
        return False, "אין הרשאה למחוק (ייתכן שנדרש root)"
    if rc == 0 and not out.strip():
        return True, "נמחק"
    return (rc == 0), (friendly_error(out, "נמחק" if rc == 0 else "המחיקה נכשלה"))


def rename(adb: str, remote: str, new_name: str) -> tuple[bool, str]:
    if "/" in new_name or new_name in ("", ".", ".."):
        return False, "שם לא חוקי"
    dst = _posix_join(posix_parent(remote), new_name)
    rc, out = _run([adb, "shell", f"mv {_sh(remote)} {_sh(dst)}"], timeout=60)
    low = out.lower()
    if "permission denied" in low or "read-only" in low:
        return False, "אין הרשאה (ייתכן שנדרש root)"
    if rc == 0 and not out.strip():
        return True, f"השם שונה ל-{new_name}"
    return (rc == 0), (friendly_error(out, "בוצע" if rc == 0 else "שינוי השם נכשל"))


def mkdir(adb: str, parent: str, name: str) -> tuple[bool, str]:
    if "/" in name or name in ("", ".", ".."):
        return False, "שם לא חוקי"
    target = _posix_join(parent, name)
    rc, out = _run([adb, "shell", f"mkdir {_sh(target)}"], timeout=30)
    low = out.lower()
    if "exists" in low:
        return False, "כבר קיימת תיקייה בשם זה"
    if "permission denied" in low or "read-only" in low:
        return False, "אין הרשאה ליצור כאן תיקייה (ייתכן שנדרש root)"
    if rc == 0 and not out.strip():
        return True, f"נוצרה תיקייה: {name}"
    return (rc == 0), (friendly_error(out, "בוצע" if rc == 0 else "יצירת התיקייה נכשלה"))
