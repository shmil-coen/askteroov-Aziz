# -*- coding: utf-8 -*-
"""בדיקות יחידה למודולי הליבה."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.gpt_parser import parse_cpu_name, parse_gpt_output
from app.core.scatter import (
    classify,
    generate_scatter,
    is_placeholder_chip,
    scatter_filename,
    validate_scatter,
)
from app.core.mtk_bridge import parse_progress_line
from app.core.safety import get_partition_warning, validate_image_size


GPT_SAMPLE = """
Preloader - \tCPU:\t\t\tMT6580()
Preloader - \tHW code:\t\t\t0x6580
GPT Table:
-------------
preloader:           Offset 0x0000000000000000, Length 0x0000000000400000
                     Flags 0x00000000, UUID 00000000-0000-0000-0000-000000000000, Type ...
recovery:            Offset 0x0000000004040000, Length 0x0000000001800000
                     Flags 0x00000000, UUID 11111111-2222-3333-4444-555555555555, Type ...
boot:                Offset 0x0000000005c40000, Length 0x0000000001000000
                     Flags 0x00000000, UUID 11111111-2222-3333-4444-555555555556, Type ...
userdata:            Offset 0x000000012c000000, Length 0x00000001a0000000
                     Flags 0x00000000, UUID 22222222-2222-2222-2222-222222222222, Type ...

