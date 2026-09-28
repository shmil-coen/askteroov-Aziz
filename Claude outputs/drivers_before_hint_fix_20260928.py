# -*- coding: utf-8 -*-
"""
בדיקת מצב הדרייברים במחשב — קריאה בלבד.

כל בדיקה עונה על השאלה של הלשונית שלה: "האם הדרייברים שנדרשים לפעולה כאן
מותקנים במחשב?". הבדיקה קוראת את רשימת חבילות הדרייבר של Windows
(`pnputil /enum-drivers`), ואם זה לא זמין — סורקת את קובצי ה-INF שהותקנו
(`%SystemRoot%\\INF\\oem*.inf`). אין כאן כתיבה, התקנה או שינוי במערכת.

הניסוח מכוון להיות **ניטרלי מבחינת יצרן**: נבדק אם קיים דרייבר שמתאים למצב
ADB ולמצב Fastboot, בלי להציג את שם החברה שמספקת אותו.

מה הבדיקה **אינה** עושה: היא לא מאמתת חיבור חי של מכשיר. היא בודקת אם הדרייבר
קיים במחשב; האימות הסופי הוא לחבר את המכשיר ולראות שהוא מזוהה.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# מזהי החומרה של רכיבי Android/MediaTek — מופיעים בקובצי ה-INF של הדרייברים
MTK_VID = "vid_0e8d"        # MediaTek — BROM / PreLoader
ANDROID_USB_VID = "vid_18d1"  # רכיב USB במצב Android (ADB / Bootloader)

# מילות זיהוי *ספציפיות* לכל נושא. ב-BROM לא די ב"mediatek" כללי: במחשבים רבים
# יש דרייבר Wi-Fi/Bluetooth של MediaTek שאינו קשור ל-BROM.
_MTK_STRONG = ("vcom", "preloader", "mediatek usb port", "sp flash tool")

# מחלקת ההתקנים "יציאות (COM ו-LPT)" — מזהה קבוע של Microsoft, זהה בכל Windows
# ובכל שפה. דרייבר של MediaTek במחלקה הזו = דרייבר VCOM (BROM/PreLoader).
PORTS_CLASS_GUID = "{4d36e978-e325-11ce-bfc1-08002be10318}"
# מזהי החומרה של BROM ו-PreLoader בקובץ ה-INF (לאימות נוסף)
_MTK_BROM_IDS = ("vid_0e8d&pid_0003", "vid_0e8d&pid_2000")


def _mtk_port_drivers(text: str) -> list[str]:
    """דרייברים של MediaTek במחלקת יציאות COM — מתוך פלט pnputil.

    הפלט מחולק לרשומות לפי שורות ריקות; לא מסתמכים על שמות השדות (הם עשויים
    להיות מתורגמים), אלא על שם הספק (MediaTek) ועל מזהה המחלקה הקבוע.
    מחזיר את שמות קובצי ה-INF המקוריים (למשל cdc-acm.inf) לתצוגה.
    """
    found: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        low = block.lower()
        if "mediatek" not in low or PORTS_CLASS_GUID not in low:
            continue
        infs = re.findall(r"[\w.-]+\.inf", block, flags=re.IGNORECASE)
        published = [i for i in infs if re.fullmatch(r"oem\d+\.inf", i, re.IGNORECASE)]
        original = [i for i in infs if i not in published]
        # אימות נוסף: אם אפשר לקרוא את קובץ ה-INF שהותקן — לוודא מזהי BROM/PreLoader
        if published:
            try:
                inf_txt = (_sysroot() / "INF" / published[0]).read_text(
                    encoding="latin-1", errors="replace").replace("\x00", "").lower()
                if not any(i in inf_txt for i in _MTK_BROM_IDS):
                    continue
            except OSError:
                pass   # לא ניתן לקרוא — מסתפקים בספק + מחלקה
        found.append((original or published or ["MediaTek COM"])[0])
    return found

# המצבים בלשוניות: ADB (ניהול המכשיר) ו-Fastboot (צריבה ומחיקה). הזיהוי לפי
# שמות *ממשקי ההתקן* — כך זה עובד גם עם דרייברים של יצרנים שונים.
_MODE_KEYS = {
    "adb": ("android adb interface", "android composite adb interface",
            "adb interface", "android usb device", "android_winusb"),
    "fastboot": ("android bootloader interface", "bootloader interface",
                 "android usb device", "android_winusb"),
}

# שמות קריאים לתצוגה — בלי שמות חברות
_KEY_LABELS = {
    "android adb interface": "ממשק ADB של Android",
    "android composite adb interface": "ממשק ADB משולב של Android",
    "adb interface": "ממשק ADB",
    "android bootloader interface": "ממשק Bootloader של Android",
    "bootloader interface": "ממשק Bootloader",
    "android usb device": "התקן USB של Android",
    "android_winusb": "חבילת דרייבר Android USB",
}

_MODE_HELP = {
    "adb": "נדרש כדי ש-Windows יזהה את המכשיר במצב ADB — קריאת מידע וניהול אפליקציות.",
    "fastboot": "נדרש כדי ש-Windows יזהה את המכשיר במצב Fastboot — צריבה ומחיקה של מחיצות.",
}


@dataclass
class DriverStatus:
    """תוצאת בדיקה של נושא דרייברים אחד."""
    title: str                                      # כותרת הבדיקה (מוצגת למשתמש)
    ok: bool                                        # האם הדרייבר הנדרש נמצא
    lines: list[str] = field(default_factory=list)   # פירוט שורה-שורה
    hint: str = ""                                  # מה לעשות כשחסר


def _sysroot() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows"))


def _decode(raw: bytes) -> str:
    """פענוח פלט של כלי קונסולה — קידוד המערכת משתנה בין מחשבים.

    מילות הזיהוי שלנו הן ASCII, ולכן גם פענוח 'רך' שומר אותן.
    """
    if not raw:
        return ""
    if b"\x00" in raw[:200]:            # פלט UTF-16
        try:
            return raw.decode("utf-16-le", errors="replace")
        except (UnicodeDecodeError, LookupError):
            pass
    for enc in ("utf-8", "cp862", "cp1255"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


def _run_quiet(cmd: list[str], timeout: float = 30.0) -> str:
    """הרצת פקודה מקומית בלי חלון קונסולה; שגיאה = מחרוזת ריקה."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return ""
    return _decode((p.stdout or b"") + (p.stderr or b""))


