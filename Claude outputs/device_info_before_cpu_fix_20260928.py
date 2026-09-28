# -*- coding: utf-8 -*-
"""
קריאת פרטי מכשיר חיים (דגם / מעבד / אחוז סוללה) — לפי מצב החיבור.

מגבלה מהותית: אחוז סוללה ושם דגם זמינים רק כשהטלפון דלוק (ADB) או חלקית
ב-Fastboot. במצב BROM/Preloader (mtkclient) אין ערוץ לקרוא אותם — שם מציגים
רק את המעבד (שזוהה מ-printgpt/gettargetconfig).
"""
from __future__ import annotations

import os
import re
import subprocess
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import find_adb_exe, find_fastboot_exe


@dataclass
class DeviceInfo:
    mode: str = "none"          # none / brom / adb / fastboot
    model: str = ""             # שם דגם (ADB/fastboot) — ריק אם לא ידוע
    cpu: str = ""               # MT6580 וכו'
    battery: Optional[int] = None   # אחוז 0-100, או None אם לא ידוע
    voltage_mv: Optional[int] = None    # מתח סוללה במיליוולט (Fastboot)
    soc_ok: Optional[bool] = None       # האם רמת הטעינה מספיקה (battery-soc-ok)
    unlocked: Optional[bool] = None     # מצב בוטלאודר (Fastboot: getvar unlocked)
    extra: str = ""             # טקסט נוסף (למשל מתח סוללה ב-fastboot)

    LOW_MV = 3600       # מתחת לזה — מומלץ לא לצרוב
    CRIT_MV = 3400      # מתחת לזה — סוללה חלשה מאוד

    def battery_too_low(self) -> bool:
        """האם הסוללה נמוכה מדי לצריבה בטוחה."""
        if self.soc_ok is False:
            return True
        if self.voltage_mv is not None and self.voltage_mv < self.LOW_MV:
            return True
        if self.battery is not None and self.battery < 15:
            return True
        return False

    def battery_note(self) -> str:
        if self.soc_ok is False:
            return "המכשיר מדווח שרמת הטעינה אינה מספיקה (battery-soc-ok: no)."
        bits = []
        if self.voltage_mv is not None:
            bits.append(f"מתח {self.voltage_mv}mV")
        if self.battery is not None:
            bits.append(f"{self.battery}%")
        return "סוללה נמוכה" + (f" ({', '.join(bits)})" if bits else "")

    @property
    def mode_label(self) -> str:
        return {"brom": "BROM/Preloader", "adb": "ADB",
                "fastboot": "Fastboot", "none": "אין מכשיר"}.get(self.mode, self.mode)


def _run(cmd: list[str], timeout: float = 8.0) -> str:
    """מריץ פקודה קצרה ומחזיר stdout+stderr; מחרוזת ריקה בכשל."""
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=flags)
        return p.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ---------------------------------------------------------------------- ADB

def adb_devices_connected(adb: str) -> bool:
    out = _run([adb, "devices"], timeout=8)
    for line in out.splitlines()[1:]:
        line = line.strip()
        if line and "\t" in line and line.split("\t")[1].strip() == "device":
            return True
    return False


def read_adb_info(adb: str) -> Optional[DeviceInfo]:
    if not adb_devices_connected(adb):
        return None
    info = DeviceInfo(mode="adb")
    model = _run([adb, "shell", "getprop", "ro.product.model"], timeout=6).strip()
    brand = _run([adb, "shell", "getprop", "ro.product.brand"], timeout=6).strip()
    info.model = (f"{brand} {model}".strip() if brand and brand.lower() not in model.lower()
                  else model)
    cpu = _run([adb, "shell", "getprop", "ro.board.platform"], timeout=6).strip()
    if not cpu or cpu in ("0", "unknown"):
        cpu = _run([adb, "shell", "getprop", "ro.hardware"], timeout=6).strip()
    info.cpu = _norm_cpu(cpu)
    info.battery = _parse_battery_level(_run([adb, "shell", "dumpsys", "battery"], timeout=6))
    if not info.cpu:
        # גיבוי: serialno של MediaTek מקודד את קוד השבב (למשל 0x6580 → MT6580)
        serial = _run([adb, "shell", "getprop", "ro.serialno"], timeout=6).strip()
        m = re.match(r"0x([0-9a-fA-F]{4})", serial)
        if m:
            info.cpu = f"MT{m.group(1).upper()}"
    return info


