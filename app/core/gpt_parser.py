# -*- coding: utf-8 -*-
"""
מנתח פלט GPT מ-mtkclient (printgpt) ומחיצות ל-Scatter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Partition:
    name: str
    offset: int      # bytes
    length: int      # bytes
    flags: str = ""  # מחרוזת hex מה-GPT
    uuid: str = ""   # מזהה ייחודי של המחיצה
    ptype: str = ""  # סוג המחיצה מה-GPT

    @property
    def end(self) -> int:
        return self.offset + self.length

    def to_dict(self) -> dict:
        return {"name": self.name, "offset": self.offset, "length": self.length,
                "flags": self.flags, "uuid": self.uuid, "ptype": self.ptype}


@dataclass
class GptTable:
    partitions: list[Partition] = field(default_factory=list)
    total_size: int = 0
    total_sectors: int = 0
    cpu: str = ""   # שם המעבד שזוהה מהפלט (למשל MT6580)

    def names(self) -> list[str]:
        return [p.name for p in self.partitions]

    def get(self, name: str) -> Partition | None:
        for p in self.partitions:
            if p.name.lower() == name.lower():
                return p
        return None


# שורה:  "partition_name:  Offset 0x0000000000040000, Length 0x0000000000200000"
_LINE_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9_\-\.]+?)\s*:\s*"
    r"Offset\s+0x(?P<offset>[0-9a-fA-F]+)\s*,\s*"
    r"Length\s+0x(?P<length>[0-9a-fA-F]+)",
    re.MULTILINE,
)

# שורת המשך: "Flags 0x00000000, UUID 11111111-..., Type {..}"
_FLAGS_RE = re.compile(
    r"Flags\s+0x(?P<flags>[0-9a-fA-F]+)\s*,\s*"
    r"UUID\s+(?P<uuid>[0-9a-fA-F\-]+)\s*,\s*"
    r"Type\s+(?P<type>.+)",
)

# סה"כ גודל: "Total disk size:0x00000003a3e60000, sectors:0x0000000074000000"
_TOTAL_RE = re.compile(
    r"Total disk size\s*:\s*0x(?P<size>[0-9a-fA-F]+)"
    r"(?:,\s*sectors\s*:\s*0x(?P<sectors>[0-9a-fA-F]+))?"
)

# זיהוי המעבד:  "Preloader - \tCPU:\t\t\tMT6580()"  או  "CPU: 0x6580"
_CPU_RE = re.compile(
    r"CPU\s*:\s*(?P<val>MT\s*\d{4}|0x[0-9a-fA-F]+)", re.IGNORECASE)
# "Preloader - HW code:\t\t\t0x6580"
_HWCODE_RE = re.compile(r"HW\s*code\s*:\s*0x(?P<code>[0-9a-fA-F]+)")


def parse_cpu_name(text: str) -> str:
    """
    מחלץ את שם המעבד (platform) מפלט mtkclient.
    מחזיר מחרוזת ריקה אם לא זוהה — ואז אסור ליצור Scatter "בלי שם מעבד".
    """
    m = _CPU_RE.search(text)
    if m:
        val = m.group("val").replace(" ", "")
        if val.lower().startswith("0x"):
            return "MT" + val[2:].lower()
        return val.upper()
    m = _HWCODE_RE.search(text)
    if m:
        return "MT" + m.group("code").lower()
    return ""


def parse_gpt_output(text: str) -> GptTable:
    """מנתח את הפלט של mtk printgpt — כולל Flags, UUID ו-Type לכל מחיצה."""
    table = GptTable(cpu=parse_cpu_name(text))
    m = _TOTAL_RE.search(text)
    if m:
        table.total_size = int(m.group("size"), 16)
        if m.group("sectors"):
            table.total_sectors = int(m.group("sectors"), 16)
    for m in _LINE_RE.finditer(text):
        name = m.group("name").rstrip(":")
        end_of_line = text.find("\n", m.end())
        tail = text[m.end(): end_of_line if end_of_line != -1 else len(text)]
        # שורת ההמשך (Flags/UUID/Type) מופיעה בשורה שאחרי
        next_line_end = text.find("\n", end_of_line + 1) if end_of_line != -1 else -1
        cont = text[end_of_line + 1: next_line_end if next_line_end != -1 else len(text)]
        flags = uuid = ptype = ""
        fm = _FLAGS_RE.search(cont) or _FLAGS_RE.search(tail)
        if fm:
            flags = "0x" + fm.group("flags")
            uuid = fm.group("uuid")
            ptype = fm.group("type").strip()
        table.partitions.append(
            Partition(
                name=name,
                offset=int(m.group("offset"), 16),
                length=int(m.group("length"), 16),
                flags=flags,
                uuid=uuid,
                ptype=ptype,
            )
        )
    return table


def parse_gpt_file(path: Path) -> GptTable:
    """קריאת קובץ GPT בינארי וחילוץ מחיצות — ללא תלות ב-mtkclient."""
    data = Path(path).read_bytes()
    table = GptTable()

    # איתור חתימת GPT ("EFI PART") בלב 512 או 4096
    sig = b"EFI PART"
    pos = data.find(sig)
    if pos == -1:
        raise ValueError("לא נמצאה חתימת GPT בקובץ")

    import struct
    # LBA size נגזר מהמיקום: header ב-LBA 1 => sector_size = pos (אם pos ב-power of 2)
    sector_size = pos if pos in (512, 4096) else 512
    header = data[pos:pos + 92]
    # GPT header: sig(8) rev(4) hsize(4) crc(4) rsvd(4) myLBA(8) altLBA(8) firstUsable(8)
    #             lastUsable(8) diskGUID(16) partEntryLBA(8) numEntries(4) entrySize(4) ...
    num_entries = struct.unpack_from("<I", header, 80)[0]
    entry_size = struct.unpack_from("<I", header, 84)[0]
    entries_lba = struct.unpack_from("<Q", header, 72)[0]

    base = entries_lba * sector_size
    for i in range(num_entries):
        entry = data[base + i * entry_size: base + (i + 1) * entry_size]
        if len(entry) < entry_size or entry[:16] == b"\x00" * 16:
            continue
        name_utf16 = entry[56:128]
        name = name_utf16.decode("utf-16-le").rstrip("\x00")
        first_lba = struct.unpack_from("<Q", entry, 32)[0]
        last_lba = struct.unpack_from("<Q", entry, 40)[0]
        table.partitions.append(
            Partition(
                name=name,
                offset=first_lba * sector_size,
                length=(last_lba - first_lba + 1) * sector_size,
            )
        )
    return table


# ---------------------------------------------------------------- מצב אבטחה / בוטלאודר

# שדות שמופיעים בפלט gettargetconfig של mtkclient
_SEC_FIELDS = {
    "sbc": "Secure Boot (SBC)",
    "sla": "Serial Link Auth (SLA)",
    "daa": "Download Agent Auth (DAA)",
}
_BOOL_RE = re.compile(r"(?P<key>\w[\w ]*?)\s*[:=]\s*(?P<val>true|false|enabled|disabled|1|0)\b",
                      re.IGNORECASE)


def parse_target_config(text: str) -> dict:
    """
    מחלץ ממצב היעד (gettargetconfig) את שדות האבטחה: SBC / SLA / DAA וכו'.
    מחזיר dict {תווית: True/False}. ריק אם לא זוהה כלום.
    """
    result: dict[str, bool] = {}
    for m in _BOOL_RE.finditer(text):
        key = m.group("key").strip().lower()
        val = m.group("val").lower() in ("true", "enabled", "1")
        for token, label in _SEC_FIELDS.items():
            if token in key:
                result[label] = val
    return result


def summarize_bootloader(sec: dict) -> str:
    """סיכום קריא לאדם של מצב האבטחה."""
    if not sec:
        return "לא זוהו שדות אבטחה בפלט."
    lines = [f"{'🔒' if v else '🔓'} {label}: {'פעיל' if v else 'כבוי'}"
             for label, v in sec.items()]
    sbc = sec.get("Secure Boot (SBC)")
    daa = sec.get("Download Agent Auth (DAA)")
    sla = sec.get("Serial Link Auth (SLA)")
    if sbc is True:
        lines.append("🔒 Secure Boot פעיל — צריבה דורשת חתימה; "
                     "בדרך כלל לא ניתן לצרוב מחיצות חופשי.")
    elif sbc is False:
        lines.append("🔓 אין Secure Boot (SBC כבוי) — במכשירים כאלה "
                     "<b>בדרך כלל אפשר לצרוב מחיצות</b>.")
        lines.append("⚠️ זה <b>לא</b> אומר בהכרח שהבוטלאודר פתוח (unlocked) — "
                     "מצב הנעילה עצמו נבדק בנפרד.")
    lines.append("ℹ️ מצב הנעילה המדויק (נעול/פתוח) נשמר במחיצת seccfg ואינו נקרא "
                 "בבדיקה זו. לפתיחה/נעילה בפועל — הכפתורים בלשונית בוטלאודר.")
    return "\n".join(lines)
