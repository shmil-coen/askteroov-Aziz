# -*- coding: utf-8 -*-
"""
Preflight — הצ'קליסט האחרון ממש לפני כתיבה (BROM או Fastboot). כל הבדיקות
כאן הן קריאה-בלבד; שום דבר לא נכתב למכשיר במודול הזה. נבנה לפי הרשימה
המדויקת שהוגדרה בשני מסמכי הארכיטקטורה: טביעת אצבע GPT, מיקום מחיצת יעד
מדויק, SHA256 מקור/מפוצח, מצב vbmeta, וסוללה.

עיקרון: כל בדיקה קריטית שנכשלת חוסמת המשך (אין "המשך בכל זאת" שקט).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .checksums import file_sha256
from .device_info import DeviceInfo
from .gpt_parser import GptTable


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    critical: bool = True    # כשל בבדיקה קריטית חוסם המשך


@dataclass
class PreflightReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, critical: bool = True):
        self.checks.append(Check(name, ok, detail, critical))

    @property
    def blocking_failures(self) -> list[Check]:
        return [c for c in self.checks if c.critical and not c.ok]

    @property
    def all_critical_ok(self) -> bool:
        return not self.blocking_failures

    def as_text(self) -> str:
        lines = []
        for c in self.checks:
            mark = "✅" if c.ok else ("🛑" if c.critical else "⚠️")
            lines.append(f"{mark} {c.name}: {c.detail}")
        return "\n".join(lines)


def gpt_fingerprint(gpt: GptTable) -> tuple:
    """(מספר מחיצות, רשימת (שם, offset, length) ממוינת) — להשוואת 'אותו דיסק בדיוק'."""
    parts = tuple(sorted((p.name.lower(), p.offset, p.length) for p in gpt.partitions))
    return (len(gpt.partitions), parts)


def run_preflight(*, gpt_before: GptTable, gpt_now: GptTable,
                  target_partition: str, source_image: Path, patched_image: Path,
                  expected_source_sha256: Optional[str] = None,
                  vbmeta_status: str = "", device: Optional[DeviceInfo] = None,
                  ) -> PreflightReport:
    report = PreflightReport()

    # 1) טביעת אצבע GPT — אותו דיסק בדיוק כמו שנקרא בתחילת התהליך
    fp_before = gpt_fingerprint(gpt_before)
    fp_now = gpt_fingerprint(gpt_now)
    same_gpt = fp_before == fp_now
    report.add("טביעת אצבע GPT",
              same_gpt,
              "זהה למה שנקרא בתחילת התהליך" if same_gpt else
              f"שונה! לפני: {fp_before[0]} מחיצות, עכשיו: {fp_now[0]} מחיצות — "
              "המכשיר עשוי להיות אחר / GPT השתנה")

    # 2) מחיצת היעד עדיין קיימת ובאותו מיקום/גודל בדיוק
    part = gpt_now.get(target_partition)
    if part is None:
        report.add("מחיצת יעד קיימת", False, f"'{target_partition}' לא נמצאה ב-GPT הנוכחי")
    else:
        part_before = gpt_before.get(target_partition)
        same_loc = (part_before is not None and part_before.offset == part.offset
                   and part_before.length == part.length)
        report.add("מיקום מחיצת יעד", same_loc,
                  f"'{target_partition}': offset=0x{part.offset:x} length=0x{part.length:x}"
                  + ("" if same_loc else " — לא תואם למה שנקרא בהתחלה!"))
        # קובץ מפוצח לא גדול מהמחיצה
        try:
            patched_size = patched_image.stat().st_size
            fits = patched_size <= part.length
            report.add("גודל קובץ מפוצח מול מחיצה", fits,
                      f"{patched_size:,} בתים מול מחיצה של {part.length:,} בתים")
        except OSError as e:
            report.add("גודל קובץ מפוצח מול מחיצה", False, f"שגיאת קריאה: {e}")

    # 3) SHA256 של קובץ המקור (boot/init_boot שנשאב) — לא השתנה מאז השאיבה
    try:
        actual_sha = file_sha256(source_image)
        if expected_source_sha256:
            match = actual_sha.lower() == expected_source_sha256.lower()
            report.add("SHA256 קובץ מקור", match,
                      "תואם לגיבוי שנשמר" if match else
                      f"אינו תואם! צפוי {expected_source_sha256[:16]}…, בפועל {actual_sha[:16]}…")
        else:
            report.add("SHA256 קובץ מקור", True, f"{actual_sha[:16]}… (אין ערך צפוי להשוואה)",
                      critical=False)
    except OSError as e:
        report.add("SHA256 קובץ מקור", False, f"שגיאת קריאה: {e}")

    # 4) קובץ מפוצח קיים ולא ריק
    try:
        ok_patched = patched_image.is_file() and patched_image.stat().st_size > 0
        report.add("קובץ מפוצח תקין", ok_patched,
                  str(patched_image) if ok_patched else "הקובץ לא קיים או ריק")
    except OSError as e:
        report.add("קובץ מפוצח תקין", False, f"שגיאת קריאה: {e}")

    # 5) מצב vbmeta (מידע בלבד — לא חוסם; ההחלטה כבר התקבלה קודם בפייפליין)
    if vbmeta_status:
        report.add("מצב vbmeta", True, vbmeta_status, critical=False)

    # 6) סוללה
    if device is not None:
        low = device.battery_too_low()
        report.add("רמת סוללה", not low,
                  device.battery_note() if low else "תקינה לכתיבה", critical=low)

    return report