_LEVEL_RE = re.compile(r"^\s*level\s*:\s*(\d+)", re.IGNORECASE | re.MULTILINE)
_SCALE_RE = re.compile(r"^\s*scale\s*:\s*(\d+)", re.IGNORECASE | re.MULTILINE)


def _parse_battery_level(text: str) -> Optional[int]:
    m = _LEVEL_RE.search(text)
    if not m:
        return None
    level = int(m.group(1))
    ms = _SCALE_RE.search(text)
    scale = int(ms.group(1)) if ms else 100
    if scale and scale != 100:
        level = round(level / scale * 100)
    return max(0, min(100, level))


def _norm_cpu(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    m = re.search(r"(mt\d{4})", raw, re.IGNORECASE)
    return m.group(1).upper() if m else raw


# ---------------------------------------------------------------------- ADB מידע מורחב

# מאפייני מערכת שנקראים לתצוגת מידע בלשונית ADB (קריאה בלבד)
ADB_PROPS = {
    "ro.product.brand": "מותג",
    "ro.product.model": "דגם",
    "ro.product.device": "קוד מכשיר",
    "ro.product.manufacturer": "יצרן",
    "ro.board.platform": "מעבד (platform)",
    "ro.hardware": "חומרה",
    "ro.build.version.release": "גרסת אנדרואיד",
    "ro.build.version.sdk": "רמת API",
    "ro.build.display.id": "גרסת Build",
    "ro.serialno": "מספר סידורי",
}

_VERIFIED_BOOT_LABELS = {
    "0": "ירוק — נעול (קושחה רשמית)",
    "1": "צהוב — קושחה חתומה שונה",
    "2": "כתום — בוטלאודר פתוח",
    "3": "אדום — נעול אך פגום",
}


def collect_adb_details(adb: str) -> dict:
    """אוסף מידע מורחב מהמכשיר ב-ADB (קריאה בלבד): דגם, מעבד, אנדרואיד, סוללה."""
    out: dict[str, str] = {}
    for prop, label in ADB_PROPS.items():
        val = _run([adb, "shell", "getprop", prop], timeout=6).strip()
        if val:
            out[label] = val
    vbs = _run([adb, "shell", "getprop", "ro.boot.verifiedbootstate"], timeout=6).strip()
    if vbs:
        _vb_names = {"green": "0", "yellow": "1", "orange": "2", "red": "3"}
        out["מצב Verified Boot"] = _VERIFIED_BOOT_LABELS.get(_vb_names.get(vbs.lower(), vbs), vbs)
    level = _parse_battery_level(_run([adb, "shell", "dumpsys", "battery"], timeout=6))
    if level is not None:
        out["סוללה"] = f"{level}%"
    return out


# ---------------------------------------------------------------------- ניהול אפליקציות ב-ADB


def adb_list_packages(adb: str, include_system: bool = False) -> list[dict]:
    """רשימת חבילות מותקנות (שם + האם מערכת) — קריאה בלבד."""
    arg = "-s" if include_system else "-3"
    out = _run([adb, "shell", "pm", "list", "packages", arg], timeout=15)
    pkgs = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            name = line.split(":", 1)[1].strip()
            if name:
                pkgs.append({"package": name, "system": include_system})
    return sorted(pkgs, key=lambda p: p["package"].lower())


def adb_uninstall(adb: str, package: str, keep_data: bool = False) -> tuple[bool, str]:
    """הסרת אפליקציה לפי שם חבילה. keep_data=True → -k (שמירת נתונים ומטמון)."""
    args = [adb, "shell", "pm", "uninstall"]
    if keep_data:
        args.append("-k")
    args.append(package)
    # ניסיון חוזר כשהתשובה ריקה: המכשיר עשוי להיות עסוק לרגע (למשל בדיקת mtk במקביל)
    out = ""
    for attempt in range(3):
        out = _run(args, timeout=30)
        if out.strip():
            break
        time.sleep(1.2)
    low = (out or "").lower()
    if "success" in low:
        return True, "הוסר בהצלחה"
    if not out.strip():
        return False, "אין תשובה מהמכשיר — בדוק חיבור ADB (נסה שוב; ודא שאין פעולת mtk פעילה)"
    # אפליקציית מערכת: אי אפשר למחוק לגמרי בלי root (DELETE_FAILED_INTERNAL_ERROR).
    # השיטה המקובלת: הסרה למשתמש הנוכחי (--user 0) — נעלמת ולא רצה, ניתנת לשחזור.
    if "delete_failed" in low or "failure" in low:
        args2 = [adb, "shell", "pm", "uninstall"] + (["-k"] if keep_data else []) \
            + ["--user", "0", package]
        out2 = _run(args2, timeout=30)
        if "success" in (out2 or "").lower():
            return True, ("הוסרה למשתמש (אפליקציית מערכת). לשחזור: "
                          f"adb shell cmd package install-existing {package}")
        return False, f"{out.strip()} | ניסיון הסרה למשתמש: {(out2 or '').strip()}"
    return False, out.strip()


def adb_restore(adb: str, package: str) -> tuple[bool, str]:
    """שחזור אפליקציה שהוסרה מהמשתמש (cmd package install-existing)."""
    out = _run([adb, "shell", "cmd", "package", "install-existing", package], timeout=30)
    low = (out or "").lower()
    if "installed" in low and "fail" not in low:
        return True, "שוחזרה בהצלחה"
    return False, (out or "אין תשובה מהמכשיר").strip()


def _expand_apk_archive(path: "Path") -> tuple[list["Path"], "Optional[Path]"]:
    """מחזיר (רשימת קובצי apk להתקנה, תיקייה זמנית לניקוי או None).

    apk בודד -> [path]. חבילה מפוצלת (xapk/apkm/apks) -> חילוץ כל ה-apk-ים מתוכה.
    ה-base מוחזר ראשון כדי ש-install-multiple יעבוד כראוי.
    """
    p = Path(path)
    suf = p.suffix.lower()
    if suf == ".apk":
        return [p], None
    try:
        tmp = Path(tempfile.mkdtemp(prefix="askt_apk_"))
        apks: list[Path] = []
        with zipfile.ZipFile(p) as z:
            for name in z.namelist():
                if name.lower().endswith(".apk") and not name.endswith("/"):
                    dest = tmp / Path(name).name
                    with z.open(name) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out)
                    apks.append(dest)
        apks.sort(key=lambda x: (0 if "base" in x.name.lower() else 1, x.name.lower()))
        return apks, tmp
    except (OSError, zipfile.BadZipFile):
        return [], None


