# -*- coding: utf-8 -*-
"""
זיהוי סביבת פייתון — בדיקה בלבד (לא משנה איך התוכנה מריצה את mtkclient).

בודק:
  1. פייתון נייד בתוך התוכנה (תיקיית python או mtkclient ליד התוכנה — לגרסה המלאה)
  2. פייתון נייד חיצוני — התיקייה הניידת המוגדרת היום (MTKCliantPortable)
  3. פייתון שמותקן במחשב (python / py ב-PATH)
ובנוסף: האם mtk.py קיים, ואילו ספריות של mtkclient חסרות בפייתון הפעיל.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config

# קישור להורדת פייתון לווינדוס (האתר הרשמי)
PYTHON_DOWNLOAD_URL = "https://www.python.org/downloads/windows/"

# ספריות ש-mtkclient צריך: (שם להתקנה, [שמות import אפשריים])
_REQUIRED = [
    ("pyusb", ["usb"]),
    ("pyserial", ["serial"]),
    ("pycryptodome", ["Cryptodome", "Crypto"]),
]

_CHECK_SCRIPT = (
    "import importlib, json, sys\n"
    "req = json.loads(sys.argv[1])\n"
    "res = {}\n"
    "for name, mods in req:\n"
    "    ok = False\n"
    "    for m in mods:\n"
    "        try:\n"
    "            importlib.import_module(m); ok = True; break\n"
    "        except Exception:\n"
    "            pass\n"
    "    res[name] = ok\n"
    "print(json.dumps({'version': sys.version.split()[0], 'mods': res}))\n"
)

_EXE = "python.exe" if os.name == "nt" else "python3"

KIND_INSIDE = "inside"      # נייד בתוך התוכנה
KIND_EXTERNAL = "external"  # נייד חיצוני (MTKCliantPortable)
KIND_SYSTEM = "system"      # מותקן במחשב

_KIND_LABEL = {
    KIND_INSIDE: "פייתון נייד בתוך התוכנה",
    KIND_EXTERNAL: "פייתון נייד חיצוני לתוכנה (MTKCliantPortable)",
    KIND_SYSTEM: "פייתון מותקן במחשב",
}


@dataclass
class PyCandidate:
    kind: str
    path: Optional[Path]
    exists: bool

    @property
    def label(self) -> str:
        return _KIND_LABEL[self.kind]


@dataclass
class PyEnvReport:
    candidates: list[PyCandidate] = field(default_factory=list)
    active: Optional[Path] = None        # הפייתון שהתוכנה משתמשת בו בפועל
    active_kind: str = ""
    version: str = ""
    mtk_script: Optional[Path] = None
    mtk_script_ok: bool = False
    missing: list[str] = field(default_factory=list)
    check_error: str = ""

    @property
    def ok(self) -> bool:
        return (self.active is not None and self.mtk_script_ok
                and not self.missing and not self.check_error)

    @property
    def has_inside(self) -> bool:
        return any(c.kind == KIND_INSIDE and c.exists for c in self.candidates)

    def summary(self) -> str:
        lines = []
        if self.active:
            kind = _KIND_LABEL.get(self.active_kind, "פייתון")
            ver = f" — גרסה {self.version}" if self.version else ""
            lines.append(f"פייתון פעיל: {kind}{ver}")
            lines.append(f"   נתיב: {self.active}")
        else:
            lines.append("❌ לא נמצא פייתון — mtkclient לא יוכל לרוץ.")
            lines.append("   לחץ על הכפתור 'התקן פייתון' למטה.")
        lines.append("")
        lines.append("מה נמצא:")
        for c in self.candidates:
            if c.exists:
                lines.append(f"   ✅ נמצא — {c.label}")
            else:
                lines.append(f"   ❌ לא נמצא — {c.label}")
        lines.append("")
        lines.append(f"{'✅' if self.mtk_script_ok else '❌'} mtk.py: {self.mtk_script}")
        if self.check_error:
            lines.append(f"⚠️ בדיקת הספריות נכשלה: {self.check_error}")
        elif self.active:
            if self.missing:
                lines.append("❌ ספריות חסרות: " + ", ".join(self.missing))
                lines.append("   להתקנה: " + f'"{self.active}" -m pip install '
                             + " ".join(self.missing))
            else:
                lines.append("✅ כל הספריות ש-mtkclient צריך קיימות.")
        lines.append("")
        lines.append("🟢 הסביבה תקינה — mtkclient מוכן לעבודה." if self.ok
                     else "🔴 הסביבה לא מוכנה — ראה הפרטים למעלה.")
        return "\n".join(lines)


def _system_python() -> Optional[Path]:
    for name in ("python", "python3", "py"):
        exe = shutil.which(name)
        if exe and "WindowsApps" not in exe:   # מתעלם מה-stub של Microsoft Store
            return Path(exe)
    return None


def _same(a: Optional[Path], b: Optional[Path]) -> bool:
    if a is None or b is None:
        return False
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a).lower() == str(b).lower()


def detect() -> PyEnvReport:
    rep = PyEnvReport()
    root = config.PROJECT_ROOT
    inside = next((p for p in (root / "python" / _EXE, root / "mtkclient" / _EXE)
                   if p.is_file()), None)
    external = config.PORTABLE_ROOT / "python.exe"
    system = _system_python()
    rep.candidates = [
        PyCandidate(KIND_INSIDE, inside, inside is not None),
        PyCandidate(KIND_EXTERNAL, external, external.is_file()),
        PyCandidate(KIND_SYSTEM, system, system is not None),
    ]

    rep.active = config.PYTHON_EXE
    for c in rep.candidates:
        if c.exists and _same(c.path, rep.active):
            rep.active_kind = c.kind
            break
    else:
        if rep.active is not None:
            rep.active_kind = KIND_SYSTEM

    rep.mtk_script = config.MTK_SCRIPT
    rep.mtk_script_ok = config.MTK_SCRIPT.is_file()

    if rep.active is not None:
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            p = subprocess.run(
                [str(rep.active), "-c", _CHECK_SCRIPT, json.dumps(_REQUIRED)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", timeout=20, creationflags=flags,
                cwd=str(config.MTK_SCRIPT.parent) if rep.mtk_script_ok else None)
            last = (p.stdout or "").strip().splitlines()[-1:] or [""]
            data = json.loads(last[0])
            rep.version = data.get("version", "")
            rep.missing = [k for k, v in data.get("mods", {}).items() if not v]
        except Exception as e:   # פייתון לא רץ / פלט לא צפוי / timeout
            rep.check_error = str(e)[:200]
    return rep
