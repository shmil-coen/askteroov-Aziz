# -*- coding: utf-8 -*-
"""
פאץ' Magisk בצד ה-PC — עוטף את tools/Magisk/magiskboot.exe (Windows, MinGW/UCRT,
מקור: github.com/svoboda18/magiskboot). לא נוגע במכשיר בכלל: קלט/פלט הם קבצים
בלבד (boot/init_boot שנשאב + APK של Magisk שנבחר).

הרצף כאן הוא פורט נאמן ל-Python של assets/boot_patch.sh — נשלף ונקרא *ישירות
מתוך* Magisk-v30.7.apk הארוז אצלנו (tools/Magisk), ולא משוחזר מהזיכרון, כדי
להבטיח דיוק:
  1. unpack (magiskboot unpack) → kernel/ramdisk.cpio/dtb/…
  2. בדיקת מצב ה-ramdisk הקיים (cpio test): 0=stock, 1=כבר Magisk, 2=רוט אחר (עצירה)
  3. דחיסת magisk / stub.apk / init-ld ל-xz
  4. כתיבת config (KEEPVERITY/KEEPFORCEENCRYPT/RECOVERYMODE/VENDORBOOT/…)
  5. הזרקה ל-ramdisk דרך cpio: add magiskinit כ-init, יצירת overlay.d/sbin,
     הוספת magisk.xz/stub.xz/init-ld.xz, "patch" (הסרת dm-verity/forceencrypt
     מה-fstab המוטמע לפי KEEPVERITY/KEEPFORCEENCRYPT), גיבוי ה-ramdisk המקורי
  6. פאץ' dtb/kernel_dtb/extra (fstab מוטמע ב-device tree, אם קיים)
  7. hexpatch-ים בקרנל (Samsung RKP/defex/PROCA — לא-פעילים/no-op אם לא רלוונטי
     לשבב; LEGACYSAR חייב להיות מסומן מפורשות — לא מנחשים)
  8. repack (magiskboot repack) → new-boot.img

הבינריים (magiskinit / magisk / init-ld) נשלפים מתוך אותו APK, מ-lib/<abi>/
lib*.so (כך הם ארוזים כדי לעבור את חוקי החתימה של APK — זה עצמם הבינריים,
לא ספריות שיתוף אמיתיות).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import PROJECT_ROOT
from .logs import log

MAGISKBOOT_EXE = PROJECT_ROOT / "tools" / "Magisk" / "magiskboot.exe"

# lib/<abi>/lib<logical>.so בתוך ה-APK
_LIB_NAMES = {
    "magiskinit": "libmagiskinit.so",
    "magisk": "libmagisk.so",
    "init-ld": "libinit-ld.so",
}
_KNOWN_ABIS = ("arm64-v8a", "armeabi-v7a", "x86_64", "x86")

# ---------------------------------------------------------------------- זיהוי ABI (ללא ADB)
#
# ל-boot_patch צריך לדעת אם המכשיר 64/32-bit כדי לבחור את lib/<abi>/ הנכון
# מתוך ה-APK. בלי ADB (מצב BROM טהור) אין דרך לקרוא ro.product.cpu.abi בפועל —
# לכן זו הצעה בלבד לפי שם המעבד, לא קביעה. לפי עקרון "אי-ודאות => עצירה":
# ה-UI *חייב* להציג את הבחירה למשתמש ולתת לו לאשר/לשנות, לא להשתמש בה בשקט.

# שבבי MediaTek ידועים כ-32-bit בלבד (Cortex-A7, דור ישן) — Android 8.1 נפוץ עליהם
_KNOWN_32BIT_ONLY_CHIPS = {
    "MT6580", "MT6570", "MT6572", "MT6571", "MT6261", "MT6260", "MT6582", "MT6592",
}


@dataclass
class AbiGuess:
    abi64: Optional[str]     # "arm64-v8a" או None אם 32-bit בלבד
    abi32: str               # "armeabi-v7a"
    is64bit_guess: bool
    confident: bool          # True רק אם השבב מוכר לנו ברשימה כלשהי
    reason: str


def guess_abi(cpu_name: str) -> AbiGuess:
    cpu = (cpu_name or "").upper().strip()
    if cpu in _KNOWN_32BIT_ONLY_CHIPS:
        return AbiGuess(abi64=None, abi32="armeabi-v7a", is64bit_guess=False,
                        confident=True, reason=f"{cpu} ידוע כשבב 32-bit בלבד")
    if cpu:
        return AbiGuess(abi64="arm64-v8a", abi32="armeabi-v7a", is64bit_guess=True,
                        confident=False,
                        reason=f"{cpu} לא ברשימת השבבים הישנים הידועים — "
                               "הנחה: 64-bit (רוב המכשירים מ-2016+), אך יש לאשר ידנית")
    return AbiGuess(abi64="arm64-v8a", abi32="armeabi-v7a", is64bit_guess=True,
                    confident=False, reason="לא זוהה שם מעבד — ברירת מחדל 64-bit, נדרש אישור")


# ---------------------------------------------------------------------- הרצת magiskboot


def _run(args: list[str], cwd: Path, timeout: float = 180.0) -> tuple[int, str]:
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        p = subprocess.run([str(MAGISKBOOT_EXE)] + args, cwd=str(cwd),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=flags)
        return p.returncode, (p.stdout or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


def extract_from_apk(apk_path: Path, abi: str, work_dir: Path) -> dict[str, Path]:
    """שולף magiskinit/magisk/init-ld מ-lib/<abi>/ בתוך ה-APK אל תוך work_dir."""
    if abi not in _KNOWN_ABIS:
        raise ValueError(f"ABI לא נתמך: {abi}")
    lib_dir = f"lib/{abi}/"
    out: dict[str, Path] = {}
    with zipfile.ZipFile(apk_path) as z:
        names = set(z.namelist())
        for logical, soname in _LIB_NAMES.items():
            entry = lib_dir + soname
            if entry not in names:
                continue
            dest = work_dir / logical
            with z.open(entry) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            out[logical] = dest
    missing = [k for k in ("magiskinit", "magisk", "init-ld") if k not in out]
    if missing:
        raise RuntimeError(f"חסרים בינריים ל-abi={abi} בתוך ה-APK שנבחר: {missing}")
    return out


def extract_stub_apk(apk_path: Path, work_dir: Path) -> Path:
    dest = work_dir / "stub.apk"
    with zipfile.ZipFile(apk_path) as z:
        with z.open("assets/stub.apk") as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return dest


# ---------------------------------------------------------------------- תוצאה


@dataclass
class PatchResult:
    ok: bool
    message: str
    output_image: Optional[Path] = None
    sha1_orig: str = ""
    log_lines: list[str] = field(default_factory=list)


def _log(result_lines: list[str], line: str):
    result_lines.append(line)
    log.info(line)


# ---------------------------------------------------------------------- הפאץ' המלא


def patch_boot_image(src_image: Path, apk_path: Path, abi: str, work_dir: Path,
                     keep_verity: bool = False, keep_forceencrypt: bool = False,
                     legacy_sar: bool = False) -> PatchResult:
    lines: list[str] = []
    if not MAGISKBOOT_EXE.is_file():
        return PatchResult(False, f"magiskboot.exe לא נמצא ב-{MAGISKBOOT_EXE}")
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    boot_local = work_dir / src_image.name
    shutil.copy2(src_image, boot_local)

    try:
        bins = extract_from_apk(apk_path, abi, work_dir)
        stub = extract_stub_apk(apk_path, work_dir)
    except Exception as e:      # noqa: BLE001
        return PatchResult(False, f"שליפת בינריים מה-APK נכשלה: {e}")

    # 1) unpack — קודי חזרה של magiskboot: 0=רגיל, 2=ChromeOS, 3=vendor_boot, אחר=כשל
    rc, out = _run(["unpack", str(boot_local)], work_dir)
    _log(lines, out.strip() or f"(unpack הסתיים בקוד {rc})")
    if rc == 2:
        _log(lines, "זוהה boot image מסוג ChromeOS — לא נתמך בטווח היעד של הכלי")
        return PatchResult(False, "boot image מסוג ChromeOS — לא רלוונטי למכשירי MediaTek", log_lines=lines)
    if rc == 3:
        return PatchResult(False,
            "magiskboot זיהה את הקובץ כ-vendor_boot — יעד שגוי (צריך boot/init_boot)",
            log_lines=lines)
    if rc != 0:
        return PatchResult(False, f"unpack נכשל (קוד {rc})", log_lines=lines)

    # 2) איתור ה-ramdisk (init_boot מודרני / boot רגיל)
    ramdisk_candidates = ["ramdisk.cpio", "vendor_ramdisk/init_boot.cpio",
                          "vendor_ramdisk/ramdisk.cpio"]
    ramdisk = None
    for cand in ramdisk_candidates:
        p = work_dir / cand
        if p.is_file():
            ramdisk = p
            break

    skip_backup = False
    if ramdisk is not None:
        rc_test, _ = _run(["cpio", str(ramdisk), "test"], work_dir)
    else:
        ramdisk = work_dir / "ramdisk.cpio"
        ramdisk.write_bytes(b"")
        rc_test = 0
        skip_backup = True
        _log(lines, "לא נמצא ramdisk ב-boot image (תקין ל-GKI/SAR מודרני) — נוצר ריק")

    sha1_orig = ""
    if rc_test == 2:
        return PatchResult(False,
            "זוהה פאץ' רוט אחר (לא Magisk) על גבי ה-boot/init_boot — לא ממשיכים "
            "אוטומטית. יש לשחזר תמונה מקורית לפני רוטינג עם Magisk.", log_lines=lines)
    if rc_test == 1:
        _log(lines, "זוהה boot image שכבר מכיל Magisk — מבצע re-patch")
        _run(["cpio", str(ramdisk), "extract .backup/.magisk config.orig", "restore"], work_dir)
        cfg_orig = work_dir / "config.orig"
        if cfg_orig.is_file():
            for ln in cfg_orig.read_text(encoding="utf-8", errors="replace").splitlines():
                if ln.startswith("SHA1="):
                    sha1_orig = ln.split("=", 1)[1].strip()
    else:
        rc_sha, out_sha = _run(["sha1", str(boot_local)], work_dir)
        sha1_orig = out_sha.strip() if rc_sha == 0 else ""

    # 3) דחיסת magisk / stub.apk / init-ld ל-xz (כמו boot_patch.sh)
    for logical, fname in (("magisk", "magisk"), ("stub", "stub.apk"), ("init-ld", "init-ld")):
        src = bins[fname] if fname in bins else (stub if logical == "stub" else None)
        if src is None:
            continue
        rc_c, out_c = _run(["compress=xz", str(src), str(work_dir / f"{logical}.xz")], work_dir)
        if rc_c != 0:
            return PatchResult(False, f"דחיסת {logical} נכשלה: {out_c}", log_lines=lines)

    # 4) config
    cfg_lines = [f"KEEPVERITY={'true' if keep_verity else 'false'}",
                f"KEEPFORCEENCRYPT={'true' if keep_forceencrypt else 'false'}",
                "RECOVERYMODE=false", "VENDORBOOT=false"]
    if sha1_orig:
        cfg_lines.append(f"SHA1={sha1_orig}")
    (work_dir / "config").write_text("\n".join(cfg_lines) + "\n", encoding="utf-8")

    # 5) הזרקה ל-ramdisk — רצף זהה ל-assets/boot_patch.sh (נקרא ישירות מה-APK)
    cpio_cmds = [
        f"add 0750 init {bins['magiskinit']}",
        "mkdir 0750 overlay.d",
        "mkdir 0750 overlay.d/sbin",
        f"add 0644 overlay.d/sbin/magisk.xz {work_dir / 'magisk.xz'}",
        f"add 0644 overlay.d/sbin/stub.xz {work_dir / 'stub.xz'}",
        f"add 0644 overlay.d/sbin/init-ld.xz {work_dir / 'init-ld.xz'}",
        "patch",
    ]
    if not skip_backup:
        cpio_cmds.append(f"backup {work_dir / 'ramdisk.cpio.orig'}")
    cpio_cmds += ["mkdir 000 .backup", f"add 000 .backup/.magisk {work_dir / 'config'}"]

    rc, out = _run(["cpio", str(ramdisk), *cpio_cmds], work_dir)
    _log(lines, out.strip() or f"(cpio patch הסתיים בקוד {rc})")
    if rc != 0:
        return PatchResult(False, "פאץ' ה-ramdisk נכשל", log_lines=lines)

    # 6) dtb / kernel_dtb / extra — פאץ' fstab מוטמע (אם קיים)
    for dt in ("dtb", "kernel_dtb", "extra"):
        dtp = work_dir / dt
        if not dtp.is_file():
            continue
        rc_t, _ = _run(["dtb", str(dtp), "test"], work_dir)
        if rc_t != 0:
            return PatchResult(False,
                f"{dt}: זוהה פאץ' של גרסת Magisk ישנה לא-נתמכת — יש להשתמש בתמונה מקורית",
                log_lines=lines)
        _run(["dtb", str(dtp), "patch"], work_dir)

    # 7) hexpatch-ים בקרנל (no-op אם התבנית לא נמצאת — בטוח להריץ תמיד)
    kernel = work_dir / "kernel"
    if kernel.is_file():
        _run(["hexpatch", str(kernel),
             "49010054011440B93FA00F71E9000054010840B93FA00F7189000054001840B91FA00F7188010054",
             "A1020054011440B93FA00F7140020054010840B93FA00F71E0010054001840B91FA00F7181010054"], work_dir)
        _run(["hexpatch", str(kernel), "821B8012", "E2FF8F12"], work_dir)
        _run(["hexpatch", str(kernel),
             "70726F63615F636F6E66696700", "70726F63615F6D616769736B00"], work_dir)
        if legacy_sar:
            _run(["hexpatch", str(kernel),
                 "736B69705F696E697472616D667300", "77616E745F696E697472616D667300"], work_dir)

    # 8) repack
    rc, out = _run(["repack", str(boot_local)], work_dir)
    _log(lines, out.strip() or f"(repack הסתיים בקוד {rc})")
    if rc != 0:
        return PatchResult(False, "repack נכשל", log_lines=lines)

    out_img = work_dir / "new-boot.img"
    if not out_img.is_file() or out_img.stat().st_size == 0:
        return PatchResult(False, "repack לא הפיק new-boot.img", log_lines=lines)

    return PatchResult(True, "פאץ' Magisk הושלם בהצלחה", output_image=out_img,
                       sha1_orig=sha1_orig, log_lines=lines)