_INSTALL_ERRORS = {
    "install_failed_already_exists": "האפליקציה כבר קיימת — סמן 'עדכן אם קיימת' ונסה שוב",
    "install_failed_insufficient_storage": "אין מספיק שטח אחסון במכשיר",
    "install_failed_invalid_apk": "קובץ APK פגום או לא תקין",
    "install_failed_version_downgrade": "הגרסה ישנה מהמותקנת — סמן 'אפשר גם גרסה ישנה יותר' ונסה שוב",
    "install_failed_update_incompatible": "העדכון לא תואם לקיימת (חתימה שונה) — סמן 'עדכן אם קיימת'; אם עדיין נכשל צריך להסיר קודם",
    "install_parse_failed": "לא ניתן לפענח את החבילה — ודא שזה קובץ apk/xapk/apkm תקין",
    "install_failed_no_matching_abis": "החבילה לא תואמת למעבד המכשיר",
}


def _install_result(out: str, allow_downgrade: bool = False) -> tuple[bool, str]:
    low = (out or "").lower()
    if "success" in low:
        return True, "הותקן בהצלחה"
    if "install_failed_version_downgrade" in low and allow_downgrade:
        # -d כבר סומן ועדיין נחסם — אנדרואיד חוסם שדרוג-לאחור לאפליקציות release
        return False, ("אנדרואיד חוסם התקנת גרסה ישנה גם עם \u200e-d. "
                       "כדי בכל זאת — צריך להסיר את המותקנת ואז להתקין.")
    for key, msg in _INSTALL_ERRORS.items():
        if key in low:
            return False, msg
    if not (out or "").strip():
        return False, "אין תשובה מהמכשיר — בדוק חיבור ADB ואישור במסך המכשיר"
    return False, out.strip()


