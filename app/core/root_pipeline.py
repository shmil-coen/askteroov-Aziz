# -*- coding: utf-8 -*-
"""
אורכיסטרציית הרוטינג האוטומטי — שני הארכיטקטורות מהמסמכים:
  "רוטינג אוטומטי במצב ברום.txt"      (ארכיטקטורה 1: BROM בלבד)
  "רוטינג אוטומטי דרך פאסטבוט.txt"    (ארכיטקטורה 2: Backend חלופי ל-Unlock/Write)

עקרון מכונן (כמו שאר האפליקציה): שום דבר לא רץ בלי אישור מפורש. כאן זה בא
לידי ביטוי בשלושה Job נפרדים לכל ארכיטקטורה, כל אחד עם חלון "אישור פעולה"
משלו (דרך אותו _plan/_request הקיימים ב-main_window):

  Job 1  (לא מסוכן): ניתוח מלא — GPT, זיהוי slot, שאיבת boot/init_boot+vbmeta+misc,
          פאץ' Magisk בצד ה-PC. שום דבר לא נכתב למכשיר.
  Job 1b (לא מסוכן): קריאת GPT טרייה + Preflight מול מה שנקרא ב-Job 1.
          התוצאה מוצגת למשתמש *לפני* שממשיכים לכתיבה.
  Job 2  (מסוכן):  הכתיבה בפועל (+ Unlock אופציונלי, Reboot, אימות אחרי כתיבה,
          תיעוד). ל-BROM (ארכיטקטורה 1) או Fastboot (ארכיטקטורה 2).

כל השלבים כאן בנויים מ-MtkCommand / FastbootCommand קיימים, פרט לשלבי עיבוד
מקומיים טהורים (פאץ' Magisk, פאץ' AVB, כתיבת תיעוד) שעטופים ב-PyStepCommand
כדי לשבת באותו Job/Step/JobManager הקיימים ולקבל בחינם: חלון אישור, פס
התקדמות, לוג, ניסיונות חוזרים, ועצירה בכשל ראשון.
"""
from __future__ import annotations

import shutil
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import avb, magisk_patch, root_audit
from .config import DUMPS_DIR
from .fastboot_bridge import FastbootCommands
from .gpt_parser import GptTable, parse_gpt_output
from .identity import DeviceIdentity, IdentityMismatch, parse_identity
from .jobs import Job, Step
from .logs import log
from .mtk_bridge import MtkCommands
from .preflight import PreflightReport, run_preflight
from .slot_detector import SlotDetectionError, detect_slot


# ---------------------------------------------------------------------- מצב הפייפליין


@dataclass
class PipelineState:
    # נבחר מראש ע"י המשתמש בדיאלוג הפתיחה
    magisk_apk: Path = None
    magiskboot_abi: str = "arm64-v8a"
    do_seccfg_unlock: bool = False
    keep_verity: bool = False
    keep_forceencrypt: bool = False
    legacy_sar: bool = False

    # נגלה ב-Job 1
    job_dir: Path = None
    gpt_before: Optional[GptTable] = None
    identity_before: Optional[DeviceIdentity] = None
    target_base: str = ""          # "boot" / "init_boot"
    slot: str = ""                 # "" / "a" / "b"
    target_partition: str = ""     # למשל "boot_a" או "boot"
    has_vbmeta: bool = False
    vbmeta_partition: str = ""
    backup_target: Optional[Path] = None
    backup_vbmeta: Optional[Path] = None
    backup_misc: Optional[Path] = None
    source_sha256: str = ""
    patched_image: Optional[Path] = None
    slot_detail: str = ""

    # נגלה ב-Job 1b
    gpt_now_1: Optional[GptTable] = None
    preflight_report: Optional[PreflightReport] = None

    # נגלה ב-Job 2
    vbmeta_patched_copy: Optional[Path] = None
    vbmeta_will_write: bool = False
    identity_after: Optional[DeviceIdentity] = None


class _OutputRouter:
    """מנתב שורות פלט ל-buffer הפעיל — מוחלף מתוך ה-after של כל שלב (רץ
    synchronously *לפני* שהשלב הבא מתחיל, לפי jobs.py) — כדי לפצל טקסט
    שנקלט מ-mtk/fastboot בין כמה שלבי פרסור בתוך אותו Job.
    """
    def __init__(self):
        self.buf: Optional[list[str]] = None

    def __call__(self, line: str):
        if self.buf is not None:
            self.buf.append(line)

    def switch_to(self, buf: Optional[list[str]]):
        self.buf = buf