def _installed_drivers_text() -> tuple[str, str]:
    """טקסט של כל חבילות הדרייבר במחשב, ומהיכן נלקח.

    קודם pnputil (המקור המדויק), ואם אינו זמין — סריקת קובצי ה-INF.
    """
    text = _run_quiet(["pnputil", "/enum-drivers"])
    if text.strip():
        return "pnputil", text
    parts: list[str] = []
    inf_dir = _sysroot() / "INF"
    try:
        for inf in sorted(inf_dir.glob("oem*.inf"))[:600]:
            try:
                parts.append(inf.read_text(encoding="latin-1", errors="replace"))
            except OSError:
                continue
    except OSError:
        pass
    return "inf", "\n".join(parts)


def _source_line(where: str) -> str:
    """שורת מקור הבדיקה — מהיכן נלקח המידע."""
    src = ("רשימת הדרייברים של Windows\u200f (pnputil)\u200f" if where == "pnputil"
           else "סריקת קובצי INF של הדרייברים")
    return f"מקור הבדיקה: {src}"


def check_mediatek() -> DriverStatus:
    """דרייבר MediaTek (VCOM/PreLoader) + UsbDk — מה שנדרש בלשונית mtkclient."""
    where, text = _installed_drivers_text()
    low = text.lower()
    strong = sorted({k for k in _MTK_STRONG if k in low})
    if where == "pnputil":
        strong += [f"{n} — יציאת COM" for n in _mtk_port_drivers(text)]
    elif any(i in low for i in _MTK_BROM_IDS):
        strong.append("מזהי BROM/PreLoader בקובץ INF")
    lines: list[str] = []

    if strong:
        lines.append(f"✅ דרייבר MediaTek VCOM/PreLoader — נמצא ({', '.join(strong)})")
    elif "mediatek" in low:
        lines.append("❓ נמצאו דרייברים של MediaTek, אבל לא VCOM/PreLoader — ייתכן "
                     "שאלה דרייברים של Wi-Fi/Bluetooth שבמחשב, ולא הדרייבר שנדרש "
                     "למצב BROM.")
    else:
        lines.append("❌ דרייבר MediaTek VCOM/PreLoader לא נמצא במחשב.")

    usbdk_sys = _sysroot() / "System32" / "drivers" / "UsbDk.sys"
    usbdk = usbdk_sys.is_file() or "usbdk" in low
    lines.append("✅ UsbDk — מותקן" if usbdk else
                 "❌ UsbDk — לא מותקן (mtkclient משתמש בו בגישה ל-BROM)")
    lines.append(_source_line(where))
    lines.append("רמז: המחשב כבר ראה רכיב של MediaTek בעבר."
                 if MTK_VID in low else
                 "רמז: המחשב לא ראה עדיין רכיב של MediaTek.")

    ok = bool(strong) or usbdk
    hint = ""
    if not ok:
        hint = ("התקן את דרייבר MediaTek VCOM/PreLoader (כפתור ההתקנה שליד), "
                "או התקן UsbDk (כפתור ההתקנה שליד).")
    elif not (strong and usbdk):
        hint = "אחד משני החלקים חסר — ראה השורות למעלה."
    return DriverStatus("דרייברים למצב BROM / PreLoader\u200f (mtkclient)\u200f", ok, lines, hint)