def adb_install(adb: str, apk_path: "Path", reinstall: bool = False,
                allow_downgrade: bool = False) -> tuple[bool, str]:
    """התקנת חבילה מהמחשב: apk בודד או חבילה מפוצלת (xapk/apkm/apks).

    reinstall=True -> -r (עדכון קיימת). allow_downgrade=True -> -d (גם גרסה ישנה).
    חבילה מפוצלת מותקנת עם install-multiple.
    """
    p = Path(apk_path)
    if not p.is_file():
        return False, f"הקובץ לא נמצא: {p}"
    apks, tmp = _expand_apk_archive(p)
    try:
        if not apks:
            return False, "לא נמצאו קובצי APK בתוך החבילה (xapk/apkm/apks פגום?)"
        flags = (["-r"] if reinstall else []) + (["-d"] if allow_downgrade else [])
        if len(apks) == 1:
            args = [adb, "install"] + flags + [str(apks[0])]
        else:
            args = [adb, "install-multiple"] + flags + [str(a) for a in apks]
        out = _run(args, timeout=600)
        return _install_result(out, allow_downgrade)
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)



def adb_install_replacing(adb: str, apk_path: "Path", keep_data: bool = False) -> tuple[bool, str]:
    """מסיר את הגרסה המותקנת ואז מתקין — לעקיפת חסימת שדרוג-לאחור של אנדרואיד.

    keep_data=True → הסרה עם שמירת נתונים (-k). מזהה את שם החבילה מתוך ה-APK.
    """
    from .apk_info import apk_package_name
    apks, tmp = _expand_apk_archive(Path(apk_path))
    try:
        if not apks:
            return False, "לא נמצאו קובצי APK בחבילה"
        pkg = apk_package_name(apks[0])
        if not pkg:
            return False, "לא זוהה שם החבילה מה-APK — לא ניתן להסיר אוטומטית"
        un_args = [adb, "shell", "pm", "uninstall"] + (["-k"] if keep_data else []) + [pkg]
        un = _run(un_args, timeout=60)
        ok, msg = adb_install(adb, apk_path, reinstall=True, allow_downgrade=True)
        if ok:
            return True, f"הוסרה הגרסה הקודמת ({pkg}) והותקנה הגרסה החדשה"
        return False, f"הסרה: {(un or '').strip() or 'בוצעה'} | התקנה נכשלה: {msg}"
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------- הרשאות ניהול מלאות (device owner)

def adb_find_admin_receiver(adb: str, package: str) -> "Optional[str]":
    """מאתר את רכיב מנהל-ההתקן (receiver עם BIND_DEVICE_ADMIN) של אפליקציה.

    שיטה 1 (אמינה): קריאת AndroidManifest של ה-APK המותקן.
    שיטה 2 (גיבוי): פענוח dumpsys. מחזיר 'package/component' או None.
    """
    try:
        from .apk_info import admin_receiver_on_device
        comp = admin_receiver_on_device(adb, package)
        if comp:
            return comp
    except Exception:      # noqa: BLE001
        pass
    out = _run([adb, "shell", "dumpsys", "package", package], timeout=15)
    receiver = None
    for line in out.splitlines():
        line = line.strip()
        # שורות receiver נראות כך: <pkg>/<component> ... permission=android.permission.BIND_DEVICE_ADMIN
        if package in line and "/" in line:
            m = re.search(rf"{re.escape(package)}/[\w.$]+", line)
            if m:
                cand = m.group(0)
                if "admin" in line.lower() or "device" in line.lower():
                    return cand
                if receiver is None:
                    receiver = cand
    return receiver


def adb_set_device_owner(adb: str, component: str) -> tuple[bool, str]:
    """הענקת בעלות מלאה על המכשיר (device owner) לרכיב pkg/receiver.

    דרישות: אין חשבונות משתמש/גוגל מוגדרים במכשיר, והאפליקציה מותקנת.
    """
    out = _run([adb, "shell", "dpm", "set-device-owner", component], timeout=40)
    low = (out or "").lower()
    if "success" in low:
        return True, "הוענקו הרשאות בעלים למכשיר (device owner) בהצלחה"
    if not (out or "").strip():
        return False, "אין תשובה מהמכשיר — בדוק חיבור ADB"
    if "already" in low and "owner" in low:
        return False, "כבר מוגדר בעלים למכשיר — הסר אותו קודם"
    if "account" in low:
        return False, ("נכשל: קיימים חשבונות במכשיר. יש להסיר את כל החשבונות "
                       "(כולל חשבון Google) בהגדרות לפני הענקת בעלות.")
    return False, out.strip()