# ---------------------------------------------------------------------- PyStepCommand


class PyStepCommand:
    """עוטף פונקציית Python טהורה (בלי subprocess מול מכשיר) לאותו ממשק
    שמצפה לו JobManager (describe/reset/stop/run_blocking) — כדי לשלב שלבי
    עיבוד מקומי (פאץ' Magisk/AVB, כתיבת תיעוד) בתוך Job רגיל."""

    def __init__(self, label: str, fn: Callable[[], None]):
        self.label = label
        self.fn = fn
        self.no_device = False
        self.needs_reconnect = False
        self.connect_timeout = None

    def describe(self) -> str:
        return self.label

    def reset(self):
        pass

    def stop(self):
        pass

    def run_blocking(self, on_output=None, on_progress=None) -> int:
        if on_progress:
            on_progress(0.0, self.label)
        try:
            self.fn()
        except Exception as e:      # noqa: BLE001 — כל כשל בשלב מקומי = כשל השלב
            if on_output:
                on_output(f"שגיאה ב{self.label}: {e}")
            log.error(f"{self.label}: {e}")
            raise
        if on_progress:
            on_progress(100.0, self.label)
        return 0


# ---------------------------------------------------------------------- Job 1: ניתוח


def build_job1_analyze(state: PipelineState) -> Job:
    gpt_buf: list[str] = []

    def before_gpt():
        gpt_buf.clear()

    def after_gpt():
        text = "\n".join(gpt_buf)
        table = parse_gpt_output(text)
        if not table.partitions:
            raise RuntimeError("לא נמצאו מחיצות בפלט GPT — ודא שהמכשיר במצב BROM/Preloader")
        state.gpt_before = table
        state.identity_before = parse_identity(text)
        names = {n.lower() for n in table.names()}
        state.target_base = "init_boot" if any(
            n in names for n in ("init_boot", "init_boot_a", "init_boot_b")) else "boot"
        state.has_vbmeta = avb.has_vbmeta_partition(table)

    misc_path = state.job_dir / "backups" / "original_misc.img"

    def after_misc():
        base = state.target_base
        has_a = state.gpt_before.get(f"{base}_a") is not None
        has_b = state.gpt_before.get(f"{base}_b") is not None
        if has_a and has_b:
            result = detect_slot(state.gpt_before, base, misc_image_path=misc_path)
            state.slot = result.slot
            state.slot_detail = (f"אסטרטגיות: {result.strategy} "
                                 f"({'מאומת בהצלבה' if result.confident else 'אסטרטגיה בודדת'})")
        else:
            state.slot = ""
            state.slot_detail = "מכשיר ללא A/B (slot יחיד)"
        state.target_partition = f"{base}_{state.slot}" if state.slot else base
        state.backup_misc = misc_path
        if state.has_vbmeta:
            vb_a = state.gpt_before.get("vbmeta_a") is not None
            vb_b = state.gpt_before.get("vbmeta_b") is not None
            if state.slot and vb_a and vb_b:
                state.vbmeta_partition = f"vbmeta_{state.slot}"
            else:
                state.vbmeta_partition = "vbmeta"

    def after_target_backup():
        from .checksums import file_sha256, write_checksum_file
        state.source_sha256 = file_sha256(state.backup_target)
        write_checksum_file(state.backup_target)

    def after_vbmeta_backup():
        from .checksums import write_checksum_file
        write_checksum_file(state.backup_vbmeta)

    def do_magisk_patch():
        work_dir = state.job_dir / "work_magisk"
        result = magisk_patch.patch_boot_image(
            src_image=state.backup_target, apk_path=state.magisk_apk,
            abi=state.magiskboot_abi, work_dir=work_dir,
            keep_verity=state.keep_verity, keep_forceencrypt=state.keep_forceencrypt,
            legacy_sar=state.legacy_sar)
        if not result.ok:
            raise RuntimeError(result.message)
        state.patched_image = result.output_image
        log.success(f"פאץ' Magisk: {result.message} → {result.output_image}")

    state.backup_target = state.job_dir / "backups" / f"original_{state.target_base}.img"
    state.backup_vbmeta = state.job_dir / "backups" / "original_vbmeta.img"

    steps = [
        Step("קריאת GPT", _CallbackThenCommand(before_gpt, MtkCommands.printgpt()), after_gpt),
        Step("שאיבת misc (לזיהוי slot)", MtkCommands.read_partition("misc", misc_path),
            after_misc),
    ]
    # שלבים הבאים תלויים ב-target_partition/vbmeta_partition שנקבעו ב-after_misc —
    # לכן נבנים כ"עצלים" (lambda) שמפנים ל-state בזמן הריצה, לא כאן.
    steps.append(_LazyStep("שאיבת boot/init_boot",
                           lambda: MtkCommands.read_partition(state.target_partition,
                                                              state.backup_target),
                           after_target_backup))
    if state.has_vbmeta:
        steps.append(_LazyStep("שאיבת vbmeta",
                               lambda: MtkCommands.read_partition(state.vbmeta_partition,
                                                                  state.backup_vbmeta),
                               after_vbmeta_backup))
    steps.append(Step("פאץ' Magisk (PC, ללא מגע במכשיר)",
                      PyStepCommand("פאץ' Magisk", do_magisk_patch)))

    job = Job("שלב 1: ניתוח מכשיר + פאץ' Magisk", steps, on_output=gpt_buf.append, retries=2,
             danger=False)
    job.notes = ["שלב זה קורא/שואב מהמכשיר בלבד — שום דבר לא נכתב אליו.",
                f"יעד: {state.job_dir}"]
    return job