def check_mode(mode: str) -> DriverStatus:
    """הדרייבר שנדרש לפעולה של לשונית מסוימת: ADB או Fastboot.

    mode: "adb" — ניהול המכשיר;  "fastboot" — צריבה ומחיקה.
    """
    mode = "adb" if mode not in _MODE_KEYS else mode
    keys = _MODE_KEYS[mode]
    name = "ADB" if mode == "adb" else "Fastboot"
    where, text = _installed_drivers_text()
    low = text.lower()
    hits = [k for k in keys if k in low]
    lines: list[str] = []

    if hits:
        nice = sorted({_KEY_LABELS.get(k, k) for k in hits})
        lines.append(f"✅ נמצא דרייבר מתאים למצב {name}: {', '.join(nice)}")
    else:
        lines.append(f"❌ לא נמצא דרייבר מתאים למצב {name} במחשב הזה.")
    lines.append(_MODE_HELP[mode])
    lines.append(_source_line(where))
    lines.append("רמז: המחשב כבר ראה רכיב USB של Android בעבר."
                 if ANDROID_USB_VID in low else
                 "רמז: המחשב לא ראה עדיין רכיב USB של Android.")

    ok = bool(hits)
    hint = ("" if ok else
            f"הורד והתקן את דרייבר ה-USB של Android (כפתור ההורדה שליד) — "
            f"בלעדיו Windows לא יזהה את המכשיר במצב {name}.")
    return DriverStatus(f"דרייבר {name} — ללשונית {name}", ok, lines, hint)


def format_status(st: DriverStatus) -> str:
    """מחרוזת להצגה למשתמש (וגם ללוג)."""
    head = "✅" if st.ok else "❌"
    out = [f"{head} {st.title}"]
    out += [f"   {line}" for line in st.lines]
    if st.hint:
        out.append(f"   ↪ {st.hint}")
    return "\n".join(out)
