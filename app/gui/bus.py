# -*- coding: utf-8 -*-
"""
אוטובוס אותות Qt — מעביר אירועים מתהליכי רקע ל-UI בבטחה.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class Bus(QObject):
    """אותות גלובליים לעדכון ה-UI (thread-safe דרך QueuedConnection)."""

    log_line = Signal(str, str)          # level, message
    progress = Signal(float, str)        # percent, suffix
    job_done = Signal(str, bool)         # job name, success
    ports_changed = Signal(list)         # list[PortInfo]
    gpt_parsed = Signal(object)          # GptTable
    status = Signal(str)                 # הודעת מצב
    sec_parsed = Signal(object)          # dict של מצב אבטחה/בוטלאודר
    fb_parsed = Signal(object, object)   # (dict, raw) של מצב Fastboot
    device_info = Signal(object)         # DeviceInfo לפס הסטטוס העליון
    battery_warning = Signal(str)        # אזהרת סוללה נמוכה
    pyenv_report = Signal(object)        # PyEnvReport — זיהוי סביבת פייתון
    brom_detected = Signal()             # מכשיר ב-BROM בלי ADB — להצעת קריאת GPT ב-UI
    adb_details = Signal(str, str)       # (text, level) — מידע ADB מ-thread רקע ל-UI
    adb_pkgs_text = Signal(str)          # טקסט לתצוגת חבילות/תוצאות בלשונית ADB
    adb_apps_list = Signal(object)       # (דור, [AppEntry]) — רשימת האפליקציות
    adb_app_update = Signal(object)      # (דור, AppEntry, מספר, סה"כ) — שם/אייקון נטענו
    adb_app_details = Signal(object)     # dict — מידע מפורט על אפליקציה
    tool_locked = Signal(str)            # ערוץ התקשורת ננעל (adb/brom/fastboot)
    adb_boot_state = Signal(object)      # מצב בוטלאודר שנקרא דרך ADB
    adb_uninstall_progress = Signal(object)  # (מספר, סה"כ, חבילה, הצליח, הודעה)
    adb_op_result = Signal(object)       # (הצליח, כותרת, טקסט) — הודעת סיום
    adb_app_restored = Signal(str)       # אפליקציה שוחזרה — הסרת הסימון מהשורה
    adb_fs_listing = Signal(object)      # (path, [FileEntry], error) — תוכן תיקייה בסייר
    adb_fs_op = Signal(object)           # (הצליח, כותרת, טקסט, לרענן) — תוצאת פעולת קבצים
    adb_fs_edit_ready = Signal(object)   # (הצליח, remote, local, הודעה) — קובץ נמשך לעריכה
    adb_install_downgrade = Signal(str)  # ההתקנה נחסמה (גרסה ישנה) — להציע הסרה+התקנה
    reconnect_hint = Signal(object)      # (שם שלב, שניות) — לבקש מהמשתמש לחבר מחדש
    pyinstall_done = Signal(object)      # (הצליח, הודעה) — התקנת פייתון + ספריות אוטומטית
    driver_fix_result = Signal(object)   # list[(מצב, סוג, טקסט)] — תוצאת "תקן דרייבר למכשיר המחובר"
    root_pipeline_step = Signal(object)  # dict — התקדמות פייפליין הרוטינג האוטומטי (לשונית בפיתוח)


bus = Bus()