class _LazyStep(Step):
    """Step שבו command נבנה רק ברגע ההרצה (תלוי בתוצאות שלב קודם)."""
    def __init__(self, name: str, command_factory: Callable[[], object], after=None):
        super().__init__(name, _LazyCommand(command_factory), after)


class _LazyCommand:
    """עוטף factory של פקודה — הפקודה האמיתית נבנית רק ב-run_blocking הראשון.
    connect_timeout מועבר הלאה לפקודה האמיתית (גם אם עדיין לא נוצרה) כדי
    ש-JobManager.retries/reconnect ימשיך לעבוד בדיוק כמו על פקודה רגילה."""
    def __init__(self, factory: Callable[[], object]):
        self._factory = factory
        self._real = None
        self.no_device = False
        self.needs_reconnect = False
        self._pending_connect_timeout = None

    def _ensure(self):
        if self._real is None:
            self._real = self._factory()
            if self._pending_connect_timeout is not None and hasattr(self._real, "connect_timeout"):
                self._real.connect_timeout = self._pending_connect_timeout
        return self._real

    @property
    def connect_timeout(self):
        return getattr(self._real, "connect_timeout", None) if self._real else self._pending_connect_timeout

    @connect_timeout.setter
    def connect_timeout(self, value):
        self._pending_connect_timeout = value
        if self._real is not None and hasattr(self._real, "connect_timeout"):
            self._real.connect_timeout = value

    def describe(self) -> str:
        try:
            return self._ensure().describe()
        except Exception:
            return "(פקודה תלוית-מצב)"

    def reset(self):
        self._real = None

    def stop(self):
        if self._real is not None:
            self._real.stop()

    def run_blocking(self, on_output=None, on_progress=None) -> int:
        cmd = self._ensure()
        rc = cmd.run_blocking(on_output, on_progress)
        self.no_device = getattr(cmd, "no_device", False)
        self.needs_reconnect = getattr(cmd, "needs_reconnect", False)
        return rc


# ---------------------------------------------------------------------- Job 1b: Preflight


def build_job1b_preflight(state: PipelineState) -> Job:
    gpt_buf: list[str] = []

    def before_gpt():
        gpt_buf.clear()

    def after_gpt():
        text = "\n".join(gpt_buf)
        table = parse_gpt_output(text)
        if not table.partitions:
            raise RuntimeError("לא נמצאו מחיצות בפלט GPT")
        identity_now = parse_identity(text)
        if not identity_now.matches(state.identity_before):
            raise IdentityMismatch(
                "טביעת האצבע של המכשיר לא תואמת למה שנקרא בשלב 1! "
                f"לפני: {state.identity_before.summary()} | עכשיו: {identity_now.summary()}. "
                "ייתכן שהתחבר מכשיר אחר — עוצרים.")
        state.gpt_now_1 = table
        vbmeta_status = ("קיימת מחיצת vbmeta עצמאית" if state.has_vbmeta
                         else "אין מחיצת vbmeta עצמאית")
        report = run_preflight(
            gpt_before=state.gpt_before, gpt_now=table,
            target_partition=state.target_partition,
            source_image=state.backup_target, patched_image=state.patched_image,
            expected_source_sha256=state.source_sha256, vbmeta_status=vbmeta_status,
            device=None)
        state.preflight_report = report
        if not report.all_critical_ok:
            raise RuntimeError("Preflight נכשל:\n" + report.as_text())

    job = Job("שלב 1ב: אימות מחדש + Preflight",
             [Step("קריאת GPT טרייה", _CallbackThenCommand(before_gpt, MtkCommands.printgpt()),
                  after_gpt)],
             on_output=gpt_buf.append, retries=2, danger=False)
    job.notes = ["קריאה בלבד — משווה למצב שנקרא בשלב 1, לפני שממשיכים לכתיבה."]
    return job


