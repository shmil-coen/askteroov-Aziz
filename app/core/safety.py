# -*- coding: utf-8 -*-
"""
מודול בטיחות: בדיקות לפני פעולות מסוכנות.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .config import SENSITIVE_PARTITIONS


def get_partition_warning(name: str) -> Optional[str]:
    """מחזיר אזהרה למחיצה רגישה, או None אם אין."""
    key = name.lower()
    for known, warning in SENSITIVE_PARTITIONS.items():
        if key == known or key.startswith(known):
            return warning
    return None


def validate_image_size(image_path: Path, partition_length: int) -> tuple[bool, str]:
    """
    בודק שקובץ ה-Image נכנס למחיצה.
    מחזיר (תקין, הודעה).
    """
    actual = image_path.stat().st_size
    if actual > partition_length:
        return False, (
            f"קובץ ה-Image ({actual:,} בתים) גדול מגודל המחיצה "
            f"({partition_length:,} בתים) — הצריבה תיכשל או תזיק!"
        )
    if actual < partition_length // 2:
        return True, (
            f"הערה: הקובץ קטן בהרבה מהמחיצה "
            f"({actual:,} מול {partition_length:,} בתים) — ודא שזה הקובץ הנכון."
        )
    return True, "גודל הקובץ תואם למחיצה."