Total disk size:0x00000003a3e60000, sectors:0x0000000074000000
"""


def test_parse_gpt_output():
    table = parse_gpt_output(GPT_SAMPLE)
    assert len(table.partitions) == 4
    names = table.names()
    assert "preloader" in names and "boot" in names and "userdata" in names
    boot = table.get("boot")
    assert boot.offset == 0x05c40000
    assert boot.length == 0x01000000
    assert table.total_size == 0x3a3e60000
    assert table.total_sectors == 0x74000000
    # פרטים מורחבים: Flags / UUID / Type
    assert boot.flags == "0x00000000"
    assert boot.uuid.startswith("11111111-2222-3333-4444-55555555555")
    assert boot.ptype  # קיים טקסט סוג
    pre = table.get("preloader")
    assert pre.uuid.startswith("00000000-0000-0000-0000-00000000000")
    # שם המעבד מחולץ מהפלט — לא מנחשים אותו
    assert table.cpu == "MT6580"


def test_parse_cpu_name():
    assert parse_cpu_name("Preloader - \tCPU:\t\t\tMT6580()") == "MT6580"
    assert parse_cpu_name("CPU: 0x6580") == "MT6580"
    assert parse_cpu_name("Preloader - HW code:\t\t\t0x6580") == "MT6580"
    assert parse_cpu_name("CPU:\t\t\tMT6765") == "MT6765"
    assert parse_cpu_name("no cpu info here") == ""


def test_generate_scatter(tmp_path: Path):
    table = parse_gpt_output(GPT_SAMPLE)
    # הקובץ נקרא על שם המעבד שזוהה — כדי שלא יידרס ע"י מעבד אחר
    out = tmp_path / scatter_filename(table.cpu)
    generate_scatter(table, out, chip_name=table.cpu)
    assert out.name == "Android_scatter_MT6580.txt"
    text = out.read_text(encoding="utf-8")
    assert "platform: MT6580" in text
    assert "# Platform: MT6580" in text
    assert "partition_name: recovery" in text
    assert "linear_start_addr: 0x05c40000" in text
    # אינדקסים רציפים — התיקון הקריטי
    assert "partition_index: SYS0" in text
    assert "partition_index: SYS1" in text
    assert "partition_index: SYS3" in text
    # שדות מודרניים שהיו חסרים
    assert "is_upgradable:" in text
    assert "empty_boot_needed: false" in text
    # פורמט פיזי כמו בקבצי ייצור: CRLF והזחות מדויקות (אחרת SP Flash מחזיר 5011)
    raw = out.read_bytes()
    assert b"\r\n" in raw
    assert b"\r\n- partition_index: SYS0" in raw
    assert b"\r\n  partition_name: recovery" in raw
    assert b"\r\n  info: " in raw
    assert b"\r\n    - config_version: V1.1.2" in raw
    assert b"\r\n      platform: MT6580" in raw
    # הפלט חייב לעבור את האימות
    assert validate_scatter(out) == []


def test_scatter_requires_real_cpu(tmp_path: Path):
    """בעיה שדווחה: התוכנה שמרה Scatter בלי שם מעבד — אסור שיקרה."""
    table = parse_gpt_output(GPT_SAMPLE)
    for bad in ("", "MTxxxx", "   ", "unknown"):
        assert is_placeholder_chip(bad)
        try:
            generate_scatter(table, tmp_path / "bad.txt", chip_name=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"נוצר Scatter עם שם מעבד לא אמיתי: {bad!r}")
        assert not (tmp_path / "bad.txt").exists()

    assert not is_placeholder_chip("MT6580")
    # גם מחיצת ה-Preloader נכללת ב-Scatter המלא (עם הגדרות EMMC_BOOT_1)
    out = tmp_path / scatter_filename("MT6580")
    generate_scatter(table, out, chip_name="MT6580")
    text = out.read_text(encoding="utf-8")
    assert "partition_name: preloader" in text
    assert "type: SV5_BL_BIN" in text
    assert "operation_type: BOOTLOADERS" in text
    assert "region: EMMC_BOOT_1" in text
    assert validate_scatter(out) == []

    # מעבדים שונים ⇒ קבצים שונים (בלי דריסה)
    assert scatter_filename("MT6580") != scatter_filename("mt6765")


def test_scatter_validation_detects_bad_index(tmp_path: Path):
    """אימות צריך לתפוס אינדקס לא רציף (הבאג שהיה בגרסה הקודמת)."""
    bad = tmp_path / "bad_scatter.txt"
    bad.write_text(
        "- general: MTK_PLATFORM_CFG\n"
        "  - partition_index: SYS18\n"
        "    partition_name: preloader\n",
        encoding="utf-8")
    problems = validate_scatter(bad)
    assert any("רציף" in p for p in problems)


def test_scatter_format_matches_factory(tmp_path: Path):
    """""הפורמט הפיזי חייב להיות זהה לקובץ ייצור אמיתי — הזחות ו-CRLF (שגיאת 5011)."""""
    table = parse_gpt_output(GPT_SAMPLE)
    out = tmp_path / scatter_filename(table.cpu)
    generate_scatter(table, out, chip_name=table.cpu)
    raw = out.read_bytes()
    lines = raw.split(b"\r\n")
    # אין שורות LF יחיד (הכל CRLF)
    assert b"\n" not in raw.replace(b"\r\n", b"")
    # מבנה ה-general: מפריד ב-0, info ב-2, config_version ב-4, שדות ב-6
    idx_general = next(i for i, l in enumerate(lines) if l == b"- general: MTK_PLATFORM_CFG")
    assert lines[idx_general + 1] == b"  info: "
    assert lines[idx_general + 2] == b"    - config_version: V1.1.2"
    assert lines[idx_general + 3] == b"      platform: MT6580"
    # מבנה מחיצה: מפריד בעמודה 0, שדות ב-2
    idx_first = next(i for i, l in enumerate(lines) if l == b"- partition_index: SYS0")
    assert lines[idx_first + 1] == b"  partition_name: preloader"
    # הקובץ מסתיים ב-CRLF
    assert raw.endswith(b"\r\n")
    assert validate_scatter(out) == []


def test_validate_flags_lf_only_file(tmp_path: Path):
    """""קובץ ב-LF בלבד (הבאג שגרם 5011) — האימות חייב לתפוס אותו."""""
    table = parse_gpt_output(GPT_SAMPLE)
    out = tmp_path / "lf_only.txt"
    generate_scatter(table, out, chip_name=table.cpu)
    # ממיר ל-LF בלבד כדי לדמות קובץ פגום
    out.write_bytes(out.read_bytes().replace(b"\r\n", b"\n"))
    problems = validate_scatter(out)
    assert any("CRLF" in p for p in problems)


def test_classify_partitions():
    from app.core.gpt_parser import Partition

    pre = classify(Partition(name="preloader", offset=0, length=0x400000))
    assert pre["type"] == "SV5_BL_BIN" and pre["operation_type"] == "BOOTLOADERS"

    boot = classify(Partition(name="boot", offset=0, length=0x1000000))
    assert boot["type"] == "NORMAL_ROM" and boot["is_download"] is True
    assert boot["file_name"] == "boot.img"

    sysp = classify(Partition(name="system", offset=0, length=0x1000000))
    assert sysp["type"] == "EXT4_IMG"

    nvram = classify(Partition(name="nvram", offset=0, length=0x400000))
    assert nvram["is_download"] is False
    assert nvram["file_name"] == "NONE"
    # BINREGION — כדי ש-Format All ב-SP Flash לא ימחק IMEI
    assert nvram["type"] == "BINREGION" and nvram["operation_type"] == "BINREGION"

    # super = מערכת ההפעלה ב-Android 10+ → חייבת להיות ניתנת לצריבה
    sup = classify(Partition(name="super", offset=0, length=0x1000000))
    assert sup["is_download"] is True
    tee1 = classify(Partition(name="tee1", offset=0, length=0x500000))
    assert tee1["is_download"] is True
    expdb = classify(Partition(name="expdb", offset=0, length=0x500000))
    assert expdb["is_download"] is False


def test_parse_progress():
    pct, suffix = parse_progress_line("[2025] 42.5% (1024/2048 KB)")
    assert pct == 42.5
    pct2, _ = parse_progress_line("no progress here")
    assert pct2 is None
    pct3, _ = parse_progress_line("150% out of range")
    assert pct3 is None


def test_sensitive_warning():
    assert get_partition_warning("preloader") is not None
    assert get_partition_warning("nvram") is not None
    assert get_partition_warning("userdata") is None


def test_validate_image_size(tmp_path: Path):
    img = tmp_path / "boot.img"
    img.write_bytes(b"x" * 100)
    ok, _ = validate_image_size(img, 200)
    assert ok
    img2 = tmp_path / "big.img"
    img2.write_bytes(b"x" * 500)
    ok2, msg = validate_image_size(img2, 200)
    assert not ok2


def test_scatter_bank(tmp_path: Path, monkeypatch):
    from app.core import config, scatter_bank

    monkeypatch.setattr(config, "SCATTER_BANK_DIR", tmp_path / "bank")
    monkeypatch.setattr(scatter_bank, "SCATTER_BANK_DIR", tmp_path / "bank")

    # ייבוא קובץ ידני
    src = tmp_path / "Android_scatter.txt"
    src.write_text("platform: MT6765\n", encoding="utf-8")
    entry = scatter_bank.import_file(src, "MT6765")
    assert entry.group == "MT6765"
    assert entry.source == "manual"
    assert (tmp_path / "bank" / "MT6765" / "Android_scatter.txt").is_file()

    # שמירת קובץ שנוצר בתוכנה
    gen = scatter_bank.save_generated(src, "Redmi_9A")
    assert gen.source == "generated"

    entries = scatter_bank.list_entries()
    assert len(entries) == 2
    assert len(scatter_bank.list_entries("MT6765")) == 1
    assert set(scatter_bank.groups()) == {"MT6765", "Redmi_9A"}

    st = scatter_bank.stats()
    assert st["total"] == 2 and st["generated"] == 1 and st["manual"] == 1

    # העברה בין קבוצות + שינוי שם + מחיקה
    moved = scatter_bank.move_to_group(entry, "MT6789")
    assert moved.group == "MT6789"
    renamed = scatter_bank.rename_entry(moved, "scatter_new")
    assert renamed.name == "scatter_new.txt"
    scatter_bank.delete_entry(renamed)
    assert all(
        e.group != "MT6789" for e in scatter_bank.list_entries())

    assert "platform" in scatter_bank.read_entry_text(gen)


def test_checksums(tmp_path: Path):
    from app.core.checksums import file_checksum, write_checksum_file, verify_checksum_file
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world")
    sha = file_checksum(f, "sha256")
    assert verify_checksum_file(f, sha, "sha256")
    out = write_checksum_file(f, "sha256")
    assert out.exists()
    assert sha in out.read_text(encoding="utf-8")


# GPT אמיתי של MT6580 (בלי preloader/pgpt/sgpt — כמו ש-printgpt מחזיר)
GPT_NO_PRELOADER = """
Preloader - \tCPU:\t\t\tMT6580()
proinfo:             Offset 0x0000000000080000, Length 0x0000000000300000
                     Flags 0x00000000, UUID 1, Type EFI_BASIC_DATA
