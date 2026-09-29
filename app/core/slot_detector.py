# -*- coding: utf-8 -*-
"""
זיהוי ה-slot הפעיל (A/B) — ריבוי-אסטרטגיות עם הצלבה, לפי העיקרון
"אי-ודאות => עצירה". אין שיטה אוניברסלית אחת: חלק מהמכשירים (בעיקר Qualcomm,
חלק מ-MediaTek החדשים) שומרים מטא-דאטה של A/B בביטים בתוך ה-attributes של
כל מחיצה ב-GPT עצמו; אחרים (נפוץ ב-MediaTek) שומרים זאת אך ורק במבנה
bootloader_control בתוך מחיצת ה-misc.

כל אסטרטגיה מחזירה תוצאה או None (לא מכריעה). אם 0 הכריעו — עצירה.
אם רק 1 הכריעה — משתמשים בה אך מסמנים "לא מאומת-הצלבה". אם 2+ הכריעו
ולא מסכימות — עצירה עם פירוט המחלוקת. ראו: "רוטינג אוטומטי במצב ברום.txt".
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

from .gpt_parser import GptTable

# ---------------------------------------------------------------------- מבנה תוצאה


@dataclass
class SlotResult:
    slot: str                       # "a" / "b"
    strategy: str                   # "gpt_attr" / "misc_bootctrl" / "adb_prop"
    confident: bool                 # True אם 2+ אסטרטגיות הסכימו
    details: list[str] = field(default_factory=list)


class SlotDetectionError(RuntimeError):
    """נזרק כשאין אף אסטרטגיה מכריעה, או כששתיים+ סותרות זו את זו."""


# ---------------------------------------------------------------------- אסטרטגיה 1: GPT attribute bits
#
# מבוסס על source.android.com/devices/tech/ota/ab#partitions — ביטי ה-flags
# (64bit, little-endian) של כל ערך GPT: bits 48-49 = priority, bit 50 = active,
# bit 51 = successful boot, bits 52-55 = tries remaining. לא כל יצרן משתמש
# בשיטה הזו (רבים מ-MediaTek דווקא לא) — כאן רק קוראים; לא מניחים שהיא קיימת.

_PRIORITY_MASK = 0b11 << 48
_ACTIVE_BIT = 1 << 50
_SUCCESSFUL_BIT = 1 << 51


def _gpt_attr_strategy(gpt: GptTable, base_name: str) -> Optional[SlotResult]:
    pa = gpt.get(f"{base_name}_a")
    pb = gpt.get(f"{base_name}_b")
    if pa is None or pb is None:
        return None
    try:
        flags_a = int(pa.flags, 16) if pa.flags else 0
        flags_b = int(pb.flags, 16) if pb.flags else 0
    except ValueError:
        return None
    active_a = bool(flags_a & _ACTIVE_BIT)
    active_b = bool(flags_b & _ACTIVE_BIT)
    if active_a == active_b:
        # שני ה-slot מסומנים זהה (שניהם 0 = כנראה שהשיטה הזו לא בשימוש בכלל,
        # או שניהם 1 = לא הגיוני) — לא מכריעים.
        return None
    prio_a = (flags_a & _PRIORITY_MASK) >> 48
    prio_b = (flags_b & _PRIORITY_MASK) >> 48
    winner = "a" if active_a else "b"
    return SlotResult(
        slot=winner, strategy="gpt_attr", confident=False,
        details=[f"{base_name}_a: active={active_a} priority={prio_a} flags=0x{flags_a:x}",
                 f"{base_name}_b: active={active_b} priority={prio_b} flags=0x{flags_b:x}"],
    )


# ---------------------------------------------------------------------- אסטרטגיה 2: misc / bootloader_control
#
# struct bootloader_control (AOSP bootable/recovery/bootloader_message),
# ממוקם בהיסט 2048 בתוך מחיצת misc (מיד אחרי ה-bootloader_message הישן),
# magic = 0x42414342 ("BAB" + גרסה, little-endian בקובץ הבינארי).

_BOOTCTRL_OFFSET = 2048
_BOOTCTRL_MAGIC = 0x42414342


def _parse_bootloader_control(data: bytes) -> Optional[dict]:
    if len(data) < _BOOTCTRL_OFFSET + 4 + 4 + 4 + 4:
        return None
    block = data[_BOOTCTRL_OFFSET:_BOOTCTRL_OFFSET + 64]
    if len(block) < 16:
        return None
    magic = struct.unpack_from("<I", block, 4)[0]
    if magic != _BOOTCTRL_MAGIC:
        return None
    # slot_info[0..3] מתחילים בהיסט 12 בתוך ה-struct, 1 בית כל אחד:
    #   bit0-3 priority, bit4-6 tries_remaining, bit7 successful_boot
    slot_info_off = 12
    slots = []
    for i in range(2):   # רק 2 slot רלוונטיים ל-A/B (nb_slot בד"כ 2)
        byte = block[slot_info_off + i]
        priority = byte & 0x0F
        tries = (byte >> 4) & 0x07
        successful = bool((byte >> 7) & 0x01)
        slots.append({"priority": priority, "tries": tries, "successful": successful})
    return {"slots": slots}


def _misc_bootctrl_strategy(misc_image_path) -> Optional[SlotResult]:
    """
    :param misc_image_path: נתיב לקובץ שנשאב ממחיצת misc (Path).
    """
    try:
        data = misc_image_path.read_bytes()
    except OSError:
        return None
    parsed = _parse_bootloader_control(data)
    if parsed is None:
        return None
    sa, sb = parsed["slots"][0], parsed["slots"][1]
    if sa["priority"] == sb["priority"] and sa["tries"] == sb["tries"]:
        return None   # אין הבדל שמאפשר הכרעה
    # ה-slot הפעיל: priority גבוה יותר וגם tries_remaining > 0
    cand = "a" if sa["priority"] > sb["priority"] else "b"
    winner_info = sa if cand == "a" else sb
    if winner_info["tries"] == 0:
        return None   # ה-slot המועדף כבר "מוצה" — לא ברור, לא מכריעים
    return SlotResult(
        slot=cand, strategy="misc_bootctrl", confident=False,
        details=[f"slot_a: priority={sa['priority']} tries={sa['tries']} successful={sa['successful']}",
                 f"slot_b: priority={sb['priority']} tries={sb['tries']} successful={sb['successful']}"],
    )


# ---------------------------------------------------------------------- אסטרטגיה 3: ADB (רק אם זמין)

def _adb_prop_strategy(adb_exe: Optional[str]) -> Optional[SlotResult]:
    if not adb_exe:
        return None
    import subprocess
    try:
        out = subprocess.run([adb_exe, "shell", "getprop", "ro.boot.slot_suffix"],
                             capture_output=True, text=True, timeout=6).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = out.strip().lstrip("_").lower()
    if out in ("a", "b"):
        return SlotResult(slot=out, strategy="adb_prop", confident=False,
                          details=[f"ro.boot.slot_suffix=_{out}"])
    return None


# ---------------------------------------------------------------------- הצלבה


def detect_slot(gpt: GptTable, base_name: str, misc_image_path=None,
                adb_exe: Optional[str] = None) -> SlotResult:
    """
    מריץ את כל האסטרטגיות הזמינות ומצליב. זורק SlotDetectionError אם אין
    הכרעה, או אם יש הכרעות סותרות.
    """
    results: list[SlotResult] = []
    r1 = _gpt_attr_strategy(gpt, base_name)
    if r1:
        results.append(r1)
    if misc_image_path is not None:
        r2 = _misc_bootctrl_strategy(misc_image_path)
        if r2:
            results.append(r2)
    r3 = _adb_prop_strategy(adb_exe)
    if r3:
        results.append(r3)

    if not results:
        raise SlotDetectionError(
            f"לא ניתן לזהות בביטחון את ה-slot הפעיל של '{base_name}' — "
            "אף אסטרטגיה (GPT attributes / misc bootloader_control / ADB) לא הכריעה. "
            "עוצרים לפי עקרון 'אי-ודאות => עצירה'.")

    slots_found = {r.slot for r in results}
    if len(slots_found) > 1:
        detail = "\n".join(f"- {r.strategy}: slot {r.slot} ({'; '.join(r.details)})"
                           for r in results)
        raise SlotDetectionError(
            f"אסטרטגיות זיהוי ה-slot סותרות זו את זו עבור '{base_name}':\n{detail}\n"
            "עוצרים — אין להמשיך עם ניחוש.")

    winner = results[0]
    all_details = [d for r in results for d in r.details]
    strategies_used = ", ".join(sorted({r.strategy for r in results}))
    return SlotResult(slot=winner.slot, strategy=strategies_used,
                      confident=len(results) >= 2, details=all_details)


def target_names(base_name: str, slot: Optional[str]) -> list[str]:
    """
    שמות המחיצה האפשריים ליעד, לפי סדר עדיפות: עם slot (אם יש A/B), בלי (אם
    המכשיר לא A/B בכלל).
    """
    if slot:
        return [f"{base_name}_{slot}"]
    return [base_name]
