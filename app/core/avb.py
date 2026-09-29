# -*- coding: utf-8 -*-
"""
טיפול ב-AVB / vbmeta — פאץ' דגלים בלבד (בלי חתימה מחדש; דגלים אלו נועדו
בדיוק בשביל זה: לכבות אכיפה במקום לזייף חתימה).

מקור (אומת מול המקור הרשמי, external/avb/libavb/avb_vbmeta_image.h):
  AVB_VBMETA_IMAGE_FLAGS_HASHTREE_DISABLED   = 0x1
  AVB_VBMETA_IMAGE_FLAGS_VERIFICATION_DISABLED = 0x2
כל שדות ה-header הם big-endian (avb_be32toh/avb_be64toh).

עיקרון בטיחות: flags |= 0x3 (לא דריסה) — כדי לא לפגוע בביטים לא-ידועים/
ספציפיים ליצרן. אם כבר יש ביטים לא-מוכרים דלוקים — נמנעים מפאץ' אוטומטי
לגמרי ומדווחים. ראו: "רוטינג אוטומטי במצב ברום.txt", סעיף vbmeta.
"""
from __future__ import annotations

from pathlib import Path

from .gpt_parser import GptTable

MAGIC = b"AVB0"
_FLAGS_OFFSET = 120

HASHTREE_DISABLED = 0x1
VERIFICATION_DISABLED = 0x2
KNOWN_MASK = HASHTREE_DISABLED | VERIFICATION_DISABLED


def read_flags(vbmeta_path: Path) -> int:
    with open(vbmeta_path, "rb") as f:
        header = f.read(256)
    if len(header) < 256 or header[0:4] != MAGIC:
        raise ValueError(f"{vbmeta_path.name}: לא זוהתה חתימת AVB0 — זה לא vbmeta תקין")
    return int.from_bytes(header[_FLAGS_OFFSET:_FLAGS_OFFSET + 4], "big")


def patch_flags_disable_verification(vbmeta_path: Path) -> tuple[bool, str]:
    """
    מבצע flags |= 0x03 במקום (על עותק מקומי — הקורא אחראי להעביר עותק, לא
    את הגיבוי המקורי). מחזיר (בוצע_שינוי, הודעה).
    נמנע מפאץ' אם קיימים ביטים לא-מוכרים ב-flags (שמור על ההתנהגות המקורית).
    """
    current = read_flags(vbmeta_path)
    unknown = current & ~KNOWN_MASK
    if unknown:
        return False, (
            f"נמצאו ביטים לא-מוכרים ב-flags הקיימים (0x{current:08x}) — "
            "נמנעים מפאץ' אוטומטי כדי לא לפגוע בהתנהגות ספציפית ליצרן. "
            "נדרשת החלטה ידנית.")
    if current & KNOWN_MASK == KNOWN_MASK:
        return False, "הדגלים כבר מכבים hashtree+verification — אין צורך בפאץ'."
    new_flags = current | KNOWN_MASK
    with open(vbmeta_path, "r+b") as f:
        f.seek(_FLAGS_OFFSET)
        f.write(new_flags.to_bytes(4, "big"))
    return True, f"vbmeta flags עודכן: 0x{current:08x} → 0x{new_flags:08x} (bitwise OR, לא דריסה)"


def has_vbmeta_partition(gpt: GptTable) -> bool:
    """
    האם קיימת מחיצת vbmeta עצמאית (vbmeta / vbmeta_a / vbmeta_b) ב-GPT.
    משמש בארכיטקטורה 2 להחלטה אם fastboot --disable-verity/--disable-verification
    ידרוש flash נפרד למחיצת vbmeta, בהתאם ללוגיקה המדויקת של fastboot.cpp הרשמי:

        if (g_disable_verity || g_disable_verification) {
            if (apply_vbmeta) {
                rewrite_vbmeta_buffer(buf, false);
            } else if (!has_vbmeta_partition() &&
                (partition == "boot" || partition == "boot_a" || partition == "boot_b")) {
                rewrite_vbmeta_buffer(buf, true);
            }
        }
    """
    names = {n.lower() for n in gpt.names()}
    return bool(names & {"vbmeta", "vbmeta_a", "vbmeta_b"})