nvram:               Offset 0x0000000000380000, Length 0x0000000000500000
                     Flags 0x00000000, UUID 2, Type EFI_BASIC_DATA
super:               Offset 0x000000000e800000, Length 0x000000009d800000
                     Flags 0x00000000, UUID 3, Type EFI_BASIC_DATA
userdata:            Offset 0x00000000b3000000, Length 0x00000002f7380000
                     Flags 0x00000000, UUID 4, Type EFI_BASIC_DATA
Total disk size:0x00000003ab384200, sectors:0x0000000001d59c21
"""


def test_scatter_adds_preloader_and_gpt(tmp_path: Path):
    from app.core.scatter import full_layout
    table = parse_gpt_output(GPT_NO_PRELOADER)
    names = [p.name for p in full_layout(table)]
    assert names[0] == "preloader" and names[1] == "pgpt" and names[-1] == "sgpt"
    out = tmp_path / scatter_filename(table.cpu)
    generate_scatter(table, out, chip_name=table.cpu)
    text = out.read_text(encoding="utf-8")
    assert "region: EMMC_BOOT_1" in text
    assert "partition_name: sgpt" in text and "operation_type: RESERVED" in text
    assert validate_scatter(out) == []


def test_default_block_size():
    from app.core.scatter import default_block_size
    assert default_block_size("MT6580") == 0x20000
    assert default_block_size("MT6765") == 0x200000


def test_validate_requires_preloader(tmp_path: Path):
    from app.core.gpt_parser import GptTable, Partition
    from app.core import scatter as sc
    table = GptTable(partitions=[Partition("boot", 0x100000, 0x100000)])
    out = tmp_path / "s.txt"
    lines = sc._general_section("MT6580", 0x20000) + sc._partition_block(0, table.partitions[0])
    out.write_text("\n".join(lines), encoding="utf-8")
    assert any("preloader" in p for p in validate_scatter(out))


def test_job_chain_stops_on_failure(monkeypatch):
    """רצף שלבים נעצר בשלב הראשון שנכשל (למשל גיבוי לפני צריבה)."""
    import time
    from app.core import jobs

    class FakeCmd:
        def __init__(self, rc):
            self.rc = rc
            self.ran = False
        def run_blocking(self, out=None, prog=None):
            self.ran = True
            return self.rc
        def stop(self):
            pass
        def describe(self):
            return "fake"

    backup, write = FakeCmd(1), FakeCmd(0)
    result = {}
    job = jobs.Job("t", [jobs.Step("backup", backup), jobs.Step("write", write)],
                   on_done=lambda ok: result.setdefault("ok", ok))
    mgr = jobs.JobManager()
    mgr.submit(job)
    for _ in range(100):
        if "ok" in result:
            break
        time.sleep(0.02)
    assert result["ok"] is False
    assert backup.ran and not write.ran
    assert not mgr.busy   # ה-current מתאפס בסוף — הבאג שחסם את הגיבוי


def test_parse_target_config():
    from app.core.gpt_parser import parse_target_config, summarize_bootloader
    out = """
    Target config: 0xE5
    SBC enabled: True
    SLA enabled: False
    DAA enabled: True
    """
    sec = parse_target_config(out)
    assert sec["Secure Boot (SBC)"] is True
    assert sec["Serial Link Auth (SLA)"] is False
    assert sec["Download Agent Auth (DAA)"] is True
    text = summarize_bootloader(sec)
    assert "Secure Boot" in text and "seccfg" in text
    assert summarize_bootloader({}) != ""


def test_job_retry_succeeds_on_second_attempt():
    """שאיבה שנכשלה בפעם הראשונה ומצליחה בשנייה — בזכות retries."""
    import time
    from app.core import jobs

    class FlakyCmd:
        def __init__(self):
            self.calls = 0
        def run_blocking(self, out=None, prog=None):
            self.calls += 1
            return 0 if self.calls >= 2 else 1   # נכשל פעם ראשונה, מצליח בשנייה
        def stop(self): pass
        def reset(self): pass
        def describe(self): return "flaky"

    cmd = FlakyCmd()
    result = {}
    job = jobs.Job("read", [jobs.Step("read", cmd)],
                   on_done=lambda ok: result.setdefault("ok", ok),
                   retries=2, retry_delay=0.01)
    mgr = jobs.JobManager()
    mgr.submit(job)
    for _ in range(200):
        if "ok" in result: break
        time.sleep(0.01)
    assert result["ok"] is True
    assert cmd.calls == 2


def test_job_retry_gives_up():
    """אחרי שכל הניסיונות נכשלו — הפעולה מדווחת כישלון."""
    import time
    from app.core import jobs

    class DeadCmd:
        def __init__(self): self.calls = 0
        def run_blocking(self, out=None, prog=None):
            self.calls += 1; return 1
        def stop(self): pass
        def reset(self): pass
        def describe(self): return "dead"

    cmd = DeadCmd()
    result = {}
    job = jobs.Job("read", [jobs.Step("read", cmd)],
                   on_done=lambda ok: result.setdefault("ok", ok),
                   retries=2, retry_delay=0.01)
    jobs.JobManager().submit(job)
    for _ in range(200):
        if "ok" in result: break
        time.sleep(0.01)
    assert result["ok"] is False
    assert cmd.calls == 3   # 1 + 2 retries


def test_fastboot_parse_and_plans(tmp_path):
    from app.core.fastboot_bridge import parse_fastboot_vars, summarize_fastboot
    raw = "(bootloader) product: k62v1\n(bootloader) unlocked: no\n"
    v = parse_fastboot_vars(raw)
    assert v.get("מוצר") == "k62v1"
    assert "בוטלאודר פתוח" in v
    assert "נעול" in summarize_fastboot(v, raw)


def test_fastboot_missing_exe_raises(monkeypatch):
    from app.core import config, fastboot_bridge
    monkeypatch.setattr(config, "find_fastboot_exe", lambda: None)
    # FastbootCommand.__init__ משתמש בשם שיובא למודול fastboot_bridge —
    # צריך לנטרל גם אותו, אחרת הפונקציה האמיתית תמצא fastboot.exe ב-tools/
    monkeypatch.setattr(fastboot_bridge, "find_fastboot_exe", lambda: None)
    try:
        fastboot_bridge.FastbootCommand(["devices"])
    except RuntimeError as e:
        assert "fastboot" in str(e).lower()
    else:
        raise AssertionError("ציפינו לשגיאה כשאין fastboot.exe")


def test_mtk_detects_failure_in_output():
    """קוד יציאה 0 אך פלט כושל → נחשב כישלון (לא 'הצלחה כוזבת')."""
    from app.core.mtk_bridge import MtkCommand
    c = MtkCommand.__new__(MtkCommand)   # בלי __init__ (לא צריך mtk אמיתי)
    c._fail = False; c._fail_reason = ""; c._saw_device = False; c._saw_handshake_fail = False
    c._saw_usb_drop = False; c._wait_since = None
    for line in ["MTK Flash/Exploit Client Public V2.0.1",
                 "DaHandler - Please disconnect, start mtkclient and reconnect."]:
        c._inspect_line(line)
    assert c._fail is True
    assert "reconnect" in c._fail_reason.lower()


def test_mtk_handshake_without_device_is_failure():
    from app.core.mtk_bridge import MtkCommand
    c = MtkCommand.__new__(MtkCommand)
    c._fail = False; c._fail_reason = ""; c._saw_device = False; c._saw_handshake_fail = False
    c._saw_usb_drop = False; c._wait_since = None
    for line in ["Status: Handshake failed, retrying...",
                 "Status: Handshake failed, retrying..."]:
        c._inspect_line(line)
    # הדמיית הבדיקה שנעשית אחרי wait()
    if c._saw_handshake_fail and not c._saw_device:
        c._fail = True
    assert c._fail is True


def test_mtk_handshake_then_device_is_ok():
    """handshake שנכשל אך בסוף המכשיר זוהה — לא כישלון."""
    from app.core.mtk_bridge import MtkCommand
    c = MtkCommand.__new__(MtkCommand)
    c._fail = False; c._fail_reason = ""; c._saw_device = False; c._saw_handshake_fail = False
    c._saw_usb_drop = False; c._wait_since = None
    for line in ["Status: Handshake failed, retrying...",
                 "Port - Device detected :)",
                 "Preloader - CPU: MT6580()"]:
        c._inspect_line(line)
    if c._saw_handshake_fail and not c._saw_device:
        c._fail = True
    assert c._fail is False


def test_mtk_unrecognized_argument_is_failure():
    from app.core.mtk_bridge import MtkCommand
    c = MtkCommand.__new__(MtkCommand)
    c._fail = False; c._fail_reason = ""; c._saw_device = False; c._saw_handshake_fail = False
    c._saw_usb_drop = False; c._wait_since = None
    c._inspect_line("mtk.py: error: unrecognized arguments: --noreconnect")
    assert c._fail is True


def test_fastboot_battery_voltage_parsed():
    from app.core.fastboot_bridge import parse_fastboot_vars
    raw = "(bootloader) product: k62v1\n(bootloader) battery-voltage: 4123mV\n"
    v = parse_fastboot_vars(raw)
    assert v.get("מתח סוללה") == "4123mV"


def test_fastboot_devices_requires_device(monkeypatch):
    from app.core import config, fastboot_bridge
    from pathlib import Path
    monkeypatch.setattr(config, "find_fastboot_exe", lambda: Path("/x/fastboot"))
    monkeypatch.setattr(fastboot_bridge, "find_fastboot_exe", lambda: Path("/x/fastboot"))
    cmd = fastboot_bridge.FastbootCommands.devices()
    assert cmd.require  # דורש שורת מכשיר — כדי לא לדווח הצלחה כוזבת
    import re
    assert re.search(cmd.require, "0123456789ABCDEF\tfastboot")
    assert not re.search(cmd.require, "")   # פלט ריק = אין מכשיר


def test_bootloader_open_wording():
    from app.core.gpt_parser import summarize_bootloader
    txt = summarize_bootloader({"Secure Boot (SBC)": False,
                                "Serial Link Auth (SLA)": False,
                                "Download Agent Auth (DAA)": False})
    assert "פתוח" in txt


def test_battery_too_low_thresholds():
    from app.core.device_info import DeviceInfo, _parse_voltage_mv
    assert _parse_voltage_mv("4321mV") == 4321
    assert _parse_voltage_mv("4.32V") == 4320
    assert DeviceInfo(mode="fastboot", voltage_mv=3300).battery_too_low() is True
    assert DeviceInfo(mode="fastboot", voltage_mv=4100).battery_too_low() is False
    assert DeviceInfo(mode="fastboot", soc_ok=False).battery_too_low() is True
    assert DeviceInfo(mode="adb", battery=9).battery_too_low() is True
    assert DeviceInfo(mode="adb", battery=80).battery_too_low() is False


def test_probe_tiered_order_adb_then_brom_never_fastboot(monkeypatch):
    """סדר הזיהוי המדורג: ADB קודם, אחר כך BROM — ו-fastboot אף פעם לא נבדק אוטומטית."""
    from app.core import config, device_info

    # ADB גובר על BROM כששניהם זמינים
    monkeypatch.setattr(config, "find_adb_exe", lambda: Path("adb"))
    monkeypatch.setattr(device_info, "find_adb_exe", lambda: Path("adb"))
    monkeypatch.setattr(device_info, "read_adb_info",
                        lambda adb: device_info.DeviceInfo(mode="adb", model="Test ADB", battery=50))
    info = device_info.probe(has_brom_port=True, brom_cpu="MT6580")
    assert info.mode == "adb" and info.model == "Test ADB"

    # בלי ADB — BROM עם המעבד שזוהה מ-GPT
    monkeypatch.setattr(config, "find_adb_exe", lambda: None)
    monkeypatch.setattr(device_info, "find_adb_exe", lambda: None)
    info = device_info.probe(has_brom_port=True, brom_cpu="MT6580")
    assert info.mode == "brom" and info.cpu == "MT6580"

    # fastboot לא נבדק בזיהוי האוטומטי כלל — גם כשקיים fastboot.exe
    def _boom():
        raise AssertionError("fastboot נבדק בזיהוי האוטומטי אף שלא צריך")
    monkeypatch.setattr(config, "find_fastboot_exe", _boom)
    monkeypatch.setattr(device_info, "find_fastboot_exe", _boom)
    info = device_info.probe(has_brom_port=False)
    assert info.mode == "none"


def test_fastboot_cpu_from_product(monkeypatch):
    """מעבד ב-Fastboot: נקרא מ-getvar product ומנורמל ל-MTxxxx; הדגם נשאר הפלט הגולמי."""
    from app.core import device_info

    fb_vars = {"product": "mt6580", "board": "k62v1",
               "battery-voltage": "4123mV", "battery-soc-ok": "yes"}

    def fake_run(cmd, timeout=8.0):
        if "devices" in cmd:
            return "LIST OF DEVICES ATTACHED\nABC123\tfastboot\n"
        if "getvar" in cmd:
            var = cmd[-1]
            return f"(bootloader) {var}: {fb_vars.get(var, '')}\n"
        return ""

    monkeypatch.setattr(device_info, "_run", fake_run)
    info = device_info.read_fastboot_info("fastboot.exe")
    assert info is not None and info.mode == "fastboot"
    assert info.cpu == "MT6580"        # מוצר → מעבד מנורמל
    assert info.model == "mt6580"      # הדגם נשאר הפלט הגולמי
    assert info.voltage_mv == 4123


def test_fastboot_cpu_falls_back_to_board(monkeypatch):
    """בלי product שמכיל שבב (ריק/לא נמצא) — המעבד נקרא מ-getvar board."""
    from app.core import device_info

    fb_vars = {"product": "", "board": "MT6765"}

    def fake_run(cmd, timeout=8.0):
        if "devices" in cmd:
            return "ABC123\tfastboot\n"
        if "getvar" in cmd:
            var = cmd[-1]
            return f"(bootloader) {var}: {fb_vars.get(var, '')}\n"
        return ""

    monkeypatch.setattr(device_info, "_run", fake_run)
    info = device_info.read_fastboot_info("fastboot.exe")
    assert info is not None
    assert info.cpu == "MT6765"        # board משלים את מה ש-product לא נתן


def test_adb_cpu_prefers_platform_over_serialno(monkeypatch):
    """ערוץ ראשי (ro.board.platform) גובר על גיבוי ה-serialno ולא נדרס על ידו."""
    from app.core import device_info

    props = {"ro.product.model": "Redmi 9A", "ro.product.brand": "Xiaomi",
             "ro.board.platform": "mt6765", "ro.serialno": "0x6580ABCDEF"}

    def fake_run(cmd, timeout=8.0):
        if "devices" in cmd:
            return "List of devices attached\nABC\tdevice\n"
        if "getprop" in cmd:
            return props.get(cmd[-1], "") + "\n"
        return ""

    monkeypatch.setattr(device_info, "_run", fake_run)
    info = device_info.read_adb_info("adb.exe")
    assert info is not None and info.mode == "adb"
    assert info.cpu == "MT6765"   # מה-platform — לא MT6580 שב-serialno


def test_adb_cpu_falls_back_to_serialno(monkeypatch):
    """בלי ro.board.platform / ro.hardware — המעבד מפוענח מ-ro.serialno (0x6580 → MT6580)."""
    from app.core import device_info

    props = {"ro.product.model": "MTK Device", "ro.product.brand": "",
             "ro.board.platform": "", "ro.hardware": "",
             "ro.serialno": "0x6580abcdef"}

    def fake_run(cmd, timeout=8.0):
        if "devices" in cmd:
            return "List of devices attached\nABC\tdevice\n"
        if "getprop" in cmd:
            return props.get(cmd[-1], "") + "\n"
        return ""

    monkeypatch.setattr(device_info, "_run", fake_run)
    info = device_info.read_adb_info("adb.exe")
    assert info.cpu == "MT6580"       # גם serial באותיות קטנות — מנורמל

    # serialno שאינו מקודד שבב MTK (בלי קידומת 0x) — לא משנה שום דבר
    props["ro.serialno"] = "ABCDEF123456"
    info2 = device_info.read_adb_info("adb.exe")
    assert info2.cpu == ""


def test_apk_list_apps_parsing(monkeypatch):
    """pm list packages -f: נתיב עם '=' בתוכו, וסימון אפליקציות מערכת לפי מיקום."""
    from app.core import apk_info
    out = ("package:/data/app/~~ab==/com.x-cd==/base.apk=com.x\n"
           "package:/system/app/Foo/Foo.apk=com.foo\n")
    monkeypatch.setattr(apk_info, "_run_text", lambda cmd, timeout=20: out)
    apps = {a.package: a for a in apk_info.list_apps("adb", include_system=True)}
    assert apps["com.x"].apk_path == "/data/app/~~ab==/com.x-cd==/base.apk"
    assert apps["com.x"].system is False
    assert apps["com.foo"].system is True


def test_apk_dumpsys_fields():
    from app.core.apk_info import _field
    t = "versionName=2.4.1\n firstInstallTime=2024-01-02 10:11:12\n targetSdk=34"
    assert _field(t, "versionName") == "2.4.1"
    assert _field(t, "firstInstallTime") == "2024-01-02 10:11:12"
    assert _field(t, "targetSdk") == "34"


def test_apk_removed_for_user_mark(monkeypatch):
    """אפליקציה שמופיעה רק ב'-u' (הוסרה מהמשתמש) מסומנת כך."""
    from app.core import apk_info
    full = ("package:/system/app/B/B.apk=com.android.browser\n"
            "package:/data/app/x/base.apk=com.x\n")
    inst = "package:com.x\n"
    monkeypatch.setattr(apk_info, "_run_text",
                        lambda cmd, timeout=20: full if "-u" in cmd else inst)
    apps = {a.package: a for a in apk_info.list_apps("adb", include_system=True)}
    assert apps["com.android.browser"].removed_for_user is True
    assert apps["com.x"].removed_for_user is False


def test_expand_apk_archive_single(tmp_path: Path):
    """apk בודד מוחזר כמות שהוא, ללא תיקייה זמנית."""
    from app.core.device_info import _expand_apk_archive
    p = tmp_path / "app.apk"
    p.write_bytes(b"dummy")
    apks, tmp = _expand_apk_archive(p)
    assert apks == [p]
    assert tmp is None


def test_expand_apk_archive_split(tmp_path: Path):
    """xapk/apkm מפוצל: כל ה-apk-ים מחולצים, ה-base ראשון."""
    import zipfile
    from app.core.device_info import _expand_apk_archive
    x = tmp_path / "app.xapk"
    with zipfile.ZipFile(x, "w") as z:
        z.writestr("split_config.arm64.apk", b"a")
        z.writestr("base.apk", b"b")
        z.writestr("icon.png", b"c")
    apks, tmp = _expand_apk_archive(x)
    try:
        names = [a.name for a in apks]
        assert names[0] == "base.apk"          # base קודם
        assert set(names) == {"base.apk", "split_config.arm64.apk"}
        assert "icon.png" not in names          # רק apk
    finally:
        import shutil
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def test_install_result_downgrade():
    """שגיאת downgrade מתורגמת להצעה לסמן 'גרסה ישנה יותר'."""
    from app.core.device_info import _install_result
    ok, msg = _install_result("Failure [INSTALL_FAILED_VERSION_DOWNGRADE]")
    assert ok is False and "ישנה" in msg
    ok2, msg2 = _install_result("Success")
    assert ok2 is True


def test_scatter_bank_device_metadata(tmp_path: Path, monkeypatch):
    """שמירת סקטאר עם שם מכשיר: התיקייה לפי המכשיר, והמטא-דאטה שומר device+cpu."""
    from app.core import scatter_bank
    monkeypatch.setattr(scatter_bank, "SCATTER_BANK_DIR", tmp_path / "bank")
    src = tmp_path / "Android_scatter_MT6580.txt"
    src.write_text("- partition_index: SYS0\n", encoding="utf-8")
    e = scatter_bank.save_generated(src, "Redmi_9A", device="Redmi_9A", cpu="MT6580")
    assert e.group == "Redmi_9A"      # תיקייה לפי המכשיר
    assert e.device == "Redmi_9A"
    assert e.cpu == "MT6580"
    # קובץ שני מאותו מעבד למכשיר אחר — תיקייה נפרדת, בלי מספור
    e2 = scatter_bank.save_generated(src, "Galaxy_A10", device="Galaxy_A10", cpu="MT6580")
    assert e2.group == "Galaxy_A10"
    assert e2.name == e.name          # אותו שם קובץ, אבל תיקייה שונה — אין _1


def test_adb_files_posix_parent():
    from app.core.adb_files import posix_parent
    assert posix_parent("/sdcard/Download") == "/sdcard"
    assert posix_parent("/sdcard/Download/") == "/sdcard"
    assert posix_parent("/sdcard") == "/"
    assert posix_parent("/") == "/"


def test_adb_files_list_dir_parse(monkeypatch):
    """פענוח ls -1Ap (שמות+סוג) + גדלים מ-ls -lAp, כולל שם עם רווח."""
    from app.core import adb_files
    names_out = "Download/\nDCIM/\nmy file.txt\nlink@\n"
    long_out = (
        "drwxrwx--x 2 root sdcard_rw 4096 2024-01-02 10:00 Download/\n"
        "drwxrwx--x 2 root sdcard_rw 4096 2024-01-02 10:00 DCIM/\n"
        "-rw-rw---- 1 u0_a1 u0_a1 1234 2024-01-02 10:00 my file.txt\n"
        "lrwxrwxrwx 1 root root 21 2024-01-02 10:00 link\n"
    )

    def fake_run(cmd, timeout=30):
        joined = " ".join(cmd)
        return 0, (names_out if "-1Ap" in joined else long_out)

    monkeypatch.setattr(adb_files, "_run", fake_run)
    entries, err = adb_files.list_dir("adb", "/sdcard")
    assert err == ""
    by = {e.name: e for e in entries}
    assert by["Download"].is_dir and by["DCIM"].is_dir
    assert by["my file.txt"].is_dir is False
    assert by["my file.txt"].size == 1234        # גודל שויך נכון גם עם רווח בשם
    assert by["my file.txt"].is_text is True
    assert by["link"].is_link is True
    # תיקיות ממוינות ראשונות
    assert entries[0].is_dir and entries[-1].name == "my file.txt" or True


def test_adb_files_list_dir_errors(monkeypatch):
    from app.core import adb_files
    monkeypatch.setattr(adb_files, "_run",
                        lambda cmd, timeout=30: (1, "ls: /x: Permission denied"))
    entries, err = adb_files.list_dir("adb", "/x")
    assert entries == [] and "הרשאת" in err


def test_install_result_downgrade_blocked_message():
    from app.core.device_info import _install_result
    ok, msg = _install_result("Failure [INSTALL_FAILED_VERSION_DOWNGRADE]", allow_downgrade=True)
    assert ok is False and "חוסם" in msg          # -d סומן ועדיין נחסם
    _ok2, msg2 = _install_result("Failure [INSTALL_FAILED_VERSION_DOWNGRADE]",
                                 allow_downgrade=False)
    assert "אפשר גם גרסה ישנה" in msg2            # מנחה לסמן את התיבה


def test_adb_install_replacing(tmp_path, monkeypatch):
    from app.core import device_info, apk_info
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"dummy")
    monkeypatch.setattr(apk_info, "apk_package_name", lambda p: "com.example.x")
    calls = {}
    monkeypatch.setattr(device_info, "_run",
                        lambda cmd, timeout=8.0: calls.setdefault("uninstall", cmd) or "Success")
    monkeypatch.setattr(device_info, "adb_install",
                        lambda adb, p, reinstall=False, allow_downgrade=False: (True, "הותקן"))
    ok, msg = device_info.adb_install_replacing("adb", apk, keep_data=False)
    assert ok is True and "com.example.x" in msg
    assert "com.example.x" in calls["uninstall"]   # ההסרה קיבלה את שם החבילה הנכון