# ---------------------------------------------------------------------- Job 2 (ארכיטקטורה 1): כתיבה ב-BROM


def build_job2_brom(state: PipelineState) -> Job:
    steps: list[Step] = []

    def do_avb_patch():
        if not state.has_vbmeta:
            state.vbmeta_will_write = False
            return
        copy_path = state.job_dir / "work_avb" / "vbmeta_patched.img"
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(state.backup_vbmeta, copy_path)
        ok, msg = avb.patch_flags_disable_verification(copy_path)
        log.info(f"AVB: {msg}")
        if ok:
            state.vbmeta_patched_copy = copy_path
            state.vbmeta_will_write = True
        else:
            state.vbmeta_will_write = False   # נמנעים — לא כותבים vbmeta כלל הפעם

    steps.append(Step("בדיקת/פאץ' דגלי AVB (עותק מקומי)", PyStepCommand("פאץ' AVB", do_avb_patch)))

    if state.do_seccfg_unlock:
        steps.append(Step("Unlock (seccfg) — מוחק נתונים!", MtkCommands.seccfg("unlock")))

    steps.append(Step(f"צריבת {state.target_partition}",
                      _LazyCommand(lambda: MtkCommands.write_partition(
                          state.target_partition, state.patched_image))))

    steps.append(_LazyStep(
        "צריבת vbmeta (אם נדרש)",
        lambda: (MtkCommands.write_partition(state.vbmeta_partition, state.vbmeta_patched_copy)
                if state.vbmeta_will_write else _NoopCommand("vbmeta לא נצרב (לא נדרש/נמנע)"))))

    steps.append(Step("Reboot", MtkCommands.reset()))

    def verify_target():
        from .checksums import file_sha256
        verify_path = DUMPS_DIR / f"verify_{state.target_partition}.img"
        cmd = MtkCommands.read_partition(state.target_partition, verify_path)
        rc = cmd.run_blocking()
        if rc != 0:
            raise RuntimeError("קריאת אימות אחרי כתיבה נכשלה")
        expected = file_sha256(state.patched_image)
        actual = file_sha256(verify_path)
        if expected != actual:
            raise RuntimeError(f"אימות אחרי כתיבה נכשל! SHA256 לא תואם ({state.target_partition})")
        log.success(f"אומת: {state.target_partition} תואם בדיוק למה שנצרב (SHA256)")

    steps.append(Step("אימות אחרי כתיבה", PyStepCommand("אימות SHA256", verify_target)))

    def write_audit():
        root_audit.write_json(state.job_dir, "gpt_before.json",
                              [p.to_dict() for p in state.gpt_before.partitions])
        root_audit.write_json(state.job_dir, "hashes.json",
                              {"source_sha256": state.source_sha256})
        root_audit.write_operation_json(
            state.job_dir, architecture="brom", write_backend="brom",
            target_partition=state.target_partition, slot=state.slot or "(יחיד)",
            magisk_version=str(state.magisk_apk.name if state.magisk_apk else ""),
            vbmeta_patched=state.vbmeta_will_write, success=True)

    steps.append(Step("כתיבת תיעוד", PyStepCommand("תיעוד", write_audit)))

    job = Job(f"שלב 2: כתיבה סופית (BROM) — {state.target_partition}", steps,
             retries=2, danger=True)
    pf = state.preflight_report.as_text() if state.preflight_report else ""
    job.notes = ["⚠️ פעולה בלתי הפיכה — כתיבה למכשיר.", "", "Preflight:", pf]
    return job


class _NoopCommand:
    """פקודה ריקה (לא עושה כלום) — לשלבים מותנים שלא רלוונטיים הפעם."""
    def __init__(self, reason: str):
        self.reason = reason
        self.no_device = False
        self.needs_reconnect = False
        self.connect_timeout = None

    def describe(self) -> str:
        return f"(דילוג: {self.reason})"

    def reset(self):
        pass

    def stop(self):
        pass

    def run_blocking(self, on_output=None, on_progress=None) -> int:
        if on_output:
            on_output(self.reason)
        return 0


