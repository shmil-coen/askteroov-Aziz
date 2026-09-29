# -*- coding: utf-8 -*-
"""
טביעת אצבע לזהות מכשיר — משמשת את פייפליין הרוטינג (root_pipeline) כדי לוודא
שהמכשיר לא "התחלף" בין שלבים (חיבור מחדש, מעבר BROM<->Fastboot בארכיטקטורה 2).

אין שדה בודד שהוא "מזהה ייחודי" אמין על פני כל שבבי MediaTek — לכן משתמשים
בטופל מנורמל של כמה שדות שיחד נותנים ודאות סבירה. עיקרון-על: אי-ודאות => עצירה.
ראו: "רוטינג אוטומטי במצב ברום.txt" בתיקיית הפרויקט (סעיף טביעת אצבע).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceIdentity:
    hw_code: str = ""       # למשל "6785"
    hw_version: str = ""    # למשל "ca00"
    soc_id: str = ""        # hex ארוך, אם דווח בפלט
    meid: str = ""          # hex, אם דווח בפלט
    brom_version: str = ""

    def known_fields(self) -> tuple[str, ...]:
        return tuple(v for v in (self.hw_code, self.hw_version, self.soc_id,
                                  self.meid, self.brom_version) if v)

    def is_sufficient(self) -> bool:
        """צריך לפחות 2 שדות ידועים כדי שהשוואה תהיה בעלת משמעות."""
        return len(self.known_fields()) >= 2

    def matches(self, other: "DeviceIdentity") -> bool:
        """
        התאמה = כל שדה שידוע בשני הצדדים זהה, ויש לפחות 2 שדות משותפים להשוואה.
        פחות מ-2 שדות משותפים = חוסר ודאות = נחשב כאי-התאמה (לא "בסדר בהיעדר מידע").
        """
        common = []
        for a, b in ((self.hw_code, other.hw_code), (self.hw_version, other.hw_version),
                     (self.soc_id, other.soc_id), (self.meid, other.meid),
                     (self.brom_version, other.brom_version)):
            if a and b:
                common.append(a.lower() == b.lower())
        if len(common) < 2:
            return False
        return all(common)

    def summary(self) -> str:
        parts = []
        if self.hw_code:
            parts.append(f"HW code=0x{self.hw_code}")
        if self.hw_version:
            parts.append(f"HW ver=0x{self.hw_version}")
        if self.soc_id:
            parts.append(f"SOC ID={self.soc_id[:16]}…")
        if self.meid:
            parts.append(f"MEID={self.meid}")
        if self.brom_version:
            parts.append(f"BROM={self.brom_version}")
        return ", ".join(parts) if parts else "לא זוהו שדות זהות"


_HWCODE_RE = re.compile(r"HW\s*code\s*:\s*0x([0-9a-fA-F]+)", re.IGNORECASE)
_HWVER_RE = re.compile(r"HW\s*(?:sub\s*)?version\s*:\s*0x([0-9a-fA-F]+)", re.IGNORECASE)
_SOCID_RE = re.compile(r"SOC\s*ID\s*:\s*([0-9a-fA-F]{16,})", re.IGNORECASE)
_MEID_RE = re.compile(r"\bMEID\s*:\s*([0-9a-fA-F]{8,})", re.IGNORECASE)
_BROMVER_RE = re.compile(r"BROM\s*ver\w*\s*:\s*(\S+)", re.IGNORECASE)


def parse_identity(text: str) -> DeviceIdentity:
    """מחלץ טביעת אצבע מפלט mtkclient גולמי (printgpt / gettargetconfig / handshake)."""
    def _find(rx: re.Pattern) -> str:
        m = rx.search(text or "")
        return m.group(1) if m else ""

    return DeviceIdentity(
        hw_code=_find(_HWCODE_RE),
        hw_version=_find(_HWVER_RE),
        soc_id=_find(_SOCID_RE),
        meid=_find(_MEID_RE),
        brom_version=_find(_BROMVER_RE),
    )


class IdentityMismatch(RuntimeError):
    """נזרק כשטביעת האצבע לא תואמת בין שני שלבים בפייפליין (uncertainty=STOP)."""
