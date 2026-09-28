# -*- coding: utf-8 -*-
"""
בנק סקטארים — אחסון וארגון קובצי Scatter בתוך תיקיית התוכנה.

המבנה בדיסק (פשוט וקריא לאדם, בלי בסיס נתונים):

    workspace/scatter_bank/
    ├── _bank_index.json          ← מטא-דאטה (מקור, הערות)
    ├── MT6580/
    │   └── Android_scatter_MT6580.txt
    └── Redmi_9A/
        └── Android_scatter_Redmi_9A.txt

כל תת-תיקייה היא "קבוצה" — שם מעבד (למשל MT6580) או שם מכשיר
(למשל Redmi_9A). המשתמש יכול להוסיף קבצים ידנית ישירות לתיקיות,
והבנק יגלה אותם לבד.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import SCATTER_BANK_DIR

INDEX_NAME = "_bank_index.json"

# סיומות שנחשבות לקובץ Scatter
SCATTER_SUFFIXES = (".txt", ".scatter", ".cfg")


def bank_root() -> Path:
    SCATTER_BANK_DIR.mkdir(parents=True, exist_ok=True)
    return SCATTER_BANK_DIR


def sanitize_group(name: str) -> str:
    """שם קבוצה בטוח לתיקייה (אותיות, ספרות, קו תחתון, מקף)."""
    clean = re.sub(r"[^A-Za-z0-9_.\-\u0590-\u05FF]", "_", name.strip())
    clean = clean.strip("._")
    return clean or "כללי"


def _index_path() -> Path:
    return bank_root() / INDEX_NAME


def _load_index() -> dict:
    p = _index_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_index(index: dict) -> None:
    try:
        _index_path().write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _rel(path: Path) -> str:
    try:
        return path.relative_to(bank_root()).as_posix()
    except ValueError:
        return path.name


@dataclass
class BankEntry:
    path: Path
    group: str
    name: str
    size: int
    modified: float
    source: str = "manual"   # "generated" | "manual"
    note: str = ""
    device: str = ""         # שם המכשיר שהמשתמש מילא (אם מילא)
    cpu: str = ""            # שם המעבד שזוהה

    @property
    def modified_str(self) -> str:
        return datetime.fromtimestamp(self.modified).strftime("%Y-%m-%d %H:%M")

    @property
    def source_label(self) -> str:
        return "נוצר בתוכנה" if self.source == "generated" else "הוזן ידנית"


def _make_entry(path: Path) -> BankEntry:
    meta = _load_index().get(_rel(path), {})
    try:
        st = path.stat()
        size, modified = st.st_size, st.st_mtime
    except OSError:
        size, modified = 0, 0.0
    return BankEntry(
        path=path,
        group=path.parent.name,
        name=path.name,
        size=size,
        modified=modified,
        source=str(meta.get("source", "manual")),
        note=str(meta.get("note", "")),
        device=str(meta.get("device", "")),
        cpu=str(meta.get("cpu", "")),
    )


def groups() -> list[str]:
    """כל הקבוצות (מעבדים/מכשירים) בבנק."""
    root = bank_root()
    found = sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
        and any(f.is_file() and f.suffix.lower() in SCATTER_SUFFIXES
                for f in p.iterdir())   # תיקייה ריקה אינה קבוצה
    )
    return found


def list_entries(group: str | None = None) -> list[BankEntry]:
    """רשימת כל קובצי ה-Scatter בבנק, אופציונלית מסוננת לפי קבוצה."""
    root = bank_root()
    entries: list[BankEntry] = []
    for sub in sorted(root.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        if group and sub.name != group:
            continue
        for f in sorted(sub.iterdir()):
            if f.is_file() and f.suffix.lower() in SCATTER_SUFFIXES:
                entries.append(_make_entry(f))
    return entries


def _unique_dest(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / filename
    i = 1
    while dest.exists():
        dest = directory / f"{Path(filename).stem}_{i}{Path(filename).suffix}"
        i += 1
    return dest


def import_file(
    source: Path,
    group: str,
    source_kind: str = "manual",
    note: str = "",
    device: str = "",
    cpu: str = "",
) -> BankEntry:
    """
    מכניס קובץ Scatter לבנק תחת קבוצה (מעבד/מכשיר).
    source_kind: "manual" לקובץ שהמשתמש בחר, "generated" לקבצים שהתוכנה יצרה.
    """
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"קובץ לא נמצא: {source}")

    group_dir = bank_root() / sanitize_group(group)
    dest = _unique_dest(group_dir, source.name)
    shutil.copy2(source, dest)

    index = _load_index()
    index[_rel(dest)] = {
        "source": source_kind,
        "note": note,
        "device": device,
        "cpu": cpu,
        "added": datetime.now().isoformat(timespec="seconds"),
    }
    _save_index(index)
    return _make_entry(dest)


def save_generated(source: Path, group: str, note: str = "",
                   device: str = "", cpu: str = "") -> BankEntry:
    """שומר קובץ Scatter שהתוכנה יצרה אל הבנק."""
    return import_file(source, group, source_kind="generated", note=note,
                       device=device, cpu=cpu)


def delete_entry(entry: BankEntry) -> None:
    try:
        entry.path.unlink()
    except OSError:
        return
    index = _load_index()
    index.pop(_rel(entry.path), None)
    _save_index(index)
    # מנקה תיקיית קבוצה ריקה (למעט האינדקס)
    parent = entry.path.parent
    try:
        if parent != bank_root() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


def rename_entry(entry: BankEntry, new_name: str) -> BankEntry:
    new_name = sanitize_group(new_name)
    if not Path(new_name).suffix:
        new_name += entry.path.suffix
    dest = entry.path.with_name(new_name)
    if dest.exists() and dest != entry.path:
        raise FileExistsError(f"קובץ בשם זה כבר קיים: {new_name}")
    entry.path.rename(dest)
    index = _load_index()
    meta = index.pop(_rel(entry.path), {})
    index[_rel(dest)] = meta
    _save_index(index)
    return _make_entry(dest)


def move_to_group(entry: BankEntry, new_group: str) -> BankEntry:
    """מעביר קובץ לקבוצת מעבד/מכשיר אחרת."""
    target = bank_root() / sanitize_group(new_group)
    if target == entry.path.parent:
        return entry
    dest = _unique_dest(target, entry.path.name)
    shutil.move(str(entry.path), str(dest))
    index = _load_index()
    meta = index.pop(_rel(entry.path), {})
    index[_rel(dest)] = meta
    _save_index(index)
    return _make_entry(dest)


def read_entry_text(entry: BankEntry, max_chars: int = 20000) -> str:
    """קורא את תוכן הקובץ לתצוגה מקדימה."""
    try:
        text = entry.path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"לא ניתן לקרוא את הקובץ: {e}"
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n… (התוכן קוצר לתצוגה)"
    return text


def stats() -> dict:
    """סיכום כללי של הבנק."""
    entries = list_entries()
    gen = sum(1 for e in entries if e.source == "generated")
    return {
        "total": len(entries),
        "generated": gen,
        "manual": len(entries) - gen,
        "groups": len(groups()),
        "root": str(bank_root()),
    }