# ---------------------------------------------------------------------- Job 2 (ארכיטקטורה 2): כתיבה ב-Fastboot


_BOOTCTRL_CMD_OFFSET = 0
_BOOTCTRL_CMD_SIZE = 32


def _build_bcb_bytes(original_misc: bytes, command: str) -> bytes:
    """בונה עותק מפוצח של misc עם שדה command מוחלף בלבד — שאר הבתים
    (recovery/stage/וכו') נשמרים בדיוק כפי שהיו, לא מנחשים/מאפסים אותם."""
    buf = bytearray(original_misc)
    if len(buf) < 2048:
        buf.extend(b"\x00" * (2048 - len(buf)))
    field = command.encode("ascii") + b"\x00" * 32
    buf[_BOOTCTRL_CMD_OFFSET:_BOOTCTRL_CMD_OFFSET + _BOOTCTRL_CMD_SIZE] = field[:32]
    return bytes(buf)


def build_job2_fastboot(state: PipelineState) -> Job:
    router = _OutputRouter()
    userspace_buf: list[str] = []
    ability_buf: list[str] = []
    unlocked_buf: list[str] = []
    ident_buf: list[str] = []

    bcb_path = state.job_dir / "work_fastboot" / "misc_bootonce.img"

    def do_build_bcb():
        bcb_path.parent.mkdir(parents=True, exist_ok=True)
        original = state.backup_misc.read_bytes()
        bcb_path.write_bytes(_build_bcb_bytes(original, "bootonce-bootloader"))

    def after_userspace():
        text = "\n".join(userspace_buf).lower()
        if "yes" in text:
            raise RuntimeError("הגענו ל-fastbootd במקום לבוטלואדר האמיתי — עוצרים")
        router.switch_to(None)

    def after_ability():
        text = "\n".join(ability_buf)
        if "get_unlock_ability" in text.lower() and "1" not in text:
            raise RuntimeError("get_unlock_ability=0 — יש להפעיל Developer Options + "
                               "OEM Unlocking במכשיר עצמו לפני שממשיכים")
        router.switch_to(None)

    def after_unlocked():
        text = "\n".join(unlocked_buf).lower()
        if "yes" not in text and "true" not in text:
            raise RuntimeError("getvar unlocked לא מאשר שהבוטלואדר נפתח בפועל — עוצרים")
        router.switch_to(None)

    def after_reidentify():
        text = "\n".join(ident_buf)
        table = parse_gpt_output(text)
        if not table.partitions:
            raise RuntimeError("קריאת GPT אחרי האתחול נכשלה")
        ident_now = parse_identity(text)
        if not ident_now.matches(state.identity_before):
            raise IdentityMismatch("זהות המכשיר לא תואמת אחרי המעבר ל-Fastboot וחזרה — עוצרים")
        state.identity_after = ident_now
        router.switch_to(None)

    steps: list[Step] = [
        Step("בניית BCB (bootonce-bootloader)", PyStepCommand("בניית BCB", do_build_bcb)),
        Step("כתיבת misc (מעבר ל-Fastboot אמיתי)",
            _LazyCommand(lambda: MtkCommands.write_partition("misc", bcb_path))),
        Step("Reboot", MtkCommands.reset()),
    ]

    def before_userspace():
        userspace_buf.clear()
        router.switch_to(userspace_buf)
    steps.append(Step("בדיקת is-userspace (Fastboot אמיתי, לא fastbootd)",
                      _CallbackThenCommand(before_userspace, FastbootCommands.is_userspace()),
                      after_userspace))
    def before_ability():
        ability_buf.clear()
        router.switch_to(ability_buf)
    steps.append(Step("בדיקת get_unlock_ability",
                      _CallbackThenCommand(before_ability, FastbootCommands.get_unlock_ability()),
                      after_ability))

    unlock_cmd = FastbootCommands.flashing_unlock()
    unlock_cmd.DEVICE_TIMEOUT = 120.0
    steps.append(Step("Unlock — דורש אישור פיזי בכפתורי עוצמת קול על המכשיר!", unlock_cmd))

    def before_unlocked():
        unlocked_buf.clear()
        router.switch_to(unlocked_buf)
    steps.append(Step("אימות getvar unlocked",
                      _CallbackThenCommand(before_unlocked, FastbootCommands.getvar("unlocked")),
                      after_unlocked))

    steps.append(_LazyStep(f"flash {state.target_partition} (דגלי disable-verity)",
                           lambda: FastbootCommands.flash_disable_verity(
                               state.target_partition, state.patched_image)))
    if state.has_vbmeta:
        steps.append(_LazyStep("flash vbmeta מקורי (הדגלים מטופלים ע\"י fastboot עצמו)",
                               lambda: FastbootCommands.flash_disable_verity(
                                   state.vbmeta_partition, state.backup_vbmeta)))
    steps.append(Step("Reboot (fastboot)", FastbootCommands.reboot()))

    def before_reident():
        ident_buf.clear()
        router.switch_to(ident_buf)
    steps.append(Step("זיהוי מחדש דרך BROM (שער 1 עדיין תקין)",
                      _CallbackThenCommand(before_reident, MtkCommands.printgpt()),
                      after_reidentify))

    def verify_target():
        from .checksums import file_sha256
        verify_path = DUMPS_DIR / f"verify_{state.target_partition}.img"
        rc = MtkCommands.read_partition(state.target_partition, verify_path).run_blocking()
        if rc != 0:
            raise RuntimeError("קריאת אימות אחרי כתיבה נכשלה")
        if file_sha256(verify_path) != file_sha256(state.patched_image):
            raise RuntimeError(f"אימות אחרי כתיבה נכשל! SHA256 לא תואם ({state.target_partition})")
        log.success(f"אומת: {state.target_partition} תואם בדיוק למה שנצרב (SHA256)")

    steps.append(Step("אימות אחרי כתיבה: partition", PyStepCommand("אימות SHA256", verify_target)))

    if state.has_vbmeta:
        def verify_vbmeta():
            verify_path = DUMPS_DIR / "verify_vbmeta.img"
            rc = MtkCommands.read_partition(state.vbmeta_partition, verify_path).run_blocking()
            if rc != 0:
                raise RuntimeError("קריאת אימות vbmeta נכשלה")
            flags = avb.read_flags(verify_path)
            if flags & avb.KNOWN_MASK != avb.KNOWN_MASK:
                raise RuntimeError(f"vbmeta לא מציג דגלים מכובים כצפוי (0x{flags:08x})")
            log.success(f"אומת: vbmeta flags=0x{flags:08x} (hashtree+verification disabled)")

        steps.append(Step("אימות אחרי כתיבה: vbmeta", PyStepCommand("אימות vbmeta", verify_vbmeta)))

    def write_audit():
        root_audit.write_json(state.job_dir, "gpt_before.json",
                              [p.to_dict() for p in state.gpt_before.partitions])
        root_audit.write_json(state.job_dir, "hashes.json",
                              {"source_sha256": state.source_sha256})
        root_audit.write_operation_json(
            state.job_dir, architecture="fastboot_backend", write_backend="fastboot",
            target_partition=state.target_partition, slot=state.slot or "(יחיד)",
            magisk_version=str(state.magisk_apk.name if state.magisk_apk else ""),
            vbmeta_patched=state.has_vbmeta, success=True)

    steps.append(Step("כתיבת תיעוד", PyStepCommand("תיעוד", write_audit)))

    job = Job(f"שלב 2: כתיבה סופית (Fastboot) — {state.target_partition}", steps,
             on_output=router, retries=2, danger=True)
    pf = state.preflight_report.as_text() if state.preflight_report else ""
    job.notes = ["⚠️ פעולה בלתי הפיכה. דורשת אישור פיזי במכשיר (Unlock).", "", "Preflight:", pf]
    return job


class _CallbackThenCommand:
    """מריץ callback סינכרוני קטן (להחלפת buffer הניתוב) ואז מאציל לפקודה האמיתית."""
    def __init__(self, before: Callable[[], None], real):
        self.before = before
        self.real = real

    def describe(self) -> str:
        return self.real.describe()

    def reset(self):
        self.real.reset()

    def stop(self):
        self.real.stop()

    @property
    def no_device(self):
        return getattr(self.real, "no_device", False)

    @property
    def needs_reconnect(self):
        return getattr(self.real, "needs_reconnect", False)

    @property
    def connect_timeout(self):
        return getattr(self.real, "connect_timeout", None)

    @connect_timeout.setter
    def connect_timeout(self, value):
        if hasattr(self.real, "connect_timeout"):
            self.real.connect_timeout = value

    def run_blocking(self, on_output=None, on_progress=None) -> int:
        self.before()
        return self.real.run_blocking(on_output, on_progress)