def adb_set_active_admin(adb: str, component: str) -> tuple[bool, str]:
    """הפעלת רכיב כמנהל-התקן פעיל (device admin) — פחות חזק מ-device owner."""
    out = _run([adb, "shell", "dpm", "set-active-admin", component], timeout=40)
    low = (out or "").lower()
    if "success" in low:
        return True, "הרכיב הופעל כמנהל-התקן (device admin) בהצלחה"
    if not (out or "").strip():
        return False, "אין תשובה מהמכשיר — בדוק חיבור ADB"
    return False, out.strip()


def adb_remove_active_admin(adb: str, component: str) -> tuple[bool, str]:
    """ביטול רכיב מנהל-התקן פעיל."""
    out = _run([adb, "shell", "dpm", "remove-active-admin", component], timeout=40)
    low = (out or "").lower()
    if "success" in low or not (out or "").strip():
        return True, "בוטל מנהל-ההתקן (אם היה מוגדר)"
    return False, out.strip()


# ---------------------------------------------------------------------- Fastboot

def fastboot_devices_connected(fb: str) -> bool:
    out = _run([fb, "devices"], timeout=8)
    return any(line.strip() and "\t" in line for line in out.splitlines())


def read_fastboot_info(fb: str) -> Optional[DeviceInfo]:
    if not fastboot_devices_connected(fb):
        return None
    info = DeviceInfo(mode="fastboot")
    info.model = _fb_var(fb, "product")
    info.cpu = _norm_cpu(_fb_var(fb, "product"))
    if not info.cpu:
        info.cpu = _norm_cpu(_fb_var(fb, "board"))
    volt = _fb_var(fb, "battery-voltage")
    if volt:
        info.extra = f"מתח סוללה: {volt}"
        info.voltage_mv = _parse_voltage_mv(volt)
    unl = _fb_var(fb, "unlocked").strip().lower()
    if unl in ("yes", "true", "1"):
        info.unlocked = True
    elif unl in ("no", "false", "0"):
        info.unlocked = False
    soc = _fb_var(fb, "battery-soc-ok").strip().lower()
    if soc in ("yes", "true", "1"):
        info.soc_ok = True
    elif soc in ("no", "false", "0"):
        info.soc_ok = False
    elif soc.isdigit():
        info.battery = max(0, min(100, int(soc)))
    return info

def _parse_voltage_mv(raw):
    """ממיר מחרוזת מתח (4321mV / 4.32V / 4321000uV) למיליוולט."""
    import re as _re
    m = _re.search(r"([0-9.]+)", raw or "")
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    low = (raw or "").lower()
    if "uv" in low or val > 100000:
        return int(val / 1000)
    if "." in m.group(1) and val < 20:
        return int(val * 1000)
    return int(val)


_FBVAR_RE = re.compile(r":\s*(.+?)\s*$")


def _fb_var(fb: str, var: str) -> str:
    out = _run([fb, "getvar", var], timeout=8)
    for line in out.splitlines():
        if var in line:
            m = _FBVAR_RE.search(line)
            if m and m.group(1).lower() not in ("", "not found"):
                return m.group(1).strip()
    return ""


# ---------------------------------------------------------------------- probe כללי


def probe(has_brom_port: bool, brom_cpu: str = "") -> DeviceInfo:
    """
    בודק מה מחובר ומחזיר DeviceInfo — סדר זיהוי מדורג:
      1. ADB (הטלפון דלוק) — הערוץ העשיר ביותר: דגם, מעבד, אחוז סוללה.
      2. BROM/Preloader — רק אם זוהה פורט MTK (VID 0E8D); שם המעבד מתקבל
         מקריאת GPT של mtkclient, והיא מוצעת למשתמש מהממשק.
    Fastboot אינו נבדק כאן בכלל: הוא פרוטוקול נפרד, מזוהה רק בבקשת המשתמש
    מלשונית Fastboot — כדי שהזיהוי האוטומטי לא יתחרה ב-ADB/BROM.

    :param has_brom_port: האם זוהה פורט MTK (VID 0E8D)
    :param brom_cpu: המעבד שזוהה כבר (מGPT), להצגה במצב BROM
    """
    adb = find_adb_exe()
    if adb:
        info = read_adb_info(str(adb))
        if info:
            return info
    if has_brom_port:
        return DeviceInfo(mode="brom", cpu=_norm_cpu(brom_cpu))
    return DeviceInfo(mode="none")
