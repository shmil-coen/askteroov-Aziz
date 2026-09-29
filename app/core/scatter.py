# -*- coding: utf-8 -*-
"""
מחולל Scatter: המרת טבלת GPT לקובץ Android_scatter.txt תקני (עבור SP Flash Tool).

הפורמט מבוסס על קובצי Scatter של ייצור (factory) עבור מעבדי MediaTek
מודרניים (MT67xx/MT68xx).

אסור ליצור Scatter בלי שם מעבד: ה-platform חייב להיות שם אמיתי
(למשל MT6580), והשם נכנס גם לשם הקובץ (Android_scatter_MT6580.txt)
כדי שקובץ של מעבד אחד לא ידרוס קובץ של מעבד אחר.

שדות ה"כללי" (General Setting):
    config_version / platform / project / storage / block_size

שדות כל מחיצה (Layout Setting) — בדיוק הסדר והשמות ש-SP Flash Tool מצפה להם:
    partition_index · partition_name · file_name · is_download · type
    linear_start_addr · physical_start_addr · partition_size · region
    storage · boundary_check · is_reserved · operation_type
    is_upgradable · empty_boot_needed · reserve

אזהרה: הוספת שדה שאינו מוכר עלולה לגרום לשגיאה
"Unknown scatter field" (0xc003000d) ב-SP Flash Tool.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .gpt_parser import GptTable, Partition

# גודל גוש ברירת מחדל (eMMC) עבור מעבדים מודרניים — ניתן לשינוי מה-UI
DEFAULT_BLOCK_SIZE = 0x200000

# ערכים שנחשבים ל"אין שם מעבד" — Scatter חייב שם platform אמיתי
PLACEHOLDER_CHIPS = {"", "mtxxxx", "xxxx", "mt", "mtk", "unknown", "n/a", "none"}

# אזור ה-eMMC שבו יושב ה-Preloader
PRELOADER_REGION = "EMMC_BOOT_1"
# גודל ברירת מחדל של רשומת ה-Preloader (EMMC_BOOT_1) ושל טבלאות ה-GPT
PRELOADER_SIZE = 0x40000
PGPT_SIZE = 0x80000
SGPT_SIZE = 0x80000
# כתובת "וירטואלית" ש-SP Flash Tool מצפה לה עבור sgpt (סוף הדיסק)
SGPT_VIRTUAL_ADDR = 0xFFFF0000

# מעבדים ישנים (eMMC עם block קטן) — block_size 0x20000
_SMALL_BLOCK_CHIPS = {
    "MT6572", "MT6580", "MT6582", "MT6592", "MT6595", "MT6735", "MT6737",
    "MT6750", "MT6753", "MT6755", "MT6795", "MT8127", "MT8163", "MT8321",
}


def default_block_size(chip_name: str) -> int:
    """block_size מומלץ לפי המעבד (ישנים: 0x20000, מודרניים: 0x200000)."""
    chip = (chip_name or "").strip().upper()
    if chip in _SMALL_BLOCK_CHIPS or re.fullmatch(r"MT65\d\d", chip):
        return 0x20000
    return DEFAULT_BLOCK_SIZE

# מחיצות שמערכת הקבצים שלהן EXT4 → נטענות כ-EXT4_IMG וניתנות להורדה
_EXT4_PARTS = {
    "system", "vendor", "product", "odm", "system_ext", "cust", "customer",
    "userdata", "cache", "preload", "odm_dlkm", "vendor_dlkm", "my_product",
    "my_manifest", "my_carrier", "my_company", "my_heytap", "my_stock",
    "my_bigball", "my_engineering", "my_region",
}

# מחיצות תמונת-אתחול (NORMAL_ROM) שניתנות להורדה
_IMAGE_ROMS = {
    "boot", "recovery", "dtbo", "vbmeta", "vbmeta_system", "vbmeta_vendor",
    "logo", "tee", "tee1", "tee2", "super", "scp", "sspm", "mcupm", "spmfw", "md1img",
    "md1dsp", "md1rom", "dpm", "pi_img", "gz", "gz2", "lk", "lk2", "boot_para",
}

# מחיצות הגנה/מערכת — operation_type PROTECTED
_PROTECTED_PARTS = {
    "protect1", "protect2", "seccfg", "frp", "nvram", "nvdata", "nvcfg",
    "persist", "efuse", "proinfo", "misc", "para", "pgpt", "metadata",
    "md_udc", "sec1", "keystore", "prodnv", "flashinfo", "oem_keystore",
    "oemkeystore", "secro",
}

# מחיצות שאין להוריד (INVISIBLE) גם אם הן לא ב-_PROTECTED_PARTS
_INVISIBLE_PARTS = {
    "pgpt", "sgpt", "para", "expdb", "nvram", "nvdata", "nvcfg", "proinfo",
    "misc", "metadata", "flashinfo", "seccfg", "frp", "protect1", "protect2",
    "oemkeystore", "secro", "keystore", "md_udc",
}

# מחיצות "אזור בינארי" — נשמרות גם ב-Format All של SP Flash (IMEI, כיול)
_BINREGION_PARTS = {"nvram"}

_FILE_EXT = {
    "EXT4_IMG": ".img",
    "NORMAL_ROM": ".img",
}


def _sanitize(name: str) -> str:
    """שם מחיצה תקין ל-Scatter (אותיות, ספרות, קו תחתון)."""
    clean = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not clean or clean[0].isdigit():
        clean = "p_" + clean
    return clean


def _hex(val: int) -> str:
    return f"0x{val:08x}"


def is_placeholder_chip(chip_name: str) -> bool:
    """האם שם המעבד ריק/מומצא (MTxxxx וכדומה) ולא שם אמיתי."""
    return chip_name.strip().lower() in PLACEHOLDER_CHIPS


def scatter_filename(chip_name: str) -> str:
    """
    שם קובץ Scatter הכולל את שם המעבד — כדי ששני מעבדים שונים לא יידרסו
    זה את זה, ושניתן יהיה לזהות את הקובץ גם מחוץ לתיקיית המעבד בבנק.
    """
    return f"Android_scatter_{_sanitize(chip_name)}.txt"


def classify(part: Partition) -> dict:
    """
    מסווג מחיצה לשדות ה-Scatter: type / region / operation_type /
    is_download / is_upgradable / file_name.
    """
    low = part.name.lower()

    # ---- Preloader: מקרה מיוחד
    if low in ("preloader", "preloader_raw", "preloader_bak"):
        return {
            "type": "SV5_BL_BIN",
            "region": PRELOADER_REGION,
            "operation_type": "BOOTLOADERS",
            "is_download": True,
            "is_upgradable": False,
            "file_name": "preloader.bin",
            "start_override": 0,
            "size_override": PRELOADER_SIZE if low == "preloader" else None,
        }

    # ---- טבלאות GPT
    if low == "pgpt":
        return {
            "type": "NORMAL_ROM", "region": "EMMC_USER",
            "operation_type": "INVISIBLE", "is_download": False,
            "is_upgradable": False, "file_name": "NONE",
        }
    if low == "sgpt":
        return {
            "type": "NORMAL_ROM", "region": "EMMC_USER",
            "operation_type": "RESERVED", "is_download": False,
            "is_upgradable": False, "file_name": "NONE",
            "start_override": SGPT_VIRTUAL_ADDR, "physical_override": 0,
            "is_reserved": True, "boundary_check": False,
        }

    # ---- NVRAM: BINREGION — כדי ש-Format All לא ימחק IMEI
    if low in _BINREGION_PARTS:
        return {
            "type": "BINREGION", "region": "EMMC_USER",
            "operation_type": "BINREGION", "is_download": False,
            "is_upgradable": False, "file_name": "NONE",
        }

    # ---- הגנה/מערכת פנימית
    if low in _PROTECTED_PARTS:
        return {
            "type": "NORMAL_ROM",
            "region": "EMMC_USER",
            "operation_type": "PROTECTED" if low not in _INVISIBLE_PARTS else "INVISIBLE",
            "is_download": False,
            "is_upgradable": False,
            "file_name": "NONE",
        }

    # ---- מערכות קבצים EXT4
    if low in _EXT4_PARTS:
        return {
            "type": "EXT4_IMG",
            "region": "EMMC_USER",
            "operation_type": "UPDATE",
            "is_download": True,
            "is_upgradable": low not in ("userdata", "cache"),
            "file_name": f"{_sanitize(part.name)}.img",
        }

    # ---- תמונות אתחול
    if low in _IMAGE_ROMS:
        return {
            "type": "NORMAL_ROM",
            "region": "EMMC_USER",
            "operation_type": "UPDATE",
            "is_download": True,
            "is_upgradable": True,
            "file_name": f"{_sanitize(part.name)}.img",
        }

    # ---- ברירת מחדל: מחיצת נתונים גולמית, לא נורדת
    return {
        "type": "NORMAL_ROM",
        "region": "EMMC_USER",
        "operation_type": "INVISIBLE",
        "is_download": False,
        "is_upgradable": False,
        "file_name": "NONE",
    }


def _header(title: str) -> list[str]:
    bar = "#" * 108
    return [bar, "#", f"# {title}", "#", bar]


def _general_section(chip_name: str, block_size: int) -> list[str]:
    """הזחה בדיוק כמו בקבצי ייצור: config_version ב-4 רווחים, השדות ב-6."""
    return [
        "- general: MTK_PLATFORM_CFG",
        "  info: ",
        "    - config_version: V1.1.2",
        f"      platform: {chip_name}",
        f"      project: {chip_name}",
        "      storage: EMMC",
        f"      block_size: 0x{block_size:x}",
    ]


def _partition_block(index: int, part: Partition) -> list[str]:
    info = classify(part)
    start = info.get("start_override")
    if start is None:
        start = part.offset
    phys = info.get("physical_override")
    if phys is None:
        phys = start
    size = info.get("size_override") or part.length
    # מפריד המחיצה בעמודה 0 והשדות ב-2 רווחים — בדיוק כמו בקבצי ייצור.
    # הזחה שונה גורמת ל-SP Flash Tool להחזיר S_DL_SCAT_INCORRECT_FORMAT (5011).
    return [
        f"- partition_index: SYS{index}",
        f"  partition_name: {_sanitize(part.name)}",
        f"  file_name: {info['file_name']}",
        f"  is_download: {'true' if info['is_download'] else 'false'}",
        f"  type: {info['type']}",
        f"  linear_start_addr: {_hex(start)}",
        f"  physical_start_addr: {_hex(phys)}",
        f"  partition_size: {_hex(size)}",
        f"  region: {info['region']}",
        "  storage: HW_STORAGE_EMMC",
        f"  boundary_check: {'true' if info.get('boundary_check', True) else 'false'}",
        f"  is_reserved: {'true' if info.get('is_reserved', False) else 'false'}",
        f"  operation_type: {info['operation_type']}",
        f"  is_upgradable: {'true' if info['is_upgradable'] else 'false'}",
        "  empty_boot_needed: false",
        "  reserve: 0x0",
        "",
    ]


def full_layout(table: GptTable) -> list[Partition]:
    """
    רשימת המחיצות המלאה ל-Scatter, כמו בקובצי ייצור:
      preloader (EMMC_BOOT_1) ← pgpt ← מחיצות ה-GPT ← sgpt
    ב-MT65xx/MT67xx ה-Preloader וטבלאות ה-GPT אינם מופיעים ב-printgpt,
    ובלעדיהם SP Flash Tool לא יעבוד כראוי.
    """
    parts = list(table.partitions)
    names = {p.name.lower() for p in parts}
    head: list[Partition] = []
    if "preloader" not in names:
        head.append(Partition(name="preloader", offset=0, length=PRELOADER_SIZE))
    user_offsets = [p.offset for p in parts
                    if not p.name.lower().startswith("preloader")]
    first_user = min(user_offsets) if user_offsets else 0
    if "pgpt" not in names and first_user >= PGPT_SIZE:
        head.append(Partition(name="pgpt", offset=0, length=PGPT_SIZE))
    # preloader קיים ב-GPT → נשאר ראשון
    pre = [p for p in parts if p.name.lower() == "preloader"]
    rest = [p for p in parts if p.name.lower() != "preloader"]
    tail: list[Partition] = []
    if "sgpt" not in names:
        tail.append(Partition(name="sgpt", offset=SGPT_VIRTUAL_ADDR, length=SGPT_SIZE))
    return pre + head + rest + tail


def generate_scatter(
    table: GptTable,
    output_path: Path,
    chip_name: str,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> Path:
    """
    כותב קובץ Android_scatter.txt תקני מתוך טבלת GPT.

    :param table: טבלת המחיצות שנקראה מ-GPT
    :param output_path: נתיב היעד
    :param chip_name: שם הפלטפורמה (למשל MT6580) — חובה, אסור "MTxxxx"
    :param block_size: גודל הגוש המוצהר (ברירת מחדל 0x200000)
    :raises ValueError: אם חסר שם מעבד אמיתי
    """
    if is_placeholder_chip(chip_name):
        raise ValueError(
            "חסר שם מעבד (platform) — לא נוצר Scatter בלי שם מעבד. "
            "הזן דגם אמיתי, למשל MT6580.")

    lines: list[str] = []
    lines += _header("General Setting")
    lines += _general_section(chip_name, block_size)

    lines += _header("Layout Setting")
    for index, part in enumerate(full_layout(table)):
        lines += _partition_block(index, part)

    lines += [
        "#" * 108,
        f"# Generated by Askateroov at {datetime.now().isoformat(timespec='seconds')}",
        f"# Platform: {chip_name}",
        f"# GPT partitions: {len(table.partitions)} | "
        f"Disk size: {table.total_size} bytes "
        f"({table.total_size / (1024 ** 3):.2f} GiB)",
        "",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # קבצי Scatter של ייצור נכתבים בשורות CRLF (Windows) — SP Flash Tool רגיש לכך
    output_path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return output_path


# ---------------------------------------------------------------- אימות

_REQUIRED_PART_FIELDS = (
    "partition_index",
    "partition_name",
    "file_name",
    "is_download",
    "type",
    "linear_start_addr",
    "physical_start_addr",
    "partition_size",
    "region",
    "storage",
    "boundary_check",
    "is_reserved",
    "operation_type",
    "is_upgradable",
    "empty_boot_needed",
    "reserve",
)

_ALLOWED_PART_FIELDS = set(_REQUIRED_PART_FIELDS)
_ALLOWED_GENERAL_FIELDS = {
    "config_version", "platform", "project", "project_id", "storage",
    "block_size", "boot_channel",
}


def validate_scatter(path: Path) -> list[str]:
    """
    בודק שקובץ Scatter תקין ל-SP Flash Tool.
    מחזיר רשימת בעיות — רשימה ריקה משמעה שהקובץ תקין.
    """
    problems: list[str] = []
    p = Path(path)
    if not p.is_file():
        return [f"הקובץ לא נמצא: {p}"]

    try:
        raw = p.read_bytes()          # בייטים — כדי לשמר CRLF לבדיקת הפורמט
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        return [f"לא ניתן לקרוא את הקובץ: {e}"]

    if "- general: MTK_PLATFORM_CFG" not in text:
        problems.append("חסרה שורת general: MTK_PLATFORM_CFG")

    # פורמט פיזי: שורות CRLF — LF בלבד גורם ל-SP Flash Tool להחזיר 5011
    if "\r\n" not in text:
        problems.append(
            "הקובץ אינו בקידוד CRLF (שורות Windows)\u200f — SP Flash Tool עלול לדחות אותו (5011)")
    if not text.endswith("\r\n"):
        problems.append("הקובץ אינו מסתיים בשורה חדשה")

    # מפריד המחיצה חייב להיות בעמודה 0: '- partition_index: SYSx'
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("- partition_index:"):
            if not line.startswith("- partition_index:"):
                problems.append(
                    f"שורה {i}: המפריד '- partition_index' חייב להיות בעמודה 0 "
                    "(הזחה שגויה גורמת 5011)")
            break

    # מפסיקים את הקובץ לשני אזורים: "כללי" ו"מחיצות".
    # סעיף כללי מכיל שדות כמו storage/block_size שחוזרים גם בכל מחיצה,
    # ולכן חייבים לבדוק כל אזור בנפרד.
    general_pairs: list[tuple[str, str]] = []
    part_pairs: list[tuple[str, str]] = []
    in_partitions = False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.lstrip("- ").strip()
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k == "partition_index":
            in_partitions = True
        (part_pairs if in_partitions else general_pairs).append((k, v))

    names = [k for k, _ in part_pairs]

    # שדות לא מוכרים בסעיף הכללי → שגיאה ב-SP Flash
    for k in sorted({k for k, _ in general_pairs
                     if k not in _ALLOWED_GENERAL_FIELDS
                     and k not in ("general", "info")}):
        problems.append(
            f"שדה כללי לא מוכר (עלול לגרום 'Unknown scatter field'): {k}")

    # שדות לא מוכרים בתוך המחיצות
    for k in sorted({k for k in names
                     if k not in _ALLOWED_PART_FIELDS}):
        problems.append(
            f"שדה מחיצה לא מוכר (עלול לגרום 'Unknown scatter field'): {k}")

    # SP Flash Tool צריך רשומת preloader
    part_names = [v.lower() for k, v in part_pairs if k == "partition_name"]
    if "preloader" not in part_names:
        problems.append("חסרה מחיצת preloader — SP Flash Tool לא יוכל לצרוב")

    # כל בלוק מחיצה חייב להכיל את כל השדות הנדרשים
    index_values = [v for k, v in part_pairs if k == "partition_index"]
    if not index_values:
        problems.append("לא נמצאו מחיצות (partition_index חסר)")
        return problems

    # אינדקסים רציפים SYS0..SYSn-1
    expected = [f"SYS{i}" for i in range(len(index_values))]
    if index_values != expected:
        problems.append(
            f"partition_index אינו רציף — צפוי {expected[:3]}… "
            f"והתקבל {index_values[:3]}…")

    # ספירת שדות נדרשים לכל מחיצה
    counts = {k: names.count(k) for k in _REQUIRED_PART_FIELDS}
    n = len(index_values)
    for k, c in counts.items():
        if c != n:
            problems.append(
                f"השדה '{k}' מופיע {c} פעמים במקום {n}")

    return problems
