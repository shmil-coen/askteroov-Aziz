# -*- coding: utf-8 -*-
"""
החלון הראשי — הסקטארוב. פריסה RTL (מימין לשמאל).

מרכז שליטה: כל פעולה מול המכשיר נבנית כתוכנית (Job), מוצגת למשתמש
בחלון "אישור פעולה" עם הפקודות המדויקות — ורצה רק אחרי אישור מפורש.
"""
from __future__ import annotations

import subprocess
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QSizePolicy,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..core import config, scatter_bank
from ..core.checksums import format_size
from ..core.gpt_parser import (
    GptTable,
    parse_gpt_output,
    parse_target_config,
    summarize_bootloader,
)
from ..core.jobs import (
    Job,
    job_manager,
    plan_backup_nvram,
    plan_fastboot_erase,
    plan_fastboot_flash,
    plan_fastboot_simple,
    plan_read_all,
    plan_read_partitions,
    plan_read_preloader,
    plan_simple,
    plan_write_partition,
)
from ..core.logs import log
from ..core.fastboot_bridge import (
    FastbootCommands,
    parse_fastboot_vars,
    summarize_fastboot,
)
from ..core.mtk_bridge import MtkCommands
from ..core.port_monitor import PortMonitor, is_preloader_port, scan_ports
from ..core.safety import get_partition_warning
from ..core.scatter import (
    DEFAULT_BLOCK_SIZE,
    default_block_size,
    generate_scatter,
    is_placeholder_chip,
    scatter_filename,
    validate_scatter,
)
from . import theme
from . import icons as guiicons   # סמלים מצוירים (חץ שאיבה/צריבה)
from ..core import device_info as devinfo
from .bus import bus
from .device_status import DeviceStatusWidget

_DRIVERS_URL = "https://mtkdriver.com/"  # מאגר דרייברי MediaTek VCOM/Preloader
# MTKClient Portable — mtkclient עם פייתון נייד (Google Drive, פתוח לכל מי שיש לו את הקישור)
_MTK_PORTABLE_URL = "https://drive.google.com/file/d/1o4fo1Iuw798wc5cUfxiLCyjg6WkUNZJm/view"
_USBDK_URL = "https://github.com/daynix/UsbDk/releases"  # דף ההורדות הרשמי של UsbDk (Daynix)

_YES = QMessageBox.StandardButton.Yes
_NO = QMessageBox.StandardButton.No

# טולטיפי עזרה (מוצמדים לסמן 💡) — מה הפעולה עושה, למה היא משמשת ומה ההשלכות
_ACTION_HELP = {
    "gpt": ("קריאת GPT\u200f (printgpt)\u200f",
            "מה זה עושה: קורא את טבלת המחיצות מהמכשיר דרך mtkclient.\n"
            "למה זה משמש: רואים את כל המחיצות (שמות וגדלים), מזהה אוטומטית את שם המעבד, "
            "וזה השלב הראשון לפני יצירת Scatter.\n"
            "השלכות: קריאה בלבד – לא משנה כלום במכשיר."),
    "readback": ("שאיבת מחיצות (Readback)",
                 "מה זה עושה: מעתיק את תוכן המחיצות המסומנות מהמכשיר לקובצי .img.\n"
                 "למה זה משמש: גיבוי לפני צריבה, שחזור בעתיד או ניתוח במחשב.\n"
                 "השלכות: קריאה בלבד – לא משנה כלום במכשיר."),
    "flash": ("צריבת Image למחיצה (mtk w)",
              "מה זה עושה: כותב קובץ תמונה על מחיצה במכשיר (עם גיבוי אוטומטי לפני כן, לבחירתך).\n"
              "למה זה משמש: החלפת boot (לדוגמה: boot מושרש לצורך השגת רוט) / recovery / system וכדומה.\n"
              "השלכות: ⚠️ פעולת כתיבה! מחיצה בחתימה לא מקורית עלולה לגרום למכשיר להיכנס "
              "ללולאת אתחול (bootloop) – ודא שהבוטלאודר פתוח, ובמכשירים שדורשים זאת – "
              "שאימות החתימות (vbmeta) מבוטל. מחיצה שגויה עלולה להמית את המכשיר – "
              "ודא שהקובץ מתאים למכשיר ולגודל המחיצה."),
    "seccfg": ("פתיחה / נעילת בוטלאודר (seccfg)",
               "מה זה עושה: משנה את תצורת אבטחת המכשיר (מצב הבוטלאודר).\n"
               "למה זה משמש: פתיחת הבוטלאודר מאפשרת צריבה ב-Fastboot; נעילה מחזירה למצב סטנדרטי.\n"
               "השלכות: ⚠️ פתיחת הבוטלאודר מוחקת את כל נתוני המשתמש!"),
    "security": ("בדיקת מצב אבטחה / בוטלאודר (gettargetconfig)",
                 "מה זה עושה: קורא את מצב Secure Boot / DAA / SLA מהמכשיר.\n"
                 "למה זה משמש: לדעת אם המכשיר פתוח לצריבה.\n"
                 "השלכות: קריאה בלבד – לא משנה כלום במכשיר."),
    "fb_detect": ("זיהוי מכשיר במצב Fastboot\u200f (fastboot devices)",
                  "מה זה עושה: בודק אם מכשיר מחובר במצב Fastboot.\n"
                  "השלכות: קריאה בלבד."),
    "fb_info": ("מידע ומצב נעילה",
                "מה זה עושה: קורא את כל פרטי ה-Fastboot (מוצר, סוללה, מצב נעילה).\n"
                "השלכות: קריאה בלבד."),
    "fb_flash": ("צריבת מחיצה (fastboot flash)",
                 "מה זה עושה: כותב קובץ \u200e.img למחיצה לפי שם.\n"
                 "השלכות: ⚠️ פעולת כתיבה – דורשת בוטלאודר פתוח. מחיצה בחתימה לא מקורית עלולה "
                 "לגרום למכשיר להיכנס ללולאת אתחול (bootloop) – במכשירים שדורשים זאת, ודא "
                 "שאימות החתימות (vbmeta) מבוטל. מחיצה שגויה עלולה להמית את המכשיר."),
    "fb_erase": ("fastboot erase",
                 "מה זה עושה: מוחק את תוכן מחיצה לפי שם.\n"
                 "השלכות: ⚠️ הנתונים במחיצה יאבדו לצמיתות! ודא שיש לך גיבוי של המחיצה לפני המחיקה."),
    "fb_reboot": ("הפעלת המכשיר מחדש (fastboot reboot)",
                  "מה זה עושה: מפעיל את המכשיר מחדש למערכת.\n"
                  "השלכות: ללא – אתחול רגיל."),
    "fb_reboot_bl": ("אתחול מחדש למצב Fastboot\u200f (fastboot reboot bootloader)\u200f",
                     "מה זה עושה: מאתחל את המכשיר ישר למצב Fastboot.\n"
                     "למה זה משמש: מעבר מהיר לצריבה, בלי ללחוץ על כפתורי המכשיר (כמו ווליום למטה + הפעלה).\n"
                     "השלכות: ללא – אתחול רגיל."),
    "adb_info": ("קריאת מידע ב-ADB",
                 "מה זה עושה: קורא את פרטי המכשיר: יצרן ומותג, דגם וקוד מכשיר, מעבד וחומרה, גרסת אנדרואיד ורמת API, גרסת Build, מספר סידורי, מצב Verified Boot ורמת סוללה.\n"
                 "השלכות: קריאה בלבד – לא משנה כלום במכשיר."),
    "adb_uninstall": ("הסרת אפליקציה (pm uninstall)",
                      "מה זה עושה: מסיר אפליקציה לפי שם החבילה; אפשר להסיר תוך שמירת נתונים (-k).\n"
                      "השלכות: ⚠️ האפליקציה תיעלם מהמכשיר; הסרת אפליקציות מערכת עלולה לפגוע בתפקוד!"),
    "adb_install": ("התקנת APK",
                    "מה זה עושה: מתקין קובץ \u200e.apk מהמחשב אל המכשיר (עדכון אפשרי עם \u200e-r).\n"
                    "למה זה משמש: מאפשר להתקין על המכשיר מגוון חבילות אפליקציה (APK, APKM, XAPK, APKS); את הקובץ בוחרים בקלות מזיכרון המחשב.\n"
                    "השלכות: התקנה על גבי אפליקציה קיימת שומרת על הנתונים שלה."),
    "adb_admin": ("הענקת הרשאות ניהול מלאות (device owner / admin)",
                  "מה זה עושה: מעניק לאפליקציה בעלות על המכשיר (dpm set-device-owner) "
                  "או מפעיל אותה כמנהל-התקן – נדרש לאפליקציות סינון כדי שלא יוסרו.\n"
                  "השלכות: בעלות על המכשיר דורשת שלא יהיו חשבונות במכשיר; הסרת הבעלות עלולה לדרוש איפוס יצרן."),
    "adb_reboot_bl": ("מעבר למצב Fastboot דרך ADB\u200f (adb reboot bootloader)\u200f",
                      "מה זה עושה: מאתחל את המכשיר הדלוק למצב Fastboot דרך ADB.\n"
                      "למה זה משמש: מעבר נוח מ-Android ל-Fastboot, בלי ללחוץ על כפתורי המכשיר (כמו ווליום למטה + הפעלה).\n"
                      "השלכות: ללא – אתחול בלבד; הבוטלאודר עצמו לא נפתח ולא ננעל, "
                      "והנתונים במכשיר לא נמחקים."),
    "adb_list": ("רשימת אפליקציות מותקנות",
                 "מה זה עושה: מציג את האפליקציות המותקנות ואת שמות החבילות שלהן.\n"
                 "למה זה משמש: איתור אפליקציה לניהול – הסרה, או הענקת בעלות מלאה לניהול המכשיר."),
}


class _ToggleSwitch(QAbstractButton):
    """מתג החלפה (כמו במערכות הפעלה) — לפריטי הגדרות, במקום תיבת סימון.

    מלבן מעוגל עם עיגול שנע מצד לצד: דלוק = תכלת דיגיטלי, כבוי = אפור.
    הגובה נקבע בבניה (גם לתפריט ההגדרות המוגדל).
    """

    def __init__(self, parent=None, height: int = 26):
        super().__init__(parent)
        h = max(18, int(height))
        self._h = h
        self._w = int(h * 2.0)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self._w, self._h)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _event):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QBrush, QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#2f81f7") if on else QColor("#7f8a95")))
        radius = self._h / 2.0
        p.drawRoundedRect(QRectF(0, 0, self._w, self._h), radius, radius)
        d = self._h - 4          # קוטר העיגול (המחוון)
        x = (self._w - d - 2) if on else 2.0
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QRectF(x, 2, d, d))
        p.end()


class _TextEditDialog(QDialog):
    """עורך טקסט פשוט לעריכת קובץ שנמשך מהמכשיר."""

    def __init__(self, parent, name: str, text: str):
        super().__init__(parent)
        self.setWindowTitle(f"עריכת קובץ: {name}")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"עריכת {name} — לחיצה על 'שמור' תעלה את הקובץ בחזרה למכשיר."))
        self._edit = QPlainTextEdit()
        self._edit.setPlainText(text)
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mono = self._edit.font()
        mono.setFamily("Consolas")
        self._edit.setFont(mono)
        lay.addWidget(self._edit, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("💾 שמור והעלה")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("ביטול")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def text(self) -> str:
        return self._edit.toPlainText()


class _MainTabBar(QTabBar):
    """שורת הלשוניות הראשית: לשוניות 'ענף' (שאיבה/צריבה/Scatter) מצוירות ~10%
    קטנות יותר — כדי לתת תחושה שהן ענפים של הגזע (mtkclient)."""

    BRANCH_SCALE = 0.90

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._branch: set[int] = set()

    def set_branches(self, idxs) -> None:
        self._branch = set(idxs)
        self.updateGeometry()
        self.update()

    def tabSizeHint(self, index):
        sz = super().tabSizeHint(index)
        if index in self._branch:
            sz.setWidth(int(sz.width() * self.BRANCH_SCALE))
        return sz

    def paintEvent(self, event):
        from PySide6.QtWidgets import QStylePainter, QStyleOptionTab, QStyle
        p = QStylePainter(self)
        base_font = self.font()
        small_font = QFont(base_font)
        small_font.setPointSizeF(max(6.0, base_font.pointSizeF() * self.BRANCH_SCALE))
        for i in range(self.count()):
            opt = QStyleOptionTab()
            self.initStyleOption(opt, i)
            if i in self._branch:
                r = opt.rect
                dy = int(r.height() * (1 - self.BRANCH_SCALE))
                opt.rect = r.adjusted(0, dy, 0, 0)   # מעט נמוך יותר — תחושת ענף
                p.setFont(small_font)
            else:
                p.setFont(base_font)
            p.drawControl(QStyle.ControlElement.CE_TabBarTab, opt)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{config.APP_TITLE} v{config.APP_VERSION}")
        self.resize(1100, 740)
        # RTL: הממשק כולו מימין לשמאל
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self.dark = theme.load_dark()
        # צבעי הדגשה (פורט MTK / אזהרה) — מאותחלים כאן כדי שטבלת הפורטים לא תקרוס
        # לפני החלפת ערכת עיצוב (שם הם הוגדרו בעבר בלבד).
        self._mtk_color = theme.mtk_color
        self._warn_color = theme.warn_color
        # עיצוב כפתורי פעולה ראשיים (שאיבה/צריבה) — מוגדר במרכז ב-theme.py
        # (ירוק/אדום/כתום לפי objectName, עם וריאציה לערכה הבהירה) ומוחל משם.
        # כאן מוסיפים רק כללי צורה קבועים שלא תלויים בערכה.
        self.gpt: GptTable | None = None
        self._last_error: str = ""
        self._retry_action = None   # callable לחזרה על הפעולה האחרונה
        self._fb_warned = False     # אזהרת סוללה הוצגה כבר לחיבור Fastboot הנוכחי
        self._probing = False       # בדיקת מכשיר רצה כרגע — לא מתחילים עוד אחת
        self._apps_loading = False  # טעינת אפליקציות רצה — הבדיקה האוטומטית ממתינה
        # ערוץ תקשורת: none/auto/adb/fastboot/brom. בפתיחה "none" — אין שום חיפוש
        # אוטומטי עד שהמשתמש בוחר ערוץ (בדיאלוג הפתיחה או בשדה "ערוץ תקשורת")
        self._active_tool = "none"
        self._last_dev_info = None          # המידע החי האחרון (לסנכרון הסוללה בכותרת)
        self._boot_header_tooltip = ""      # טולטיפ אחרון של חיווי הבוטלאודר
        self._battery_probe_paused = False  # מושהה בזמן דיאלוג אזהרת סוללה
        self._last_probe_mode = None        # מצב הזיהוי הקודם (להודעות מעבר)
        self._gpt_timer = None              # טיימר איתור ניסיון GPT שנתקע (75 שניות)
        self._gpt_timeout_dialog = None     # דיאלוג "המכשיר לא זוהה" פתוח?
        # סמלי השאיבה/הצריבה — מצוירים מקומית (ירוק, בדיוק לפי הדגמים שנקבעו)
        self.icon_read = guiicons.curved_left_arrow_icon()
        self.icon_flash = guiicons.down_arrow_icon()
        self._brom_suggest_open = False     # דיאלוג הצעת GPT פתוח?
        self.port_monitor = PortMonitor()
        self.port_monitor.on_change = self._on_ports_changed

        self._build_ui()
        self._connect_bus()

        if not config.mtk_available():
            self._say("error", "הכלי mtkclient לא נמצא – פעולות מול המכשיר לא יעבדו. "
                               f"בדוק את הנתיב: {config.PORTABLE_ROOT}")
        self._load_previous_logs()   # #1: הצגת לוג מהפעלה קודמת
        self._refresh_ports()
        self.port_monitor.start()
        self._probe_device()
        # בדיקה תקופתית — כדי לזהות מכשיר ב-ADB/Fastboot גם בלי שינוי פורט BROM
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(4000)
        self._probe_timer.timeout.connect(lambda: self._probe_device())
        self._probe_timer.start()
        # #2: ניקוי מד ההתקדמות אחרי 30 שניות של חוסר פעילות
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.setInterval(30000)
        self._clear_timer.timeout.connect(self._clear_progress)
        # דיאלוג בחירת כלי תקשורת בפתיחה — צף מעל החלון, ניתן לסגור ולהמשיך.
        # מופיע תוך כדי שהזיהוי האוטומטי כבר רץ ברקע (~10 שניות ראשונות).
        QTimer.singleShot(400, self._startup_tool_dialog)
        QTimer.singleShot(1500, lambda: self._detect_pyenv(quiet=True))

    # ------------------------------------------------------------ עזרים
    def _say(self, level: str, message: str):
        """כותב ללוג המרכזי (קובץ + לשונית לוגים)."""
        {"info": log.info, "success": log.success, "warning": log.warn,
         "error": log.error}.get(level, log.info)(message)

    def _help_dot(self, key: str) -> QLabel:
        """סמן בועת-מידע (💡) לצד כפתור פעולה — לחיצה מציגה הסבר על הפעולה:
        מה היא עושה, למה היא משמשת ומה ההשלכות שלה על המכשיר."""
        dot = QLabel("💡")
        title, body = _ACTION_HELP.get(key, ("", "אין מידע."))
        dot.setCursor(Qt.CursorShape.PointingHandCursor)
        dot.setToolTip("לחץ למידע נוסף")

        def show(_=False):
            QMessageBox.information(self, title, body)

        dot.mousePressEvent = show
        return dot

    def _plan(self, factory, *args, **kwargs) -> Job | None:
        """בונה תוכנית עבודה; מציג שגיאה אם mtkclient חסר או הקלט לא תקין."""
        try:
            return factory(*args, **kwargs)
        except (RuntimeError, ValueError, OSError) as e:
            self._say("error", str(e))
            QMessageBox.critical(self, "שגיאה – לא ניתן לבצע",
                                 f"{e}\n\nבדוק את ההוראות (כפתור ❓ הוראות).")
            return None

    def _request(self, job: Job | None) -> bool:
        """חלון 'אישור פעולה' — רק אחרי אישור מפורש העבודה רצה."""
        if job is None:
            return False
        if job_manager.busy:
            QMessageBox.warning(self, "עסוק",
                                "יש פעולה פעילה — המתן לסיומה או לחץ 'בטל פעולה'.")
            return False
        dlg = QMessageBox(self)
        dlg.setWindowTitle("אישור פעולה")
        dlg.setIcon(QMessageBox.Icon.Warning if job.danger else QMessageBox.Icon.Question)
        dlg.setText(f"<b>{job.name}</b><br>לבצע את הפעולה הבאה?")
        body = "פקודות שירוצו:\n" + "\n".join(job.describe())
        if job.notes:
            body += "\n\n" + "\n".join(job.notes)
        dlg.setInformativeText(body)
        dlg.setStandardButtons(_YES | _NO)
        dlg.setDefaultButton(_NO if job.danger else _YES)
        dlg.button(_YES).setText("אשר והרץ")
        dlg.button(_NO).setText("ביטול")
        if dlg.exec() != _YES:
            self._say("info", f"בוטל על ידי המשתמש: {job.name}")
            return False
        try:
            job_manager.submit(job)
        except RuntimeError as e:
            QMessageBox.warning(self, "עסוק", str(e))
            return False
        self.cancel_btn.setEnabled(True)
        if getattr(self, "_clear_timer", None):
            self._clear_timer.stop()
        self._busy_progress(True)
        self.status_label.setText(f"{job.name}: מתחיל…")
        if job.danger:
            self.tabs.setCurrentWidget(self.logs_tab)
        return True

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        tb = QToolBar("תצוגה")
        tb.setMovable(False)
        self.toolbar = tb
        self.addToolBar(tb)
        # בנק הסקטארים בפס העליון: סמל + כפתור — בקצה הימני (ראשונים בתוספת ב-RTL)
        from .logo import BankGlyph
        self.bank_glyph = BankGlyph()
        self.bank_glyph.setVisible(False)   # מוצג רק כשבנק הוא התצוגה הפעילה
        tb.addWidget(self.bank_glyph)
        self.bank_action = QAction("🗂️ בנק סקטארים", self)
        self.bank_action.setCheckable(True)
        self.bank_action.setToolTip("פתיחת בנק הסקטארים — ארכיון קובצי Scatter")
        self.bank_action.triggered.connect(self._toggle_bank_view)
        tb.addAction(self.bank_action)
        self._bank_active = False
        # מרווח מתרחב — מפריד: הבנק בקצה הימני, כפתורי העיצוב בקצה השמאלי
        tb_spacer = QWidget()
        sp = tb_spacer.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        tb_spacer.setSizePolicy(sp)
        tb.addWidget(tb_spacer)
        # הגדרות — סמל בלבד (בלי המילה "הגדרות"): גרסה · אודות · סדר לשוניות גמיש.
        # ממוקם בתוספת לפני כפתורי העיצוב, כך שהם נשארים בקצה השמאלי בדיוק כמו היום.
        self.settings_action = QAction(guiicons.gear_icon(), "", self)
        self.settings_action.setToolTip(f"הגדרות – גרסה v{config.APP_VERSION} · אודות · עיצוב")
        self.settings_action.triggered.connect(self._open_settings_menu)
        tb.addAction(self.settings_action)
        # עיצוב בהיר/כהה — לא בפס העליון: נכנס לתפריט ההגדרות (מתחת למתג הסדר).
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self.light_action = QAction("🔵 כחול עמוק", self)
        self.dark_action = QAction("🌙 כהה", self)
        for act, is_dark in ((self.light_action, False), (self.dark_action, True)):
            act.setCheckable(True)
            act.setChecked(self.dark == is_dark)
            act.setFont(self._settings_small_font())   # כמו שאר המילים בתפריט
            act.setToolTip("הבחירה נשמרת להפעלה הבאה")
            act.triggered.connect(lambda _=False, d=is_dark: self._set_theme(d))
            self.theme_group.addAction(act)
        self.tabs = QTabWidget()
        self.tabs.setTabBar(_MainTabBar(self.tabs))   # שורת לשוניות עם 'ענפים' קטנים יותר
        # לשוניות ברוחב שווה (לא לפי אורך הטקסט) — הרוחב מחושב ב-resizeEvent
        self.tabs.setElideMode(Qt.TextElideMode.ElideNone)
        self.tabs.tabBar().setObjectName("mainTabBar")
        # אם הטקסטים לא נכנסים — חיצי גלילה במקום להכריח את החלון לגדול
        self.tabs.setUsesScrollButtons(True)
        self.device_tab = self._tab_device()
        # בנק הסקטארים — לא בשורת הלשוניות: כפתור ייעודי בפס העליון (מופיע למטה)
        self.bank_tab = self._tab_scatter_bank()
        self.tabs.addTab(self.device_tab, "mtkclient")
        # שאיבה וצריבה — צמוד ל-mtkclient (הן מתבצעות דרכו)
        rb_tab = self._scrollable(self._tab_readback())
        self.tabs.addTab(rb_tab, " שאיבה (Readback)")
        self.tabs.setTabIcon(self.tabs.indexOf(rb_tab), self.icon_read)
        fl_tab = self._scrollable(self._tab_flash())
        self.tabs.addTab(fl_tab, " צריבה (Download)")
        self.tabs.setTabIcon(self.tabs.indexOf(fl_tab), self.icon_flash)
        # Scatter — רביעי מימין, צמוד לצריבה (לבקשת המשתמש)
        self.scatter_tab = self._scrollable(self._tab_scatter())
        self.tabs.addTab(self.scatter_tab, "📄 Scatter")
        self.adb_tab = self._scrollable(self._tab_adb())
        self.tabs.addTab(self.adb_tab, "📱 ADB")
        # Fastboot צמוד ל-ADB (לבקשת המשתמש)
        self.fastboot_tab = self._scrollable(self._tab_fastboot())
        self.tabs.addTab(self.fastboot_tab, "⚡ Fastboot")
        self.boot_tab = self._scrollable(self._tab_bootloader())
        self.tabs.addTab(self.boot_tab, "🔓 Bootloader")
        # לוג — אחרונה משמאל, בקצה השורה (לבקשת המשתמש)
        self.logs_tab = self._tab_logs()
        self.tabs.addTab(self.logs_tab, "📜 לוג")
        self._apply_equal_tab_widths()   # לשוניות שוות על פני כל השורה
        # סדר ברירת המחדל (העיצוב הקבוע) — הסדר שאליו חוזרים כשהסדר הגמיש כבוי
        self._default_tab_order = [self.tabs.widget(i) for i in range(self.tabs.count())]
        # סדר לשוניות גמיש: כבוי כברירת מחדל. כשדולק — גרירת לשוניות, והסדר נשמר
        self._flex_tabs = theme.load_flexible_tabs()
        self._reordering = False
        self.tabs.tabBar().setMovable(self._flex_tabs)
        self.tabs.tabBar().tabMoved.connect(self._on_tab_moved)
        if self._flex_tabs:
            self._apply_saved_tab_order()

        # כותרת מצב מכשיר — מעל הלשוניות: דגם · מעבד · בוטלאודר · סוללה
        self.header = QGroupBox("מצב מכשיר")
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(10, 4, 10, 4)
        self.device_status = DeviceStatusWidget()
        hl.addWidget(self.device_status)
        hl.addStretch(1)
        hl.addWidget(QLabel("בוטלאודר:"))
        self.hdr_boot = QLabel("—")
        self.hdr_boot.setToolTip("מצב הבוטלאודר/אבטחה — מתעדכן אחרי בדיקת אבטחה או קריאת מידע")
        hl.addWidget(self.hdr_boot)
        hl.addSpacing(16)
        hl.addWidget(QLabel("ערוץ תקשורת:"))
        self.tool_combo = QComboBox()
        for text, key in (("לא נבחר", "none"), ("אוטומטי", "auto"), ("ADB", "adb"),
                          ("Fastboot", "fastboot"), ("mtkclient (BROM)", "brom")):
            self.tool_combo.addItem(text, key)
        self.tool_combo.setToolTip(
            "התוכנה תתחבר למכשיר רק דרך הערוץ שנבחר.\n"
            "'לא נבחר' – אין חיפוש מכשיר עד שבוחרים ערוץ.\n"
            "'אוטומטי' – מתחבר דרך הערוץ הראשון שמזהה את המכשיר, ונשאר בו.")
        self.tool_combo.currentIndexChanged.connect(self._on_tool_combo)
        hl.addWidget(self.tool_combo)
        # סוללה בכותרת — מוצג רק כשיש נתון (אחוז ב-ADB / מתח ב-Fastboot);
        # מסונכרן מהמידע החי העדכני ביותר גם אחרי פעולות שלא מדווחות סוללה
        self.battery_header = QLabel()
        self.battery_header.setVisible(False)
        hl.addWidget(self.battery_header)
        # שם המעבד בכותרת — מסונכרן מכל ערוץ זיהוי (GPT של mtkclient / ADB / Fastboot)
        # ונשאר מוצג כל עוד המכשיר מחובר
        self.cpu_header = QLabel()
        self.cpu_header.setVisible(False)
        hl.addWidget(self.cpu_header)

        # שורת התקדמות — הועלתה למעלה (מתחת לכותרת, מעל הלשוניות)
        progbar = QWidget()
        bl = QHBoxLayout(progbar)
        bl.setContentsMargins(0, 0, 0, 0)
        col = QVBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label = QLabel("מוכן")
        col.addWidget(self.progress)
        col.addWidget(self.status_label)
        bl.addLayout(col, 1)
        self.cancel_btn = QPushButton("⏹ בטל פעולה")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_job)
        bl.addWidget(self.cancel_btn)

        central = QWidget()
        cl = QVBoxLayout(central)
        # שוליים תחתונים גדולים — מרימים את התוכן (וכפתורי הצריבה) מעל תחתית החלון
        cl.setContentsMargins(9, 9, 9, 26)
        # לוגו התוכנה — שורה משלו, מרוכז במרכז החלון במדויק (stretch שווים משני צדדים)
        logo_row = QHBoxLayout()
        logo_row.addStretch(1)
        from .logo import LogoLabel
        self.logo_label = LogoLabel()
        logo_row.addWidget(self.logo_label)
        logo_row.addStretch(1)
        cl.addLayout(logo_row)

        cl.addWidget(self.header)
        cl.addWidget(self.tabs, 1)
        cl.addWidget(self.bank_tab, 1)   # מוצג רק כשבנק הסקטארים מופעל מהפס העליון
        self.bank_tab.hide()
        cl.addWidget(progbar)   # מד ההתקדמות בתחתית (קצת גבוה מהמקור)
        self.setCentralWidget(central)

    def _toggle_bank_view(self):
        """הצגה/הסתרה של בנק הסקטארים — הבנק מחליף את שורת הלשוניות כשהוא פעיל."""
        self._bank_active = not self._bank_active
        if self._bank_active:
            self._prev_tab_index = self.tabs.currentIndex()
            self.tabs.hide()
            self.bank_tab.show()
            self.bank_glyph.setVisible(True)
        else:
            self.bank_tab.hide()
            self.tabs.show()
            self.bank_glyph.setVisible(False)
            idx = getattr(self, "_prev_tab_index", 0)
            self.tabs.setCurrentIndex(idx if idx >= 0 else 0)

    def _apply_equal_tab_widths(self):
        """רוחב לשוניות אחיד: כל לשונית מקבלת את אותו מינימום-רוחב, מחושב לפי
        רוחב החלון מחולק מספר הלשוניות — כך הן ממלאות את השורה כולה בשווה."""
        n = self.tabs.count()
        if n:
            # min-width הוא רוחב התוכן בלבד — הריווח (10px מכל צד) והמסגרת נוספים
            # עליו. לכן מורידים אותם מהחישוב, אחרת סך הלשוניות רחב מהחלון,
            # החלון גדל, והחישוב רץ שוב — לולאת התנפחות.
            _PAD = 2 * 10 + 4
            w = max(40, (self.tabs.width() - 14) // n - _PAD)
            if w == getattr(self, "_last_tab_w", None):
                return   # אין שינוי — לא מחילים שוב (מונע לולאה)
            self._last_tab_w = w
            base = QApplication.instance().font().pointSizeF() or 9.0
            bar_font = QFont(QApplication.instance().font())
            bar_font.setPointSizeF(round(base * 1.25, 1))
            self.tabs.tabBar().setFont(bar_font)   # הגופן נשלט מכאן (כדי שהקטנת הענפים תעבוד בציור)
            self.tabs.setStyleSheet(
                f"QTabBar::tab {{ min-width: {w}px; padding: 8px 10px; }}")
            self._mark_branch_tabs()

    def _mark_branch_tabs(self):
        """מסמן את לשוניות ה'ענף' (שאיבה/צריבה/Scatter) שיצוירו מעט קטן יותר."""
        bar = self.tabs.tabBar()
        if not hasattr(bar, "set_branches"):
            return
        idxs = [i for i in range(self.tabs.count())
                if any(k in self.tabs.tabText(i) for k in ("שאיבה", "צריבה", "Scatter"))]
        bar.set_branches(idxs)

    # ------------------------------------------------- הגדרות: גרסה · אודות · סדר גמיש
    # גודל תפריט ההגדרות — פי 2 מהרגיל, ואחר כך הקטנה של 25% (לבקשת המשתמש)
    _SETTINGS_MENU_SCALE = 1.5
    # המילים 'אודות' / 'סדר לשוניות גמיש' / 'בהיר-כהה' והסמלים שלידן — 20% פחות
    _SETTINGS_SMALL_SCALE = 0.8

    def _settings_small_font(self) -> QFont:
        """גופן מוקטן למילים בתפריט ההגדרות ולסמלים שלידן."""
        f = QFont(QApplication.instance().font())
        base = f.pointSizeF() if f.pointSizeF() > 0 else 9.0
        f.setPointSizeF(round(base * self._SETTINGS_MENU_SCALE * self._SETTINGS_SMALL_SCALE, 1))
        return f

    def _open_settings_menu(self):
        """תפריט ההגדרות (סמל בלבד): מספר גרסה · אודות · מתג 'סדר לשוניות גמיש'.

        התפריט מוגדל פי 2 — גופן, שורות ומתג.  'סדר לשוניות גמיש' הוא מתג
        (לא תיבת סימון), והלחיצה עליו מחילה מיד את המצב החדש.  ה'אודות' כתוב
        בתוך התפריט עצמו, מתחת למילה — בלי חלון קופץ.
        """
        from PySide6.QtWidgets import QMenu, QWidgetAction
        m = QMenu(self)
        font = QFont(QApplication.instance().font())
        base = font.pointSizeF() if font.pointSizeF() > 0 else 9.0
        font.setPointSizeF(round(base * self._SETTINGS_MENU_SCALE, 1))
        m.setFont(font)
        small = self._settings_small_font()   # המילים והסמלים המוקטנים בתפריט
        ver = m.addAction(f"גרסה v{config.APP_VERSION}")
        ver.setEnabled(False)   # מציג מידע בלבד — לא לחיץ
        m.addSeparator()
        # 'אודות' — כתוב בתפריט עצמו, מתחת למילה; לא נפתח חלון קופץ/דיאלוג
        about_row = QWidget()
        ab = QVBoxLayout(about_row)
        ab.setContentsMargins(12, 4, 12, 6)
        ab.setSpacing(6)
        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        head_icon = QLabel()
        head_icon.setPixmap(guiicons.round_info_pixmap(round(small.pointSizeF() * 1.35)))
        head_text = QLabel("אודות")
        head_text.setFont(small)   # אותו גופן כמו שאר המילים בתפריט — לא מודגש
        head_row.addWidget(head_icon)
        head_row.addWidget(head_text)
        head_row.addStretch(1)
        ab.addLayout(head_row)
        about_txt = QLabel(self._about_text())
        about_txt.setTextFormat(Qt.TextFormat.RichText)
        about_txt.setWordWrap(True)
        about_txt.setFixedWidth(int(font.pointSizeF() * 26))
        ab.addWidget(about_txt)
        act_about = QWidgetAction(m)
        act_about.setDefaultWidget(about_row)
        m.addAction(act_about)
        m.addSeparator()
        # 'סדר לשוניות גמיש' — שורה עם מתג; הלחיצה מחילה מיד והתפריט נשאר פתוח
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 6, 12, 6)
        rl.setSpacing(14)
        lbl = QLabel("סדר לשוניות עצמאית")
        lbl.setFont(small)   # המילה והמתג באותו גודל מוקטן
        # המתג קטן ל-35% מגודלו הקודם (לבקשת המשתמש)
        sw = _ToggleSwitch(row, height=round(26 * self._SETTINGS_MENU_SCALE * 0.35))
        sw.setChecked(self._flex_tabs)
        sw.setToolTip("דלוק: אפשר לגרור לשוניות ולשנות את סדרן (הסדר נשמר להפעלה הבאה).\n"
                      "כבוי: חוזר לסדר ברירת המחדל של התוכנה.")
        sw.toggled.connect(self._set_flex_tabs)
        rl.addWidget(lbl)
        rl.addStretch(1)
        rl.addWidget(sw)
        act = QWidgetAction(m)
        act.setDefaultWidget(row)
        m.addAction(act)
        # בחירת העיצוב — עברה מהפס העליון לכאן, מתחת למתג הסדר (לבקשת המשתמש)
        m.addSeparator()
        m.addAction(self.light_action)
        m.addAction(self.dark_action)
        m.exec(self.toolbar.mapToGlobal(self.toolbar.rect().bottomLeft()))

    def _about_text(self) -> str:
        """טקסט ה'אודות' שמוצג בתפריט ההגדרות — תיאור המוצר והמפתח/ת.

        הטקסטים נקבעים ב-`config.APP_ABOUT` / `config.APP_AUTHOR`.
        """
        parts = [t for t in (config.APP_ABOUT.strip(), config.APP_AUTHOR.strip()) if t]
        return "<br><br>".join(parts).replace("\n", "<br>")

    def _on_tab_moved(self, _from: int, _to: int):
        """אחרי גרירת לשונית: סימון מחדש של לשוניות ה'ענף' ושמירת הסדר."""
        self._mark_branch_tabs()
        if self._flex_tabs and not self._reordering:
            self._save_current_tab_order()

    def _set_flex_tabs(self, on: bool):
        """הדלקה/כיבוי של סדר הלשוניות הגמיש.

        כיבוי מחזיר את הלשוניות לסדר ברירת המחדל ומוחק את הסדר השמור — כלומר
        חוזרים בדיוק לעיצוב הקבוע שהיה קודם."""
        self._flex_tabs = bool(on)
        theme.save_flexible_tabs(self._flex_tabs)
        self.tabs.tabBar().setMovable(self._flex_tabs)
        if self._flex_tabs:
            self._save_current_tab_order()
        else:
            theme.clear_tab_order()
            self._restore_default_tab_order()

    def _save_current_tab_order(self):
        """שומר את הסדר הנוכחי (לפי טקסט הלשונית) — לשחזור בהפעלה הבאה."""
        theme.save_tab_order([self.tabs.tabText(i) for i in range(self.tabs.count())])

    def _restore_default_tab_order(self):
        """מחזיר את הלשוניות לסדר ברירת המחדל (העיצוב הקבוע)."""
        bar = self.tabs.tabBar()
        current = self.tabs.currentWidget()
        self._reordering = True
        try:
            for i, w in enumerate(getattr(self, "_default_tab_order", [])):
                j = self.tabs.indexOf(w)
                if j not in (-1, i):
                    bar.moveTab(j, i)
        finally:
            self._reordering = False
        if current is not None:
            self.tabs.setCurrentWidget(current)
        self._mark_branch_tabs()

    def _apply_saved_tab_order(self):
        """מחיל סדר שמור (לפי טקסט הלשונית); לשונית שאינה בסדר השמור נשארת בסוף."""
        saved = theme.load_tab_order()
        if not saved:
            return
        rank = {t: i for i, t in enumerate(saved)}
        widgets = sorted(
            ((rank.get(self.tabs.tabText(i), len(saved) + i), self.tabs.widget(i))
             for i in range(self.tabs.count())),
            key=lambda pair: pair[0])
        bar = self.tabs.tabBar()
        current = self.tabs.currentWidget()
        self._reordering = True
        try:
            for i, (_key, w) in enumerate(widgets):
                j = self.tabs.indexOf(w)
                if j not in (-1, i):
                    bar.moveTab(j, i)
        finally:
            self._reordering = False
        if current is not None:
            self.tabs.setCurrentWidget(current)
        self._mark_branch_tabs()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "tabs"):
            self._apply_equal_tab_widths()

    def _set_theme(self, on: bool):
        if on == self.dark:
            return
        self.dark = on
        theme.save_dark(on)
        theme.apply_theme(on)
        self._recolor_tables()
        self._say("info", "עיצוב כהה הופעל" if on else "עיצוב כחול עמוק הופעל")

        self._mtk_color = theme.mtk_color
        self._warn_color = theme.warn_color

    def _recolor_tables(self):
        self._refresh_ports()
        self._refresh_bank()
        if self.gpt:
            self._fill_partition_table(self.gpt)

    # ------------------------------------------------------------ לשונית זיהוי
    def _scrollable(self, inner: QWidget) -> QWidget:
        """עוטף לשונית באזור גלילה: כשאין מספיק גובה — גוללים,
        במקום שהחלקים יעלו אחד על השני."""
        from PySide6.QtWidgets import QScrollArea
        if isinstance(inner, QScrollArea):
            return inner   # כבר עטופה
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(inner)
        return sa

    def _tab_device(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        gb = QGroupBox("פורטים מחוברים (ניטור חי)")
        gv = QVBoxLayout(gb)
        self.ports_table = QTableWidget(0, 5)
        self.ports_table.setHorizontalHeaderLabels(["פורט", "תיאור", "מצב", "VID", "PID"])
        self.ports_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ports_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ports_table.setMinimumHeight(95)
        self.ports_table.setMaximumHeight(130)
        # מצמצם גם את הרוחב: הטבלה לא נמתחת על כל השורה — נותרים שוליים צדדיים
        ports_wrap = QHBoxLayout()
        ports_wrap.setContentsMargins(48, 0, 48, 0)   # ~שלושת רבעי הרוחב בפועל
        ports_wrap.addWidget(self.ports_table, 1)
        gv.addLayout(ports_wrap)
        btns = QHBoxLayout()
        refresh_btn = QPushButton("🔄 רענן עכשיו")
        refresh_btn.setToolTip("הטבלה מתעדכנת אוטומטית; השתמש רק אם נראה שהיא לא התעדכנה")
        refresh_btn.clicked.connect(self._refresh_ports)
        # גובה מוקטן בכשליש (הרוחב נשמר — ריווח אופקי לא משתנה)
        refresh_btn.setMaximumHeight(28)
        refresh_btn.setStyleSheet(
            "QPushButton { min-height: 16px; padding-top: 2px; padding-bottom: 2px; }")
        btns.addWidget(refresh_btn)
        btns.addStretch(1)
        gv.addLayout(btns)

        gb2 = QGroupBox("זיהוי מכשיר (דורש חיבור מכשיר במצב BROM/Preloader)")
        g2 = QVBoxLayout(gb2)
        brom_help = QLabel(
            "<b>חיבור המכשיר במצב BROM/Preloader:</b><br>"
            "כבה את המכשיר לגמרי, ואז באחת מהדרכים:<br>"
            "• חבר בכבל USB תוך כדי החזקת <b>Volume Down</b> "
            "(או <b>Volume Up</b> — תלוי במכשיר).<br>"
            "• או: חבר כשהוא כבוי; אם לא זוהה — החזק את <b>לחצן ההפעלה כ-10 שניות "
            "תוך כדי החיבור</b>, והוא יתאפס ויזוהה אוטומטית.")
        brom_help.setWordWrap(True)
        brom_help.setStyleSheet(
            "QLabel { border: 1px solid #2f81f7; border-radius: 6px; padding: 8px;"
            " background-color: rgba(47,129,247,0.08); }")
        g2.addWidget(brom_help)
        gpt_row = QHBoxLayout()
        btn_gpt = QPushButton("קרא GPT\u200f (printgpt)\u200f")
        btn_gpt.clicked.connect(self._read_gpt)
        gpt_row.addWidget(btn_gpt)
        gpt_row.addWidget(self._help_dot("gpt"))
        gpt_row.addStretch(1)
        g2.addLayout(gpt_row)
        v.addWidget(gb2)

        gb3 = QGroupBox("דרייברים")
        g3 = QHBoxLayout(gb3)
        btn_install = QPushButton("⚙️ התקנת דרייבר UsbDk (מתוך התוכנה)")
        btn_install.clicked.connect(self._install_usbdk)
        btn_install_vcom = QPushButton("⚙️ התקנת דרייבר MediaTek VCOM (מתוך התוכנה)")
        btn_install_vcom.clicked.connect(self._install_mtk_vcom)

        def _small_dl(tip: str, slot):
            b = QPushButton("\u2002הורדה")   # רווח (en space) בין סמל הכדור למילה
            b.setIcon(guiicons.globe_icon())
            b.setIconSize(QSize(16, 16))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        btn_dl_usbdk = _small_dl("הורדה מהאתר הרשמי של UsbDk\u200f (GitHub — Daynix)\u200f",
                                 lambda: QDesktopServices.openUrl(QUrl(_USBDK_URL)))
        btn_link = _small_dl("הורדת דרייברי MediaTek VCOM\u200f (mtkdriver.com)\u200f",
                             self._open_drivers_link)
        btn_check = QPushButton("🩺 בדיקת מצב הדרייברים")
        btn_check.setToolTip("בודק אם הדרייברים MediaTek VCOM/PreLoader ו-UsbDk "
                             "מותקנים במחשב (קריאה בלבד).")
        btn_check.clicked.connect(lambda: self._check_drivers("mtk"))
        # כל הכפתורים בשורת הדרייברים — קטנים ב-7.5% מהגודל הרגיל של הכפתורים, אחיד לכולם.
        # (גודל הכפתורים נקבע בגיליון הסגנון של התוכנה, ולכן ההקטנה נעשית גם היא בגיליון.)
        _base_pt = QApplication.instance().font().pointSizeF()
        _base_pt = _base_pt if _base_pt > 0 else 9.0
        _drv_pt = round(_base_pt * theme.BUTTON_SCALE * 0.925, 2)
        btn_fix = self._fix_driver_button()
        for _b in (btn_install, btn_dl_usbdk, btn_install_vcom, btn_link, btn_check, btn_fix):
            _b.setStyleSheet(f"QPushButton {{ font-size: {_drv_pt}pt; }}")
        g3.addWidget(btn_install)
        g3.addWidget(btn_dl_usbdk)
        g3.addSpacing(12)
        g3.addWidget(btn_install_vcom)
        g3.addWidget(btn_link)
        g3.addSpacing(12)
        g3.addWidget(btn_check)
        g3.addWidget(btn_fix)
        g3.addStretch(1)
        v.addWidget(gb3)
        # ---- זיהוי סביבת פייתון (בדיקה בלבד)
        gbp = QGroupBox("סביבת פייתון (בשביל mtkclient)")
        vp = QVBoxLayout(gbp)
        self.pyenv_text = QTextEdit()
        self.pyenv_text.setReadOnly(True)
        self.pyenv_text.setMinimumHeight(140)
        self.pyenv_text.setMaximumHeight(200)
        self.pyenv_text.setPlaceholderText("לא נבדק עדיין…")
        vp.addWidget(self.pyenv_text)
        py_row = QHBoxLayout()
        b_py = QPushButton("🔍 זהה סביבת פייתון")
        b_py.clicked.connect(self._detect_pyenv)
        py_row.addWidget(b_py)
        # "התקן פייתון" — ליד כפתור הזיהוי ובאותו סגנון; מסגרת אדומה רק כשפייתון חסר
        self.btn_install_python = QPushButton("⬇️ הורדת פייתון להתקנה")
        self.btn_install_python.setToolTip(
            "פותח בדפדפן את דף ההורדה הרשמי של פייתון לווינדוס – את ההתקנה עצמה מבצעים לבד.")
        self.btn_install_python.clicked.connect(self._open_python_download)
        self._style_install_python(alert=False)
        py_row.addWidget(self.btn_install_python)
        self.btn_auto_python = QPushButton("⚙️ התקן פייתון וספריות ל-mtkclient (אוטומטי)")
        self.btn_auto_python.setToolTip(
            "מוריד ומתקין את פייתון הרשמי עם PATH מסומן, ואת כל הספריות ש-mtkclient צריך — "
            "בלי שאלות ובלי הרשאת מנהל. אם פייתון כבר מותקן — מתקין רק את הספריות.")
        self.btn_auto_python.clicked.connect(self._auto_install_python)
        py_row.addWidget(self.btn_auto_python)
        b_portable = QPushButton("⬇️ הורדת פייתון נייד\u200f (MTKClient Portable)\u200f")
        b_portable.setToolTip("פותח בדפדפן את הקובץ MTKCliantPortable.zip ב-Google Drive — "
                              "mtkclient עם פייתון נייד, בלי התקנה. אחרי ההורדה מחלצים את הקובץ.")
        b_portable.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(_MTK_PORTABLE_URL)))
        py_row.addWidget(b_portable)
        py_row.addStretch(1)
        vp.addLayout(py_row)
        v.addWidget(gbp)

        # ניטור חי לפורטים — למטה, מתחת לפייתון (לבקשת המשתמש)
        v.addWidget(gb)

        v.addStretch(1)
        return self._scrollable(w)   # גלילה במקום "מעיכה" של החלקים

    # ------------------------------------------------------------ לשונית Scatter
    def _tab_scatter(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        gb = QGroupBox("יצירת קובצי Scatter מטבלת ה-GPT")
        gv = QVBoxLayout(gb)
        form = QFormLayout()
        self.chip_edit = QLineEdit()
        self.chip_edit.setPlaceholderText("MT6580")
        self.chip_edit.setToolTip(
            "שם המעבד (platform). מתמלא אוטומטית כשקוראים GPT — MT6580 וכדומה. "
            "שם זה נכתב לתוך ה-Scatter וגם לשם הקובץ, ולכן הוא חובה.")
        self.chip_edit.editingFinished.connect(self._suggest_block_size)
        form.addRow("דגם צ'יפ (platform):", self.chip_edit)
        self.block_size_edit = QLineEdit(f"0x{DEFAULT_BLOCK_SIZE:x}")
        self.block_size_edit.setToolTip(
            "גודל הגוש המוצהר ב-Scatter. מתעדכן אוטומטית לפי המעבד: "
            "מעבדים ישנים (MT65xx, MT6735/37/53) — 0x20000, מודרניים — 0x200000. "
            "אם יש לך Scatter מקורי של המכשיר — העדף את הערך שבו.")
        form.addRow("block_size:", self.block_size_edit)
        gv.addLayout(form)

        b1 = QPushButton("צור Scatter מלא (כל המחיצות)")
        b1.setToolTip(
            "Scatter מלא ל-SP Flash Tool: preloader\u200f (EMMC_BOOT_1)\u200f + pgpt + כל מחיצות "
            "ה-GPT + sgpt.\nהקובץ נשמר בשם Android_scatter_<שם המעבד>.txt.")
        b1.clicked.connect(self._gen_scatter_full)
        btns = QHBoxLayout()
        btns.addWidget(b1)
        btns.addStretch(1)
        gv.addLayout(btns)
        self.bank_on_generate = QCheckBox("שמור אוטומטית גם ל'בנק סקטארים' תחת שם המעבד")
        self.bank_on_generate.setChecked(True)
        gv.addWidget(self.bank_on_generate)
        v.addWidget(gb)

        gb2 = QGroupBox("בדיקת קובץ Scatter")
        g2 = QVBoxLayout(gb2)
        form2 = QFormLayout()
        row = QHBoxLayout()
        self.scatter_path_edit = QLineEdit()
        btn_browse = QPushButton("…")
        btn_browse.setMaximumWidth(52)
        btn_browse.clicked.connect(self._browse_scatter)
        row.addWidget(self.scatter_path_edit)
        row.addWidget(btn_browse)
        form2.addRow("קובץ Scatter:", row)
        g2.addLayout(form2)
        btns2 = QHBoxLayout()
        b_val = QPushButton("✅ אמת תקינות ל-SP Flash")
        b_val.clicked.connect(self._validate_scatter_file)
        b_prev = QPushButton("👁️ תצוגה מקדימה")
        b_prev.clicked.connect(self._preview_scatter_file)
        btns2.addWidget(b_val)
        btns2.addWidget(b_prev)
        btns2.addStretch(1)
        g2.addLayout(btns2)
        v.addWidget(gb2)
        v.addStretch(1)
        return w

    def _suggest_block_size(self):
        chip = self.chip_edit.text().strip()
        if chip and not is_placeholder_chip(chip):
            self.block_size_edit.setText(f"0x{default_block_size(chip):x}")

    def _browse_scatter(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר קובץ Scatter", str(config.SCATTER_DIR),
            "Scatter files (*.txt);;All files (*)")
        if path:
            self.scatter_path_edit.setText(path)

    def _current_scatter_path(self) -> Path | None:
        p = self.scatter_path_edit.text().strip()
        if not p:
            QMessageBox.warning(self, "חסר קובץ", "בחר קובץ Scatter קודם")
            return None
        return Path(p)

    def _validate_scatter_file(self):
        path = self._current_scatter_path()
        if not path:
            return
        problems = validate_scatter(path)
        if not problems:
            self._say("success", f"הקובץ תקין ל-SP Flash: {path.name}")
            QMessageBox.information(self, "תקין",
                                    f"הקובץ עבר את כל הבדיקות ונראה תקין ל-SP Flash Tool:\n{path}")
            return
        self._say("error", f"נמצאו {len(problems)} בעיות בקובץ")
        for pr in problems:
            self._say("warning", f"  • {pr}")
        QMessageBox.warning(self, "נמצאו בעיות",
                            "הקובץ אינו תקין:\n\n" + "\n".join(f"• {p}" for p in problems))

    def _preview_scatter_file(self):
        path = self._current_scatter_path()
        if not path or not path.is_file():
            QMessageBox.warning(self, "קובץ חסר", "הקובץ לא נמצא")
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            QMessageBox.critical(self, "שגיאה", f"קריאה נכשלה: {e}")
            return
        dlg = QMessageBox(self)
        dlg.setWindowTitle(f"תצוגה מקדימה: {path.name}")
        dlg.setText(f"{path}")
        dlg.setDetailedText(text)
        dlg.exec()

    # ------------------------------------------------------------ לשונית בנק סקטארים
    def _tab_scatter_bank(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        back_row = QHBoxLayout()
        b_back = QPushButton("🔙 חזור לתוכנה")
        b_back.setToolTip("סגירת בנק הסקטארים וחזרה ללשוניות התוכנה")
        b_back.clicked.connect(self._bank_back)
        back_row.addWidget(b_back)
        back_row.addStretch(1)
        v.addLayout(back_row)
        info = QLabel(
            "כאן נשמרים קובצי Scatter שהתוכנה יצרה או שהזנת ידנית, מאורגנים "
            "לפי מעבד או מכשיר. אפשר גם פשוט להעתיק קבצים ידנית לתיקיות שבבנק "
            "וללחוץ רענון.")
        info.setWordWrap(True)
        v.addWidget(info)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("מעבד / מכשיר:"))
        self.bank_group_combo = QComboBox()
        self.bank_group_combo.addItem("הצג הכל", "")
        self.bank_group_combo.currentIndexChanged.connect(self._refresh_bank)
        filter_row.addWidget(self.bank_group_combo, 1)
        b_refresh = QPushButton("🔄 רענון")
        b_refresh.clicked.connect(self._refresh_bank)
        filter_row.addWidget(b_refresh)
        v.addLayout(filter_row)

        self.bank_table = QTableWidget(0, 5)
        self.bank_table.setHorizontalHeaderLabels(
            ["שם קובץ", "מעבד", "מכשיר", "מקור", "תאריך"])
        self.bank_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.bank_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.bank_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.bank_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        v.addWidget(self.bank_table, 1)

        # מפריד עדין מעל שורת התחתית — כמו מד ההתקדמות בתחתית החלון
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        v.addWidget(sep)

        # שורת תחתית (בגובה שורת סטטוס המכשיר): הכפתורים בצד אחד,
        # סיכום הבנק בצד השני — בלי שורה שלמה משלהם
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 2, 0, 0)
        for text, slot in (("📥 ייבא קובץ Scatter", self._bank_import),
                           ("👁️ הצג תוכן", self._bank_preview),
                           ("📁 העבר לקבוצה", self._bank_move),
                           ("✏️ שנה שם", self._bank_rename),
                           ("🗑️ מחק", self._bank_delete),
                           ("📂 פתח תיקיית הבנק", self._bank_open_folder)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bottom.addWidget(b)
        bottom.addStretch(1)   # ב-RTL — הסיכום יידחף לצד השני של הכפתורים
        self.bank_summary = QLabel()
        self.bank_summary.setWordWrap(True)
        bottom.addWidget(self.bank_summary, 1)
        v.addLayout(bottom)
        self._refresh_bank()
        return w

    def _refresh_bank(self):
        current = self.bank_group_combo.currentData()
        entries = scatter_bank.list_entries(current or None)
        self.bank_table.setRowCount(0)
        self._bank_entries = entries
        for e in entries:
            row = self.bank_table.rowCount()
            self.bank_table.insertRow(row)
            cpu = e.cpu or e.group      # ישן/ידני: התיקייה היא בד"כ שם המעבד
            dev = e.device or "—"       # רק שם מכשיר שמולא במפורש — אחרת ריק
            for col, val in enumerate([e.name, cpu, dev, e.source_label, e.modified_str]):
                self.bank_table.setItem(row, col, QTableWidgetItem(str(val)))

        self.bank_group_combo.blockSignals(True)
        keep = self.bank_group_combo.currentData()
        self.bank_group_combo.clear()
        self.bank_group_combo.addItem("הצג הכל", "")
        for g in scatter_bank.groups():
            self.bank_group_combo.addItem(g, g)
        idx = self.bank_group_combo.findData(keep)
        if idx >= 0:
            self.bank_group_combo.setCurrentIndex(idx)
        self.bank_group_combo.blockSignals(False)

        st = scatter_bank.stats()
        self.bank_summary.setText(
            f"סה\"כ {st['total']} קבצים | נוצרו בתוכנה: {st['generated']} | "
            f"הוזנו ידנית: {st['manual']} | קבוצות: {st['groups']}\nמיקום: {st['root']}")

    def _selected_bank_entry(self):
        row = self.bank_table.currentRow()
        if row < 0 or row >= len(getattr(self, "_bank_entries", [])):
            QMessageBox.warning(self, "בחירה חסרה", "בחר קובץ מהרשימה")
            return None
        return self._bank_entries[row]

    def _bank_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר קובץ Scatter", "", "Scatter files (*.txt *.scatter *.cfg);;All files (*)")
        if not path:
            return
        group, ok = QInputDialog.getText(self, "קבוצת יעד",
                                         "שם מעבד או מכשיר (למשל MT6765 או Redmi_9A):")
        if not ok or not group.strip():
            return
        try:
            entry = scatter_bank.import_file(Path(path), group.strip())
        except (OSError, FileNotFoundError) as e:
            QMessageBox.critical(self, "שגיאה", f"הייבוא נכשל: {e}")
            return
        self._say("success", f"נוסף לבנק: {entry.group}/{entry.name}")
        self._refresh_bank()

    def _bank_preview(self):
        entry = self._selected_bank_entry()
        if not entry:
            return
        dlg = QMessageBox(self)
        dlg.setWindowTitle(f"תצוגה: {entry.name}")
        dlg.setText(f"קבוצה: {entry.group}  |  מקור: {entry.source_label}")
        dlg.setDetailedText(scatter_bank.read_entry_text(entry))
        dlg.exec()

    def _bank_move(self):
        entry = self._selected_bank_entry()
        if not entry:
            return
        group, ok = QInputDialog.getText(self, "העברה לקבוצה", "שם מעבד או מכשיר חדש:",
                                         text=entry.group)
        if not ok or not group.strip():
            return
        try:
            scatter_bank.move_to_group(entry, group.strip())
        except OSError as e:
            QMessageBox.critical(self, "שגיאה", f"ההעברה נכשלה: {e}")
            return
        self._say("info", f"הועבר לקבוצה: {group.strip()}")
        self._refresh_bank()

    def _bank_rename(self):
        entry = self._selected_bank_entry()
        if not entry:
            return
        name, ok = QInputDialog.getText(self, "שינוי שם", "שם קובץ חדש:", text=entry.name)
        if not ok or not name.strip():
            return
        try:
            scatter_bank.rename_entry(entry, name.strip())
        except (OSError, FileExistsError) as e:
            QMessageBox.critical(self, "שגיאה", f"השינוי נכשל: {e}")
            return
        self._refresh_bank()

    def _bank_delete(self):
        entry = self._selected_bank_entry()
        if not entry:
            return
        if QMessageBox.question(self, "מחיקה", f"למחוק מהבנק:\n{entry.group}/{entry.name}?",
                                _YES | _NO, _NO) != _YES:
            return
        scatter_bank.delete_entry(entry)
        self._say("warning", f"נמחק מהבנק: {entry.name}")
        self._refresh_bank()

    def _bank_open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(scatter_bank.bank_root())))

    def _bank_back(self):
        """חזרה מבנק הסקטארים אל לשוניות התוכנה."""
        if getattr(self, "_bank_active", False):
            self._toggle_bank_view()

    # ------------------------------------------------------------ לשונית שאיבה
    def _tab_readback(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        gb = QGroupBox("מחיצות (מה-GPT) — סמן את המחיצות לשאיבה")
        gv = QVBoxLayout(gb)
        self.part_list = QTableWidget(0, 4)
        self.part_list.setHorizontalHeaderLabels(["✔", "מחיצה", "התחלה", "גודל"])
        hh = self.part_list.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.part_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.part_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.part_list.itemChanged.connect(self._update_selection_label)
        self.part_list.cellClicked.connect(self._toggle_row_check)
        gv.addWidget(self.part_list)

        sel_row = QHBoxLayout()
        b_all = QPushButton("☑ סמן הכל")
        b_all.clicked.connect(lambda: self._set_all_checks(True))
        b_none = QPushButton("☐ נקה סימון")
        b_none.clicked.connect(lambda: self._set_all_checks(False))
        self.sel_label = QLabel("לא סומנו מחיצות")
        sel_row.addWidget(b_all)
        sel_row.addWidget(b_none)
        sel_row.addWidget(self.sel_label, 1)
        gv.addLayout(sel_row)

        btns = QHBoxLayout()
        btn_dump_gpt = QPushButton("טען GPT לרשימה")
        btn_dump_gpt.setObjectName("btnSoft")
        btn_dump_gpt.clicked.connect(self._read_gpt)
        self.btn_read_sel = QPushButton(" שאב מחיצות מסומנות")
        self.btn_read_sel.setObjectName("btnSoft")   # בקשת המשתמש: ניטרלי בגוון הרקע
        self.btn_read_sel.setIcon(self.icon_read)
        self.btn_read_sel.clicked.connect(self._read_checked)
        btn_read_pre = QPushButton("שאב Preloader")
        btn_read_pre.setObjectName("btnSoft")
        btn_read_pre.clicked.connect(self._read_preloader)
        btn_read_all = QPushButton("שאב את כל המחיצות (rl)")
        btn_read_all.setObjectName("btnSoft")
        btn_read_all.clicked.connect(self._read_all)
        btn_open = QPushButton("📂 פתח תיקיית שאיבות")
        btn_open.setObjectName("btnSoft")
        btn_open.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(config.DUMPS_DIR))))
        for b, hk in ((btn_dump_gpt, "gpt"), (self.btn_read_sel, "readback"),
                      (btn_read_pre, "readback"), (btn_read_all, "readback"),
                      (btn_open, None)):
            btns.addWidget(b)
            if hk:
                btns.addWidget(self._help_dot(hk))
        gv.addLayout(btns)
        v.addWidget(gb)

        # גיבוי NVRAM/NVDATA — הועבר לכאן מלשונית תחזוקת התקשורת (שהוסרה)
        gb_nv = QGroupBox("גיבוי NVRAM / NVDATA (IMEI, MAC, כיול)")
        nv = QHBoxLayout(gb_nv)
        b_nv = QPushButton(" גבה NVRAM + NVDATA")
        b_nv.setObjectName("btnSoft")
        b_nv.setIcon(self.icon_read)
        b_nv.clicked.connect(self._backup_nvram)
        nv.addWidget(b_nv)
        nv.addWidget(self._help_dot("readback"))
        nv.addStretch(1)
        v.addWidget(gb_nv)
        return w

    def _fill_partition_table(self, table: GptTable):
        checked = set(self._checked_partitions()) if self.part_list.rowCount() else set()
        self.part_list.blockSignals(True)
        self.part_list.setRowCount(0)
        for p in table.partitions:
            row = self.part_list.rowCount()
            self.part_list.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked if p.name in checked else Qt.CheckState.Unchecked)
            self.part_list.setItem(row, 0, chk)
            name_item = QTableWidgetItem(p.name)
            if get_partition_warning(p.name):
                name_item.setForeground(self._warn_color())
                name_item.setToolTip(get_partition_warning(p.name))
            self.part_list.setItem(row, 1, name_item)
            self.part_list.setItem(row, 2, QTableWidgetItem(f"0x{p.offset:08x}"))
            self.part_list.setItem(row, 3, QTableWidgetItem(format_size(p.length)))
        self.part_list.blockSignals(False)
        self._update_selection_label()

    def _toggle_row_check(self, row: int, col: int):
        if col == 0:
            return  # לחיצה על התיבה עצמה מטופלת ע"י Qt
        item = self.part_list.item(row, 0)
        if item:
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                               else Qt.CheckState.Checked)

    def _set_all_checks(self, on: bool):
        self.part_list.blockSignals(True)
        for r in range(self.part_list.rowCount()):
            self.part_list.item(r, 0).setCheckState(
                Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.part_list.blockSignals(False)
        self._update_selection_label()

    def _checked_partitions(self) -> list[str]:
        out = []
        for r in range(self.part_list.rowCount()):
            it = self.part_list.item(r, 0)
            if it and it.checkState() == Qt.CheckState.Checked:
                out.append(self.part_list.item(r, 1).text())
        return out

    def _update_selection_label(self, *_):
        names = self._checked_partitions()
        if not names:
            self.sel_label.setText("לא סומנו מחיצות")
            self.btn_read_sel.setText("שאב מחיצות מסומנות")
            return
        total = sum(p.length for n in names if self.gpt and (p := self.gpt.get(n)))
        self.sel_label.setText(f"סומנו {len(names)} מחיצות · סה\"כ {format_size(total)}")
        self.btn_read_sel.setText(f"שאב מחיצות מסומנות ({len(names)})")

    # ------------------------------------------------------------ לשונית צריבה
    def _tab_flash(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        gb = QGroupBox("צריבת Image למחיצה")
        form = QFormLayout()
        img_row = QHBoxLayout()
        self.image_edit = QLineEdit()
        btn_browse = QPushButton("…")
        btn_browse.setMaximumWidth(52)
        btn_browse.clicked.connect(self._browse_image)
        img_row.addWidget(self.image_edit)
        img_row.addWidget(btn_browse)
        form.addRow("קובץ Image:", img_row)
        self.part_combo = QComboBox()
        form.addRow("מחיצת יעד:", self.part_combo)
        self.backup_check = QCheckBox("גיבוי אוטומטי של המחיצה לפני צריבה (מומלץ)")
        self.backup_check.setChecked(True)
        form.addRow(self.backup_check)
        flash_row = QHBoxLayout()
        btn_flash = QPushButton(" צרב")
        btn_flash.setObjectName("btnDanger")   # צריבה — כפתור אדום גדול (כמו Download ב-SP Flash)
        btn_flash.setIcon(self.icon_flash)
        btn_flash.clicked.connect(self._flash_image)
        flash_row.addWidget(btn_flash)
        flash_row.addWidget(self._help_dot("flash"))
        flash_row.addStretch(1)
        form.addRow(flash_row)
        gb.setLayout(form)
        v.addWidget(gb)

        gb2 = QGroupBox("מידע")
        v2 = QVBoxLayout(gb2)
        info = QLabel(
            "סדר הפעולה: אימות גודל ← גיבוי המחיצה הקיימת (+SHA256) אל workspace\\backups ← צריבה.\n"
            "אם הגיבוי נכשל — הצריבה לא מתבצעת.\n"
            "מצבי SP Flash\u200f (Download Only / Format All)\u200f — בתכנון.")
        info.setWordWrap(True)
        v2.addWidget(info)
        v.addWidget(gb2)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------ לשונית Bootloader
    def _tab_bootloader(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        gb = QGroupBox("פתיחה / נעילה של בוטלאודר (לפי ערוץ התקשורת)")
        gv = QVBoxLayout(gb)
        lbl = QLabel(
            "הכפתורים פועלים לפי ערוץ התקשורת הפעיל: mtkclient\u200f (seccfg)\u200f · Fastboot\u200f (flashing)\u200f · "
            "ADB (מעביר אוטומטית ל-Fastboot).\n"
            "⚠️ פתיחת ה-Bootloader\u200f (Unlock)\u200f מוחקת את כל הנתונים מהמכשיר — תמונות, אפליקציות, "
            "הגדרות וכל נתוני המשתמש. ודא שיש לך גיבוי לפני שימוש!")
        lbl.setWordWrap(True)
        gv.addWidget(lbl)
        btns = QHBoxLayout()
        btn_unlock = QPushButton("🔓 Unlock")
        btn_unlock.clicked.connect(lambda: self._bootloader_change_router(True))
        btn_lock = QPushButton("🔒 Lock")
        btn_lock.clicked.connect(lambda: self._bootloader_change_router(False))
        btns.addWidget(btn_unlock)
        btns.addWidget(self._help_dot("seccfg"))
        btns.addWidget(btn_lock)
        btns.addStretch(1)
        gv.addLayout(btns)
        v.addWidget(gb)

        gb2 = QGroupBox("מצב אבטחה / בוטלאודר (קריאה בלבד — לפי ערוץ התקשורת)")
        g2 = QVBoxLayout(gb2)
        info = QLabel(
            "בודק את מצב הבוטלאודר לפי ערוץ התקשורת הפעיל: ADB\u200f (getprop)\u200f · Fastboot\u200f (getvar)\u200f · "
            "mtkclient\u200f (gettargetconfig)\u200f. קריאה בלבד — לא משנה כלום במכשיר.")
        info.setWordWrap(True)
        g2.addWidget(info)
        self.boot_status = QTextEdit()
        self.boot_status.setReadOnly(True)
        self.boot_status.setPlaceholderText(
            "לא נבדק עדיין. חבר מכשיר במצב BROM/Preloader ולחץ 'בדוק מצב אבטחה'.")
        self.boot_status.setMaximumHeight(150)
        g2.addWidget(self.boot_status)
        sec_row = QHBoxLayout()
        b_check = QPushButton("🔍 בדוק מצב אבטחה / בוטלאודר")
        b_check.clicked.connect(self._bootloader_check_router)
        sec_row.addWidget(b_check)
        sec_row.addWidget(self._help_dot("security"))
        sec_row.addStretch(1)
        g2.addLayout(sec_row)
        v.addWidget(gb2)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------ לשונית Fastboot
    def _tab_fastboot(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        # דרייברים למצב Fastboot (קישורים — יוחלפו בעתיד בלינקים סופיים)
        gdrv = QGroupBox("דרייברים למצב Fastboot")
        dv = QVBoxLayout(gdrv)
        drv_note = QLabel(
            "אם המכשיר לא מזוהה במצב Fastboot — התקן את דרייבר "
            "'Android Bootloader Interface' של Google:")
        drv_note.setWordWrap(True)
        dv.addWidget(drv_note)
        drv_row = QHBoxLayout()
        b_drv_install = QPushButton("⚙️ התקנת דרייבר Fastboot (מתוך התוכנה)")
        b_drv_install.setToolTip("מתקין את הדרייבר מהתיקייה tools\\fastboot_driver "
                                 "(נדרשת הרשאת מנהל)")
        b_drv_install.clicked.connect(lambda: self._install_android_drivers("Fastboot"))
        drv_row.addWidget(b_drv_install)
        b_drv_goog = QPushButton("⬇️ הורדת דרייבר Fastboot")
        b_drv_goog.setToolTip("הדרייבר הרשמי של Google\u200f (Google USB Driver)\u200f")
        b_drv_goog.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://developer.android.com/studio/run/win-usb")))
        b_drv_check = QPushButton("🩺 בדיקת דרייבר Fastboot")
        b_drv_check.setToolTip("בדיקה קריאה-בלבד: האם דרייבר Android Bootloader "
                               "Interface מותקן במחשב הזה")
        b_drv_check.clicked.connect(lambda: self._check_drivers("fastboot"))
        drv_row.addWidget(b_drv_goog)
        drv_row.addWidget(b_drv_check)
        drv_row.addWidget(self._fix_driver_button())
        drv_row.addStretch(1)
        dv.addLayout(drv_row)
        # מיקום הנושא בלשונית נקבע בהמשך (התוספות בסוף) — "דרייברים" ירד לתחתית.
        # נושא 'כלי Fastboot' (בחירת fastboot.exe) הוסר: הכלי ארוז בתוכנה ומזוהה לבד

        # זיהוי ומידע
        gb1 = QGroupBox("זיהוי ומידע (קריאה בלבד)")
        g1 = QVBoxLayout(gb1)
        note = QLabel(
            "המכשיר חייב להיות במצב Fastboot, ודרייבר 'Android Bootloader Interface' "
            "מותקן. אחרת המכשיר לא יזוהה.")
        note.setWordWrap(True)
        g1.addWidget(note)
        # זיהוי אוטומטי: שם המכשיר ומצב הבוטלאודר מתעדכנים לבד כשמכשיר ב-Fastboot מחובר
        self.fb_auto_label = QLabel("לא מחובר מכשיר ב-Fastboot")
        self.fb_auto_label.setWordWrap(True)
        _f = self.fb_auto_label.font()
        _f.setBold(True)
        self.fb_auto_label.setFont(_f)
        g1.addWidget(self.fb_auto_label)
        rowd = QHBoxLayout()
        b_dev = QPushButton("🔎 זהה מכשיר (devices)")
        b_dev.clicked.connect(self._fb_detect)
        b_info = QPushButton("ℹ️ מידע ומצב נעילה (getvar all)")
        b_info.clicked.connect(self._fb_info)
        rowd.addWidget(b_dev)
        rowd.addWidget(self._help_dot("fb_detect"))
        rowd.addWidget(b_info)
        rowd.addWidget(self._help_dot("fb_info"))
        b_fb_help = QPushButton("❓ הוראות Fastboot")
        b_fb_help.clicked.connect(lambda: self._show_mode_instructions("fastboot"))
        rowd.addWidget(b_fb_help)
        rowd.addStretch(1)
        g1.addLayout(rowd)
        self.fb_status = QTextEdit()
        self.fb_status.setReadOnly(True)
        self.fb_status.setPlaceholderText("לא נבדק עדיין.")
        g1.addWidget(self.fb_status)
        v.addWidget(gb1)

        # צריבה / מחיקה
        gb2 = QGroupBox("צריבה / מחיקה (דורש בוטלאודר פתוח)")
        form = QFormLayout()
        img_row = QHBoxLayout()
        self.fb_image_edit = QLineEdit()
        b_browse = QPushButton("…")
        b_browse.setMaximumWidth(52)
        b_browse.clicked.connect(self._fb_browse_image)
        img_row.addWidget(self.fb_image_edit)
        img_row.addWidget(b_browse)
        form.addRow("קובץ Image:", img_row)
        self.fb_part_edit = QLineEdit()
        self.fb_part_edit.setPlaceholderText("boot / recovery / vbmeta / …")
        form.addRow("שם מחיצה:", self.fb_part_edit)
        rowf = QHBoxLayout()
        b_flash = QPushButton("🔥 צרב (flash)")
        b_flash.setObjectName("btnDanger")
        b_flash.clicked.connect(self._fb_flash)
        b_erase = QPushButton("🗑️ מחק (erase)")
        b_erase.setObjectName("btnWarn")
        b_erase.clicked.connect(self._fb_erase)
        rowf.addWidget(b_flash)
        rowf.addWidget(self._help_dot("fb_flash"))
        rowf.addWidget(b_erase)
        rowf.addWidget(self._help_dot("fb_erase"))
        rowf.addStretch(1)
        gb2.setLayout(form)
        v.addWidget(gb2)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addLayout(rowf)
        v.addWidget(wrap)

        # אתחול
        gb3 = QGroupBox("אתחול")
        g3 = QHBoxLayout(gb3)
        b_rb = QPushButton("🔄 הפעל מחדש (מערכת)")
        b_rb.clicked.connect(lambda: self._fb_reboot(""))
        b_rbl = QPushButton("🚀 עבור למצב Fastboot")
        b_rbl.setToolTip("מפעיל מחדש את המכשיר לתוך מצב ה-Bootloader\u200f (Fastboot)\u200f")
        b_rbl.clicked.connect(lambda: self._fb_reboot("bootloader"))
        g3.addWidget(b_rb)
        g3.addWidget(self._help_dot("fb_reboot"))
        g3.addWidget(b_rbl)
        g3.addWidget(self._help_dot("fb_reboot_bl"))
        g3.addStretch(1)
        v.addWidget(gb3)

        # "דרייברים למצב Fastboot" — בסוף הלשונית (לבקשת המשתמש)
        v.addWidget(gdrv)
        v.addStretch(1)

        return w

    def _fb_browse_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר Image", "", "Image files (*.img *.bin);;All files (*)")
        if path:
            self.fb_image_edit.setText(path)

    def _fb_guard(self) -> bool:
        if not config.fastboot_available():
            QMessageBox.warning(self, "אין fastboot",
                                "fastboot.exe לא נמצא. ודא שקובץ fastboot.exe נמצא "
                                "בתיקיית tools של התוכנה.")
            return False
        return True

    def _fb_detect(self):
        if not self._fb_guard():
            return
        self._retry_action = self._fb_detect
        collected: list[str] = []

        def on_done(ok: bool):
            text = "\n".join(collected).strip()
            has_dev = any(line and "\t" in line for line in collected)
            if ok and has_dev:
                bus.fb_parsed.emit({"מכשיר": text.splitlines()[0]}, text)
                # אוטומטית: בירור מצב סוללה (מתח) + פרטים, ועדכון הכותרת למעלה
                self._fb_autobattery()
            elif ok:
                bus.fb_parsed.emit({}, "לא זוהה מכשיר במצב Fastboot.")

        self._request(self._plan(
            lambda: plan_fastboot_simple("Fastboot: זיהוי מכשיר",
                                         FastbootCommands.devices(),
                                         on_done=on_done, on_output=collected.append)))

    def _on_device_info(self, info):
        """מעדכן את לשונית Fastboot אוטומטית: שם מכשיר, מצב בוטלאודר, סוללה."""
        if info is None or getattr(info, "mode", "none") != "fastboot":
            self._fb_warned = False
            if hasattr(self, "fb_auto_label"):
                self.fb_auto_label.setText("לא מחובר מכשיר ב-Fastboot")
            return
        parts = [f"📱 מכשיר: {info.model or 'לא ידוע'}"]
        if info.unlocked is True:
            parts.append("בוטלאודר: 🔓 פתוח")
            self._set_header_boot("🔓 פתוח")
        elif info.unlocked is False:
            parts.append("בוטלאודר: 🔒 נעול")
            self._set_header_boot("🔒 נעול")
        else:
            parts.append("בוטלאודר: לא ידוע")
        if info.extra:
            parts.append(info.extra)
        if getattr(info, "cpu", ""):
            self._apply_detected_cpu(info.cpu)   # thread ראשי — בטוח
        self.fb_auto_label.setText("   ·   ".join(parts))
        if info.battery_too_low() and not self._fb_warned:
            self._fb_warned = True
            note = info.battery_note()
            self._say("warning", f"סוללה נמוכה: {note}")
            self._show_battery_warning(note)

    def _fb_autobattery(self):
        self._fb_warned = False   # זיהוי ידני — להזהיר שוב אם צריך
        """נקרא אוטומטית אחרי זיהוי מכשיר ב-Fastboot: קורא מתח סוללה ופרטים
        ומעדכן את כותרת מצב המכשיר שלמעלה — בלי לחסום את הממשק."""
        fb = config.find_fastboot_exe()
        if not fb:
            return

        def work():
            try:
                info = devinfo.read_fastboot_info(str(fb))
                if info:
                    bus.device_info.emit(info)
                    # סנכרון מפורש של הסוללה בכותרת (אחוז/מתח שאותרו ב-Fastboot)
                    self.device_status.header_refresh.emit()
                    # עדכון המעבד לכותרת נעשה ב-_on_device_info (thread ראשי, דרך device_info)
                    if info.extra:
                        self._say("info", f"Fastboot — {info.extra}")
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _fb_info(self):
        if not self._fb_guard():
            return
        self._retry_action = self._fb_info
        collected: list[str] = []

        def on_done(ok: bool):
            if not ok:
                return
            raw = "\n".join(collected)
            bus.fb_parsed.emit(parse_fastboot_vars(raw), raw)

        self._request(self._plan(
            lambda: plan_fastboot_simple("Fastboot: getvar all",
                                         FastbootCommands.getvar_all(),
                                         on_done=on_done, on_output=collected.append)))

    def _set_fb(self, vars_: dict, raw: str):
        summary = summarize_fastboot(vars_, raw)
        self.fb_status.setHtml(summary)   # setHtml — כדי שההדגשות <b> יוצגו
        for line in summary.splitlines():
            self._say("info", line)
        unlocked = (vars_ or {}).get("בוטלאודר פתוח", "").lower()
        if unlocked in ("yes", "true"):
            self._set_header_boot("🔓 פתוח")
        elif unlocked in ("no", "false"):
            self._set_header_boot("🔒 נעול")

    def _load_previous_logs(self):
        """#1: טוען לתצוגת הלוגים את הלוג מההפעלה הקודמת (לא נמחק בסגירה)."""
        try:
            files = sorted(config.LOGS_DIR.glob("log_*.txt"))
            files = [f for f in files if f.name != log.log_file.name]
            if not files:
                return
            prev = files[-1]
            text = prev.read_text(encoding="utf-8", errors="replace").splitlines()
            self.log_view.append(
                f'<span style="color:#8b949e">──── לוג מהפעלה קודמת ({prev.name}) ────</span>')
            for line in text[-400:]:
                safe = (line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                self.log_view.append(f'<span style="color:#8b949e">{safe}</span>')
            self.log_view.append(
                '<span style="color:#8b949e">──── סוף הלוג הקודם — פעולות חדשות מכאן ────</span>')
        except Exception:
            pass

    def _fb_flash(self):
        if not self._fb_guard():
            return
        self._retry_action = None   # צריבה לא חוזרת אוטומטית
        image = Path(self.fb_image_edit.text().strip())
        part = self.fb_part_edit.text().strip()
        if not part:
            QMessageBox.warning(self, "חסר שם מחיצה", "הזן שם מחיצה (למשל boot)")
            return
        if not image.is_file():
            QMessageBox.warning(self, "קובץ חסר", "בחר קובץ Image תקין")
            return
        self._request(self._plan(plan_fastboot_flash, part, image))

    def _fb_erase(self):
        if not self._fb_guard():
            return
        self._retry_action = None
        part = self.fb_part_edit.text().strip()
        if not part:
            QMessageBox.warning(self, "חסר שם מחיצה", "הזן שם מחיצה למחיקה")
            return
        self._request(self._plan(plan_fastboot_erase, part))

    def _fb_reboot(self, target: str):
        if not self._fb_guard():
            return
        self._retry_action = None
        name = "Fastboot: הפעלה מחדש" + (f" ({target})" if target else "")
        self._request(self._plan(
            lambda: plan_fastboot_simple(name, FastbootCommands.reboot(target), retries=0)))

    # ------------------------------------------------------------ לשונית ניהול
    def _detect_pyenv(self, quiet: bool = False):
        """זיהוי סביבת פייתון ברקע — לא משנה שום דבר, רק מדווח."""
        from ..core import pyenv
        self._pyenv_quiet = quiet
        if not quiet:
            self.pyenv_text.setPlainText("בודק…")

        def work():
            try:
                bus.pyenv_report.emit(pyenv.detect())
            except Exception as e:
                self._say("error", f"זיהוי סביבת פייתון נכשל: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _set_pyenv(self, rep):
        self.pyenv_text.setPlainText(rep.summary())
        no_python = rep.active is None
        self._style_install_python(alert=no_python)
        if rep.ok:
            if not getattr(self, "_pyenv_quiet", False):
                self._say("success", "סביבת פייתון תקינה — mtkclient מוכן לעבודה.")
        else:
            self._say("warning", "סביבת פייתון לא מוכנה — פרטים בלשונית mtkclient.")
        if no_python:
            # מפנים את המשתמש לכפתור ההתקנה האוטומטית — ומציעים אותה פעם אחת
            self.tabs.setCurrentWidget(self.device_tab)
            self.btn_auto_python.setFocus()
            self._say("warning", "לא נמצא פייתון — mtkclient צריך אותו. "
                                 "לחץ על 'התקן פייתון וספריות (אוטומטי)' בלשונית mtkclient.")
            if not getattr(self, "_python_offered", False):
                self._python_offered = True
                self._offer_python_install()

    def _offer_python_install(self):
        """הצעה (פעם אחת) להתקנה אוטומטית של פייתון — לא מעל דיאלוג הפתיחה."""
        if getattr(self, "_startup_dialog_open", False):
            self._python_offer_pending = True   # יוצג מיד אחרי שדיאלוג הפתיחה נסגר
            return
        if QMessageBox.question(
                        self, "חסר פייתון",
                        "כדי לעבוד עם mtkclient (מצב BROM) צריך פייתון במחשב.\n\n"
                        "להתקין אותו עכשיו אוטומטית, עם כל הספריות? "
                        "(צריך אינטרנט, בלי הרשאת מנהל, כמה דקות)\n\n"
                        "ADB ו-Fastboot עובדים גם בלי פייתון.",
                        _YES | _NO, _YES) == _YES:
                    self._auto_install_python(confirm=False)

    def _auto_install_python(self, confirm: bool = True):
        """כפתור 'התקן פייתון וספריות (אוטומטי)' — הכול ב-thread רקע, עם מד התקדמות."""
        from ..core import pyinstall
        if getattr(self, "_pyinstall_running", False):
            return
        if confirm and QMessageBox.question(
                self, "התקנת פייתון וספריות",
                "התוכנה תוריד ותתקין את פייתון מהאתר הרשמי (אם הוא לא מותקן), "
                "עם PATH מסומן, ואז את הספריות של mtkclient.\n\n"
                "צריך אינטרנט. לא צריך הרשאת מנהל. זה לוקח כמה דקות.\nלהמשיך?",
                _YES | _NO, _YES) != _YES:
            return
        self._pyinstall_running = True
        self.btn_auto_python.setEnabled(False)

        def prog(pct: float, text: str):
            bus.progress.emit(pct, text)
            bus.status.emit(f"🐍 {text}")

        def work():
            try:
                ok, msg, _py = pyinstall.install(prog)
            except Exception as e:
                ok, msg = False, f"שגיאה לא צפויה: {e}"
            bus.pyinstall_done.emit((ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _on_pyinstall_done(self, payload):
        ok, msg = payload
        self._pyinstall_running = False
        self.btn_auto_python.setEnabled(True)
        if ok:
            self._say("success", msg.splitlines()[0])
            QMessageBox.information(self, "✅ פייתון מוכן", msg)
            self._detect_pyenv()
            return
        self._say("error", f"התקנת פייתון נכשלה: {msg.splitlines()[0]}")
        dlg = QMessageBox(self)
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setWindowTitle("ההתקנה האוטומטית לא הצליחה")
        dlg.setText(msg)
        dlg.setInformativeText(
            "אפשר להתקין ידנית — 4 צעדים:\n"
            "1. לחץ 'הורדת פייתון להתקנה' והורד את 'Windows installer (64-bit)'.\n"
            "2. פתח את הקובץ שהורד.\n"
            "3. ⚠️ חשוב: בחלון הראשון, למטה, סמן את התיבה "
            "'Add python.exe to PATH' — ורק אז לחץ 'Install Now'.\n"
            "4. בסיום — חזור לכאן ולחץ שוב על 'התקן פייתון וספריות (אוטומטי)' "
            "(הוא יתקין רק את הספריות).\n\n"
            "או — בלי שום התקנה: 'הורדת פייתון נייד' (MTKClient Portable), "
            "וחלץ את הקובץ ליד התוכנה.")
        dlg.addButton("סגור", QMessageBox.ButtonRole.RejectRole)
        b_dl = dlg.addButton("⬇️ הורדת פייתון להתקנה", QMessageBox.ButtonRole.ActionRole)
        b_port = dlg.addButton("⬇️ הורדת פייתון נייד", QMessageBox.ButtonRole.ActionRole)
        dlg.exec()
        if dlg.clickedButton() is b_dl:
            self._open_python_download()
        elif dlg.clickedButton() is b_port:
            QDesktopServices.openUrl(QUrl(_MTK_PORTABLE_URL))

    def _style_install_python(self, alert: bool):
        """כמו כל כפתורי התוכנה; מסגרת אדומה בולטת רק כשפייתון חסר (להפנות אליו)."""
        if alert:
            self.btn_install_python.setStyleSheet(
                "QPushButton { border: 3px solid #d73a49; border-radius: 6px; }")
        else:
            self.btn_install_python.setStyleSheet("")

    def _open_python_download(self):
        from ..core import pyenv
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(pyenv.PYTHON_DOWNLOAD_URL))

    # ------------------------------------------------------------ לשונית לוגים
    def _tab_logs(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        v.addWidget(self.log_view)
        btns = QHBoxLayout()
        b1 = QPushButton("💾 ייצוא לוג")
        b1.clicked.connect(self._export_log)
        b2 = QPushButton("🧹 נקה תצוגה")
        b2.clicked.connect(lambda: self.log_view.clear())
        b3 = QPushButton("📂 תיקיית הלוגים")
        b3.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.LOGS_DIR))))
        for b in (b1, b2, b3):
            btns.addWidget(b)
        btns.addStretch(1)
        v.addLayout(btns)
        return w

    # ------------------------------------------------------------ bus / events
    def _connect_bus(self):
        bus.log_line.connect(self._append_log)
        bus.progress.connect(self._set_progress)
        bus.ports_changed.connect(self._update_ports_table)
        bus.ports_changed.connect(self._probe_device)   # רץ ב-thread הראשי (לא במוניטור)
        bus.gpt_parsed.connect(self._set_gpt)
        bus.status.connect(self.status_label.setText)
        bus.job_done.connect(self._on_job_done)
        bus.sec_parsed.connect(self._set_sec)
        bus.fb_parsed.connect(self._set_fb)
        bus.device_info.connect(self.device_status.set_info)
        bus.device_info.connect(self._on_device_info)
        bus.device_info.connect(self._sync_battery_header)   # סנכרון סוללת הכותרת
        self.device_status.header_refresh.connect(self._sync_battery_header)
        bus.battery_warning.connect(self._show_battery_warning)
        bus.pyenv_report.connect(self._set_pyenv)
        bus.brom_detected.connect(self._suggest_brom_gpt)   # דיאלוג רץ ב-thread הראשי
        bus.adb_details.connect(self._on_adb_details)
        bus.adb_pkgs_text.connect(lambda t: self.adb_pkgs_view.setPlainText(t))
        bus.adb_apps_list.connect(self._on_apps_list)
        bus.adb_app_update.connect(self._on_app_update)
        bus.adb_app_details.connect(self._show_app_details)
        bus.tool_locked.connect(self._set_active_tool)
        bus.adb_boot_state.connect(self._set_adb_boot)
        bus.adb_uninstall_progress.connect(self._on_uninstall_progress)
        bus.adb_op_result.connect(self._on_op_result)
        bus.adb_app_restored.connect(lambda pkg: self._mark_app_row(pkg, ""))
        bus.adb_fs_listing.connect(self._on_fs_listing)
        bus.adb_fs_op.connect(self._on_fs_op)
        bus.adb_fs_edit_ready.connect(self._on_fs_edit_ready)
        bus.adb_install_downgrade.connect(self._on_install_downgrade)
        bus.reconnect_hint.connect(self._on_reconnect_hint)
        bus.driver_fix_result.connect(self._on_driver_fix_result)
        bus.pyinstall_done.connect(self._on_pyinstall_done)
        # מקורות רקע → אותות Qt (thread-safe)
        log.subscribe(lambda level, msg: bus.log_line.emit(level, msg))
        job_manager.on_progress = lambda pct, s: bus.progress.emit(float(pct), s)
        job_manager.on_state = lambda text: bus.status.emit(text)
        job_manager.on_finished = lambda name, ok: bus.job_done.emit(name, ok)
        job_manager.on_reconnect = lambda name, delay: bus.reconnect_hint.emit((name, delay))

    def _append_log(self, level: str, message: str):
        if level == "error":
            self._last_error = message
        colors = theme.LOG_COLORS[self.dark]
        stamp = datetime.now().strftime("%H:%M:%S")
        safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.log_view.append(
            f'<span style="color:{colors["stamp"]}">[{stamp}]</span> '
            f'<span style="color:{colors.get(level, colors["info"])}">{safe}</span>')

    def _busy_progress(self, on: bool):
        """מד התקדמות 'רץ' (marquee) כשאין אחוזים — כדי שתמיד יהיה סימן חיים."""
        if on:
            self.progress.setStyleSheet("")   # חוזר לצבע רגיל בתחילת פעולה
            self.progress.setRange(0, 0)   # מצב בלתי-מסויים: הפס נע הלוך ושוב
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)

    def _set_progress(self, pct: float, suffix: str):
        # ברגע שמגיע אחוז אמיתי — עוברים ממצב 'רץ' למד אחוזים
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        self.progress.setValue(int(pct))
        self.status_label.setText(f"{pct:.1f}% {suffix}")

    def _clear_progress(self):
        """מרוקן את מד ההתקדמות וחוזר ל'מוכן' (נקרא 30 שניות אחרי סיום)."""
        if job_manager.busy:
            return
        self._busy_progress(False)
        self.progress.setStyleSheet("")
        self.status_label.setText("מוכן")

    def _show_battery_warning(self, note: str):
        # משהים את הזיהוי התקופתי בזמן הדיאלוג — כדי שהוא לא יקפוץ שוב מאחוריו
        self._battery_probe_paused = True
        try:
            QMessageBox.warning(
                self, "⚠️ סוללה נמוכה",
                f"{note}\n\nרמת/מתח הסוללה נמוכים מדי — לא מומלץ לצרוב או לבצע פעולות "
                "כתיבה במצב הזה. צריבה שנקטעת בגלל סוללה חלשה עלולה להזיק למכשיר.\n\n"
                "טען את המכשיר לפחות ל-40% והתחבר שוב. קריאת נתונים בסיסית לרוב אפשרית, "
                "אך צריבה — לא לפני טעינה.")
        finally:
            self._battery_probe_paused = False

    def _last_job_dest(self) -> str:
        """תיקיית היעד של הפעולה שהסתיימה לאחרונה — מהנתיבים בפקודות שרצו בפועל."""
        last = job_manager.last
        if last is None:
            return ""
        try:
            for step in reversed(getattr(last, "steps", [])):
                for a in getattr(getattr(step, "command", None), "args", None) or []:
                    if str(a).lower().endswith((".img", ".bin")):
                        return str(Path(a).parent)
        except Exception:
            pass
        return ""

    def _success_explanation(self, name: str) -> str:
        """הסבר קצר לפעולה שהצליחה: מה נעשה ולמה זה משמש — כדי שההצלחה תהיה ברורה."""
        n = (name or "")
        if "GPT" in n:
            return ("טבלת המחיצות נקראה מהמכשיר ומוצגת בלשונית mtkclient.\n\n"
                    "שימושים: שמות וגדלים של כל המחיצות, זיהוי אוטומטי של שם המעבד "
                    "(מופיע למעלה ובלשונית Scatter), ובסיס ליצירת Scatter ל-SP Flash Tool.")
        if "שאיבת" in n:
            return ("המחיצות נשאבו לקובצי \u200e.img בתיקיית workspace\\dumps עם סכום ביקורת SHA256.\n\n"
                    "שימושים: גיבוי לפני צריבה, שחזור מהמחיצות בעתיד, או ניתוח הקבצים במחשב.")
        if "צריבת" in n or "flash" in n.lower():
            return ("הקובץ נצרב למחיצה בהצלחה (לפני כן נעשה גיבוי אוטומטי למחיצה הקודמת).\n\n"
                    "שימושים: החלפת תמונת מערכת/ריקברי/בוט וכדומה. אם המכשיר לא עולה "
                    "אחרי הצריבה — שחזר את הגיבוי מ-workspace\\backups.")
        if "NVRAM" in n or "nvram" in n:
            dest = self._last_job_dest()
            dest_line = (f"\n\nהגיבוי נשמר ב:\n{dest}\n"
                         "העתק את התיקייה גם למקום אחר (לא רק במחשב הזה)!") if dest else ""
            return ("ה-NVRAM וה-NVDATA גובו — שם נמצאים ה-IMEI, כתובות ה-MAC והכיול."
                    + dest_line + "\n\n"
                    "שימושים: שחזור IMEI/MAC במקרה של נזק למחיצות אלה "
                    "(דרך לשונית צריבה). שמור על הקבצים במקום בטוח!")
        if "Factory Reset" in n or "מחיקת" in n:
            return ("המחיצות שנבחרו נמחקו. Factory Reset מוחק את כל נתוני המשתמש.\n\n"
                    "שימושים: איפוס לפני מכירה, פתרון בעיות תוכנה, או ניקוי מלא של המכשיר.")
        if "seccfg" in n.lower():
            return ("תצורת אבטחת המכשיר (seccfg) עודכנה.\n\n"
                    "שימושים: פתיחה/נעילה של הבוטלאודר. אחרי unlock — פעולות הצריבה "
                    "מ-Fastboot יתקבלו על ידי המכשיר.")
        if "Fastboot" in n:
            return ("פעולת ה-Fastboot הושלמה.\n\n"
                    "שימושים: זיהוי/מידע על המכשיר במצב Fastboot, צריבת קובצי \u200e.img "
                    "לפי שם מחיצה, או אתחול המכשיר מחדש.")
        if "בדיקת מצב אבטחה" in n or "בוטלאודר" in n:
            return ("מצב האבטחה נקרא מהמכשיר (קריאה בלבד).\n\n"
                    "שימושים: בדיקה אם Secure Boot/DAA/SLA פעילים — כלומר האם ניתן "
                    "לצרוב. התוצאה מוצגת בלשונית Bootloader ובכותרת למעלה.")
        return ""

    def _on_reconnect_hint(self, payload):
        """כשל שדורש חיבור מחדש — הודעה בולטת למשתמש (לא חוסמת)."""
        _name, delay = payload
        self.progress.setStyleSheet("")
        self.status_label.setText(
            f"🔌 החיבור נכשל — נתק וחבר את המכשיר במצב BROM. ממתין לחיבור עד {int(delay)} שניות…")

    def _on_job_done(self, name: str, ok: bool):
        self.cancel_btn.setEnabled(False)
        self._busy_progress(False)
        # ניסיון ה-GPT הסתיים — מבטלים את הטיימר/ההתראה של "נתקע"
        if getattr(self, "_gpt_timer", None):
            self._gpt_timer.stop()
            self._gpt_timer = None
        if getattr(self, "_gpt_timeout_dialog", None) is not None:
            dlg, self._gpt_timeout_dialog = self._gpt_timeout_dialog, None
            dlg.close()
        last = job_manager.last
        cancelled = last is not None and last.status == "מבוטל"
        if ok:
            self.status_label.setText(f"{name}: הסתיים בהצלחה")
            self.progress.setValue(100)
            self.progress.setStyleSheet("QProgressBar::chunk { background-color: #2ea043; }")
            log.info(f"job_done (thread ראשי): {name} — לפני דיאלוג הצלחה")
            self._show_success(name)
            log.info(f"job_done: {name} — אחרי דיאלוג הצלחה")
            # אחרי קריאת GPT: הצעת בדיקת בוטלאודר — סדרתית, אחרי שהדיאלוג נסגר
            if name == "קריאת GPT" and self.gpt is not None:
                self._offer_bootloader_check()
        elif cancelled:
            self.status_label.setText(f"{name}: בוטל על ידי המשתמש")
        else:
            self.status_label.setText(f"{name}: ❌ נכשל")
            self._show_failure(name)
        if getattr(self, "_clear_timer", None):
            self._clear_timer.start()   # ינוקה אחרי 30 שניות

    def _show_success(self, name: str):
        """הודעת הצלחה ברורה עם הסבר קצר: מה נעשה ולמה זה משמש."""
        expl = self._success_explanation(name)
        QMessageBox.information(
            self, "✅ הפעולה הושלמה בהצלחה",
            f"הפעולה '{name}' הושלמה בהצלחה." + (f"\n\n{expl}" if expl else ""))

    def _show_failure(self, name: str):
        """חלון ברור שהפעולה נכשלה — קריטי כדי שלא יחשבו שהיא הצליחה."""
        last = job_manager.last
        if last is not None and getattr(last, "no_fastboot_device", False):
            self._show_no_fastboot_device(name)
            return
        if last is not None and getattr(last, "connection_failed", False):
            self._show_connection_failure(name, last)
            return
        err = getattr(self, "_last_error", "")
        detail = f"\n\nשגיאה אחרונה:\n{err}" if err else ""
        dlg = QMessageBox(self)
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setWindowTitle("❌ הפעולה נכשלה")
        dlg.setText(f"הפעולה '{name}' לא הושלמה.")
        dlg.setInformativeText(
            f"{detail}\n\nבדוק את לשונית הלוגים לפירוט מלא.\n"
            "סיבות נפוצות: המכשיר יצא ממצב BROM/Preloader — נסו להכניס אותו שוב במצב BROM, "
            "התקשורת עם המעבד נותקה, ה-DA לא נטען, או שהמכשיר תקול. "
            "נתק וחבר מחדש את המכשיר במצב BROM.")
        close_btn = dlg.addButton("סגור", QMessageBox.ButtonRole.RejectRole)
        retry_btn = None
        if self._retry_action is not None:
            retry_btn = dlg.addButton("🔄 נסה שוב", QMessageBox.ButtonRole.AcceptRole)
            dlg.setDefaultButton(retry_btn)
        dlg.exec()
        if retry_btn is not None and dlg.clickedButton() is retry_btn:
            action = self._retry_action
            if action is not None:
                self._retry_now(action)

    def _show_no_fastboot_device(self, name: str):
        """פקודת Fastboot נכשלה כי אין מכשיר במצב Fastboot — הסבר + ביטול / ניסיון חוזר."""
        from ..core.fastboot_bridge import FastbootCommand
        dlg = QMessageBox(self)
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setWindowTitle("📵 אין מכשיר במצב Fastboot")
        dlg.setText(f"'{name}' לא בוצע: לא נמצא מכשיר מחובר במצב Fastboot "
                    f"(המתנה של עד {int(FastbootCommand.DEVICE_TIMEOUT)} שניות).")
        dlg.setInformativeText(
            "איך להכניס את המכשיר למצב Fastboot:\n"
            "• מהמכשיר הדלוק: בלשונית 📱 ADB לחץ '🚀 עבור למצב Fastboot'.\n"
            "• או: כבה את המכשיר, החזק ווליום למטה + הפעלה עד שמופיע מסך Fastboot, "
            "וחבר בכבל USB.\n\n"
            "אם המכשיר במסך Fastboot ועדיין לא מזוהה — בדוק את הדרייבר "
            "(🩺 בדיקת דרייבר Fastboot, בתחתית הלשונית).")
        dlg.addButton("ביטול", QMessageBox.ButtonRole.RejectRole)
        retry_btn = None
        if self._retry_action is not None:
            retry_btn = dlg.addButton("🔄 ניסיון חוזר", QMessageBox.ButtonRole.AcceptRole)
            dlg.setDefaultButton(retry_btn)
        dlg.exec()
        if retry_btn is not None and dlg.clickedButton() is retry_btn:
            action = self._retry_action
            if action is not None:
                self._retry_now(action)

    def _show_connection_failure(self, name: str, job):
        """כל הניסיונות נכשלו בחיבור למכשיר — הסבר איך לחבר + ביטול / ניסיון חוזר."""
        attempts = job.retries + 1
        dlg = QMessageBox(self)
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setWindowTitle("🔌 החיבור למכשיר נכשל")
        dlg.setText(f"'{name}' נעצר: החיבור למכשיר נכשל {attempts} פעמים "
                    f"(עד {int(job.connect_timeout)} שניות המתנה בכל ניסיון).")
        dlg.setInformativeText(
            "איך לחבר במצב BROM:\n"
            "1. כבה את המכשיר לגמרי ונתק את הכבל.\n"
            "2. החזק את לחצן הווליום (למעלה, למטה, או שניהם — תלוי במכשיר) "
            "וחבר את הכבל תוך כדי.\n"
            "3. אם המכשיר דלוק ולא מגיב — החזק את לחצן ההפעלה כ-10 שניות תוך כדי החיבור.\n\n"
            "אם החיבור נופל באמצע פעולה: נסה כבל אחר ויציאת USB ישירה במחשב (בלי מפצל).\n\n"
            "לחץ 'ניסיון חוזר' — ואז חבר את המכשיר.")
        cancel_btn = dlg.addButton("ביטול", QMessageBox.ButtonRole.RejectRole)
        retry_btn = None
        if self._retry_action is not None:
            retry_btn = dlg.addButton("🔄 ניסיון חוזר", QMessageBox.ButtonRole.AcceptRole)
            dlg.setDefaultButton(retry_btn)
        dlg.exec()
        if retry_btn is not None and dlg.clickedButton() is retry_btn:
            action = self._retry_action
            if action is not None:
                self._retry_now(action)

    def _cancel_job(self):
        if not job_manager.busy:
            return
        cur = job_manager.current
        if cur is not None and cur.danger:
            # אזהרת נזק — רק בפעולות כתיבה (צריבה/מחיקה/seccfg); בקריאה בלבד אין סיכון
            text = ("לעצור את הפעולה הנוכחית?\n"
                    "⚠️ עצירה באמצע צריבה עלולה להשאיר את המחיצה פגומה.")
        else:
            text = "לעצור את הפעולה הנוכחית?"
        if QMessageBox.question(self, "ביטול פעולה", text,
                                _YES | _NO, _NO) == _YES:
            job_manager.cancel_current()
            self._show_cancelling()

    def _show_cancelling(self):
        """חיווי 'מבטל…' — מד התקדמות עם מילוי אדום עדין שנע לאורך הגליל, עד סיום הביטול."""
        self.progress.setRange(0, 0)   # marquee — נע לאורך כל הגליל
        self.progress.setStyleSheet(
            "QProgressBar::chunk { background-color: rgba(209,52,56,0.65); }")
        self.status_label.setText("🛑 מבטל…")

    def _retry_now(self, action):
        """נסה שוב: מבטל מיד כל פעולה שנשארה (בלי דיאלוג), ואז מריץ מחדש נקי."""
        if action is None:
            return
        if job_manager.busy:
            job_manager.cancel_current()
            self._show_cancelling()

            def when_free(tries=0):
                if not job_manager.busy or tries > 60:
                    action()
                else:
                    QTimer.singleShot(150, lambda: when_free(tries + 1))

            QTimer.singleShot(150, lambda: when_free())
        else:
            action()

    # ------------------------------------------------------------ זיהוי
    def _refresh_ports(self):
        self._update_ports_table(scan_ports())

    def _on_ports_changed(self, ports):
        # נקרא מ-thread של מוניטור הפורטים — רק פולטים אות. גם עדכון הטבלה וגם
        # הזיהוי (_probe_device) מחוברים ל-ports_changed ולכן ירוצו ב-thread הראשי
        # (queued), ולא כאן. גישה ל-Qt מ-thread רקע גרמה ל-access violation אחרי GPT.
        bus.ports_changed.emit(ports)

    def _probe_device(self, ports=None):
        """קורא ברקע את פרטי המכשיר (דגם/מעבד/סוללה) ומעדכן את פס הסטטוס.

        סדר זיהוי מדורג: ADB קודם (הערוץ העשיר ביותר); אם אין — הודעה מפורשת
        ומעבר ל-BROM/Preloader כשיש פורט MTK (עם הצעת קריאת GPT של mtkclient);
        Fastboot אינו נבדק אוטומטית כלל — רק בבקשת המשתמש מלשונית Fastboot.
        """
        if job_manager.busy:
            return   # לא מפריעים לפעולת mtk פעילה
        if self._battery_probe_paused:
            return   # דיאלוג אזהרת סוללה פתוח — הזיהוי יימשך אחריו
        if self._probing or self._apps_loading or getattr(self, "_adb_busy", False):
            return   # בדיקה קודמת עוד רצה / ADB עסוק בטעינת אפליקציות
        tool = self._active_tool
        if tool == "none":
            return   # לא נבחר ערוץ — אין חיפוש אוטומטי (לבקשת המשתמש)
        if tool == "fastboot":
            return   # ב-Fastboot הזיהוי רק לפי בקשה מהלשונית — לא נוגעים במכשיר
        if ports is None:
            ports = scan_ports()
        has_brom = any(is_preloader_port(p.vid, p.pid) for p in ports)
        brom_cpu = getattr(self.gpt, "cpu", "") if self.gpt else ""
        self._probing = True

        def work():
            try:
                if tool == "brom":
                    # נעול על mtkclient — לא שולחים פקודות ADB בכלל
                    info = (devinfo.DeviceInfo(mode="brom", cpu=devinfo._norm_cpu(brom_cpu))
                            if has_brom else devinfo.DeviceInfo(mode="none"))
                else:
                    # נעול על ADB — לא קופצים ל-BROM כש-ADB לא עונה לרגע
                    info = devinfo.probe(has_brom if tool == "auto" else False, brom_cpu)
                bus.device_info.emit(info)
                # הודעות מעבר בין שלבי הזיהוי — רק כשהמצב בפועל משתנה
                mode = getattr(info, "mode", "none")
                if mode != self._last_probe_mode:
                    if mode == "adb":
                        self._say("success", f"מכשיר זוהה ב-ADB — {info.model or info.cpu}")
                    elif mode == "brom":
                        self._say("warning",
                                  "לא נמצא מכשיר במצב ADB — נמצא פורט BROM/Preloader. "
                                  "קרא GPT כדי לזהות את המעבד (mtkclient).")
                        bus.brom_detected.emit()   # הצעת GPT ב-thread הראשי
                    elif tool == "adb":
                        self._say("warning", "המכשיר לא עונה ב-ADB (נותק או נעול) — "
                                             "ממשיך לחכות לו ב-ADB בלבד.")
                    else:
                        self._say("info", "אין מכשיר מחובר (בדיקת ADB/BROM)")
                    self._last_probe_mode = mode
                    # אחרי זיהוי ראשון — ננעלים על הערוץ שעובד (עד שהמשתמש יחליף)
                    if tool == "auto" and mode in ("adb", "brom"):
                        bus.tool_locked.emit(mode)
            except Exception:
                pass
            finally:
                self._probing = False

        threading.Thread(target=work, daemon=True).start()

    def _suggest_brom_gpt(self):
        """מציע קריאת GPT כשמכשיר מגיע ב-BROM/Preloader (קריאה בלבד).

        מופעל רק מפורט BROM/Preloader אמיתי של מכשיר (VID 0E8D + PID 0x0003/0x2000/0x2001).
        שבבי Bluetooth/Wi-Fi מובנים של MediaTek בלוח המחשב מדווחים אותו VID אבל ב-PID אחר,
        ולכן לא יפעילו את ההצעה — זו הסיבה שקודם הופיעה ההצעה מיד בפתיחה בלי מכשיר.
        """
        if job_manager.busy or getattr(self, "_brom_suggest_open", False):
            return
        if self.gpt is not None:
            return   # כבר יש טבלת מחיצות — המעבד ידוע
        # בודקים מחדש מול הפורטים בפועל: חייב פורט Preloader אמיתי, לא רק VID
        if not any(is_preloader_port(p.vid, p.pid) for p in scan_ports()):
            return
        self._brom_suggest_open = True
        try:
            if QMessageBox.question(
                    self, "מכשיר במצב BROM/Preloader",
                    "לא נמצא מכשיר במצב ADB, אבל זוהה פורט BROM/Preloader של MediaTek.\n\n"
                    "לקרוא עכשיו את טבלת המחיצות (GPT) דרך mtkclient?\n"
                    "(קריאה בלבד — הפעולה מזהה גם את שם המעבד)",
                    _YES | _NO, _YES) == _YES:
                self._read_gpt()
        finally:
            self._brom_suggest_open = False

    # ------------------------------------------------------------ בחירת כלי בפתיחה
    def _startup_tool_dialog(self):
        """דיאלוג פתיחה: באיזה כלי לדבר עם המכשיר (ADB / Fastboot / mtkclient).

        לא משנה שום פונקציונליות — רק נגישות: לכל אופציה הסבר קצר וכפתור הוראות,
        ואחרי בחירה מעבר ללשונית המתאימה + הרצת הזיהוי של אותו כלי. ניתן לסגור
        ולהמשיך בלי בחירה — הזיהוי האוטומטי המדורג רץ ברקע בכל מקרה.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("בחירת כלי תקשורת עם המכשיר")
        # חלון לרוחב: שלוש אופציות זו לצד זו (RTL — ADB מימין)
        dlg.resize(1000, 330)
        # מראה בולט — כדי שהדיאלוג לא ייבלע ברקע של התוכנה (כהה ובהיר)
        # בערכת הכחול העמוק — אותו כחול כמו התוכנה, מדורג כלפי מעלה
        accent = "#2f81f7"                              # כחול ההדגשה — בשתי הערכות
        bg = "#2b313a" if self.dark else "#133a66"        # אותו גוון כמו התוכנה, מעט בהיר יותר
        banner = "#3a424d" if self.dark else "#1a4a7d"   # פס הכותרת — עוד קצת בהיר
        card = "#30363d" if self.dark else "#16375f"
        fg = "#e6edf3" if self.dark else "#e9f1fb"
        dlg.setStyleSheet(
            f"QDialog {{ background-color: {bg}; border: 2px solid {accent}; }}"
            f"QGroupBox {{ background-color: {card}; border: 2px solid {accent};"
            f" border-radius: 8px; margin-top: 16px; padding: 10px 8px 8px 8px;"
            f" font-weight: bold; color: {fg}; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right;"
            f" padding: 0 8px; color: {accent}; }}"
            f"QLabel {{ color: {fg}; font-weight: normal; font-size: 10.5pt; }}")
        v = QVBoxLayout(dlg)
        intro = QLabel(
            "באיזה כלי ברצונך לדבר עם המכשיר? החיפוש אחרי המכשיר יתחיל אחרי שתבחר.")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            f"background-color: {banner}; color: {fg}; font-size: 14pt;"
            f" font-weight: bold; padding: 14px; border: 1px solid {accent};"
            f" border-radius: 6px;")
        # "מסגרת" עדינה לאותיות — הילה כחולה סביב הטקסט
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        from PySide6.QtGui import QColor as _QColor
        _glow = QGraphicsDropShadowEffect(intro)
        _glow.setColor(_QColor(accent))
        _glow.setBlurRadius(6)
        _glow.setOffset(0, 0)
        intro.setGraphicsEffect(_glow)
        v.addWidget(intro)
        grid = QGridLayout()
        grid.setSpacing(8)

        def add_option(title: str, desc: str, tool: str):
            gb = QGroupBox(title)
            gl = QVBoxLayout(gb)
            lbl = QLabel(desc)
            lbl.setWordWrap(True)
            gl.addWidget(lbl)
            row = QHBoxLayout()
            b_pick = QPushButton("בחר")
            b_pick.setStyleSheet(
                f"background-color: {accent}; color: white; font-weight: bold;"
                f" padding: 4px 16px; border-radius: 4px;")
            b_pick.clicked.connect(lambda _=False, t=tool: self._select_tool(t, dlg))
            b_help = QPushButton("❓ הוראות")
            b_help.clicked.connect(lambda _=False, t=tool: self._show_mode_instructions(t))
            row.addWidget(b_pick)
            row.addWidget(b_help)
            row.addStretch(1)
            gl.addLayout(row)
            return gb

        order = [
            add_option("📱 ADB — המכשיר דלוק",
                       "כשהמכשיר דלוק ותקין — הדרך הפשוטה: מציג דגם, מעבד ואחוז סוללה, "
                       "ומאפשר ניהול אפליקציות (התקנת כל סגנונות החבילה/הסרה), סייר קבצים "
                       "מלא, בדיקת בוטלאודר והרשאות ניהול.", "adb"),
            add_option("⚡ Fastboot — הבוטלאודר",
                       "צריבה ומחיקה של מחיצות (קובצי \u200e.img) ופעולות בוטלאודר.\n"
                       "דורש: המכשיר במצב Fastboot ודרייבר מתאים.", "fastboot"),
            add_option("🧬 mtkclient — BROM/Preloader",
                       "גם כשהמכשיר תקול או חסום- יש לו גישה למעבד, מועיל לשאיבת "
                       "וצריבת מחיצות, פתיחת הבוטלאודר ועוד , היתרון הגדול לא מצריך "
                       "מצב מפתחים או סקטאר.", "brom"),
        ]
        for col, gb in enumerate(order):
            grid.setColumnStretch(col, 1)
            grid.addWidget(gb, 0, col)
        v.addLayout(grid)
        row = QHBoxLayout()
        row.addStretch(1)
        b_unsure = QPushButton("🤷 אני לא יודע עדיין")
        b_unsure.clicked.connect(lambda: self._unsure_tool_flow(dlg))
        row.addWidget(b_unsure)
        v.addLayout(row)
        self._startup_dialog_open = True
        try:
            dlg.exec()
        finally:
            self._startup_dialog_open = False
        if getattr(self, "_python_offer_pending", False):
            self._python_offer_pending = False
            QTimer.singleShot(300, self._offer_python_install)

    def _unsure_tool_flow(self, dlg):
        """'אני לא יודע עדיין': שאלה אחת על מצב מפתחים — ולפי התשובה ADB או mtkclient."""
        dlg.accept()
        q = QMessageBox(self)
        q.setIcon(QMessageBox.Icon.Question)
        q.setWindowTitle("איך להתחבר למכשיר?")
        q.setText("במכשיר שלך מופעל מצב מפתחים עם ניפוי באגים ב-USB?")
        q.setInformativeText(
            "אם המכשיר נדלק ואפשר להפעיל את זה — זו הדרך הפשוטה (ADB).\n"
            "אם המכשיר לא נדלק, תקוע, או שאי אפשר להפעיל — נעבור ל-mtkclient.")
        b_yes = q.addButton("כן, מופעל", QMessageBox.ButtonRole.YesRole)
        b_can = q.addButton("לא, אבל אפשר להפעיל", QMessageBox.ButtonRole.ActionRole)
        b_no = q.addButton("לא / המכשיר לא נדלק", QMessageBox.ButtonRole.NoRole)
        q.setDefaultButton(b_yes)
        q.exec()
        clicked = q.clickedButton()
        if clicked is b_yes:
            self._select_tool("adb", None)
        elif clicked is b_can:
            self._show_mode_instructions("adb")
            self._select_tool("adb", None)
        elif clicked is b_no:
            self._show_mode_instructions("brom")
            self._select_tool("brom", None)

    def _select_tool(self, tool: str, dlg):
        """בחירת כלי: סגירת הדיאלוג, מעבר ללשונית המתאימה והרצת הזיהוי שלו."""
        if dlg is not None:
            dlg.accept()
        self._set_active_tool(tool)
        if tool == "adb":
            self.tabs.setCurrentWidget(self.adb_tab)
            self._probe_device()
        elif tool == "fastboot":
            if not self._fb_guard():
                return
            self.tabs.setCurrentWidget(self.fastboot_tab)
            self._fb_detect()
        elif tool == "brom":
            self.tabs.setCurrentWidget(self.device_tab)
            self._suggest_brom_gpt()

    def _show_mode_instructions(self, tool: str):
        """חלון הוראות מפורט לכל מצב תקשורת."""
        if tool == "adb":
            title = "הוראות: הכנת המכשיר ל-ADB"
            text = (
                "1. במכשיר: הגדרות ← על הטלפון/מידע על התוכנה ← הקש 7 פעמים על "
                "'מספר ה-Build' עד להודעה 'אתה כעת מפתח'.\n\n"
                "2. חזור להגדרות ← מערכת ← אפשרויות מפתחים ← הפעל "
                "'ניפוי באגים USB' (USB Debugging).\n\n"
                "3. חבר את המכשיר בכבל USB — במסך המכשיר תופיע בקשת אישור "
                "'אפשר ניפוי באגים USB' — אשר אותה (ניתן לסמן 'תמיד').\n\n"
                "4. אם נשאל לגבי מצב USB — בחר 'העברת קבצים' (MTP).\n\n"
                "כשהחיבור תקין, הדגם ואחוז הסוללה יופיעו אוטומטית בכותרת למעלה.")
        elif tool == "fastboot":
            title = "הוראות: כניסה למצב Fastboot"
            text = (
                "מצב Fastboot רץ על הבוטלאודר — שימושי לצריבת קובצי \u200e.img לפי שם מחיצה "
                "(boot, recovery, vbmeta וכדומה), מחיקת מחיצות ופעולות בוטלאודר.\n\n"
                "כניסה למצב:\n"
                "• מהמכשיר הדלוק (עם ADB): לחץ בלשונית 📱 ADB על 'עבור למצב Fastboot' — "
                "התוכנה מריצה 'adb reboot bootloader' וממתינה לזיהוי המכשיר ב-Fastboot.\n"
                "• ידנית: כבה את המכשיר, ואז החזק כפתור הפעלה + ווליום מטה (או שני "
                "הווליומים — תלוי דגם) עד שמופיע לוגו Fastboot.\n\n"
                "דרישות: דרייבר 'Android Bootloader Interface' (כפתורי הדרייברים "
                "בלשונית Fastboot), ולצריבה/מחיקה — בוטלאודר פתוח.\n\n"
                "⚠️ שים לב: צריבת מחיצה שגויה עלולה להמית את המכשיר. גבה קודם!")
        else:
            title = "הוראות: חיבור במצב BROM/Preloader\u200f (mtkclient)\u200f"
            text = (
                "מצב BROM הוא השכבה הנמוכה ביותר בשבב — עובד גם כשהמכשיר כבוי, "
                "תקול או נתקע בלולאת אתחול. דרכו ניתן לקרוא GPT, לשאוב ולצרוב מחיצות "
                "ולנהל את הבוטלאודר.\n\n"
                "כניסה למצב:\n"
                "1. כבה את המכשיר לגמרי (או הוצא את הסוללה אם ניתן).\n"
                "2. החזק את כפתורי ווליום מעלה + ווליום מטה (או את כל הכפתורים).\n"
                "3. תוך כדי ההחזקה — חבר את כבל ה-USB.\n\n"
                "ל-Preloader: חבר USB בלי ללחוץ על כפתורים כלל.\n\n"
                "הזיהוי כאן אוטומטי — ברגע שפורט MTK מופיע, תוצע לך קריאת GPT "
                "שמזהה גם את שם המעבד.")
        QMessageBox.information(self, title, text)

    def _update_ports_table(self, ports):
        self.ports_table.setRowCount(0)
        for p in ports:
            row = self.ports_table.rowCount()
            self.ports_table.insertRow(row)
            for col, val in enumerate([p.port_name, p.description, p.mode,
                                       f"0x{p.vid:04X}", f"0x{p.pid:04X}"]):
                item = QTableWidgetItem(str(val))
                if p.is_mtk:
                    item.setForeground(self._mtk_color())
                self.ports_table.setItem(row, col, item)

    def _read_adb_details(self):
        """קורא מידע מורחב מהמכשיר ב-ADB (קריאה בלבד) ומציג אותו בלשונית ADB.

        הקריאה רצה ב-thread רקע; העדכון ל-UI נעשה רק דרך אותות Qt
        (עדכון ווידג'טים ישירות מ-thread רקע גורם לקריסה).
        """
        adb = config.find_adb_exe()
        if not adb:
            QMessageBox.warning(
                self, "אין adb",
                "adb.exe לא נמצא. ודא שתיקיית tools מכילה את platform-tools "
                "(או הגדר ASKATEROOV_ADB).")
            return
        self.adb_info_view.setPlainText("קורא מהמכשיר…")

        def work():
            details = devinfo.collect_adb_details(str(adb))
            if details:
                text = "\n".join(f"{k}: {v}" for k, v in details.items())
                bus.adb_details.emit(text, "success")
                # סנכרון לכותרת למעלה (דגם / מעבד / סוללה) — גם כשערוץ התקשורת לא מתעדכן לבד
                try:
                    lvl = details.get("סוללה", "").rstrip("%").strip()
                    info = devinfo.DeviceInfo(
                        mode="adb",
                        model=details.get("דגם", ""),
                        cpu=devinfo._norm_cpu(details.get("מעבד (platform)", "")
                                              or details.get("חומרה", "")),
                        battery=int(lvl) if lvl.isdigit() else None)
                    bus.device_info.emit(info)
                except Exception:
                    pass
            else:
                text = ("לא נמצא מכשיר במצב ADB.\n\nבדוק: המכשיר דלוק, ניפוי באגים USB "
                        "מאושר (ראה כפתור ההוראות בדיאלוג הפתיחה), והדרייבר מותקן.")
                bus.adb_details.emit(text, "warning")

        threading.Thread(target=work, daemon=True).start()

    def _on_adb_details(self, text: str, level: str):
        """מציג את תוצאת קריאת מידע ה-ADB (נקרא ב-thread הראשי דרך אות)."""
        self.adb_info_view.setPlainText(text)
        self._say(level, "מידע ADB נקרא" if level == "success" else "לא נמצא מכשיר ב-ADB")

    # ------------------------------------------------------------ לשונית ADB
    def _tab_adb(self) -> QWidget:
        """לשונית ADB: מידע על המכשיר + ניהול אפליקציות (התקנה/הסרה)."""
        w = QWidget()
        v = QVBoxLayout(w)

        note_row = QHBoxLayout()
        note = QLabel(
            "כל הפעולות בלשונית זו דורשות מכשיר דלוק מחובר עם ניפוי באגים USB "
            "מאושר. הפעולות רצות עם adb.exe מתיקיית tools.")
        note.setWordWrap(True)
        note_row.addWidget(note, 1)
        b_adb_help = QPushButton("❓ הוראות ADB")
        b_adb_help.clicked.connect(lambda: self._show_mode_instructions("adb"))
        note_row.addWidget(b_adb_help)
        v.addLayout(note_row)

        # דרייבר ADB
        gb_drv = QGroupBox("דרייבר ADB")
        gd = QHBoxLayout(gb_drv)
        lbl_drv = QLabel("אם המכשיר לא מזוהה ב-ADB — התקן את דרייבר ה-USB הרשמי של Google:")
        lbl_drv.setWordWrap(True)
        gd.addWidget(lbl_drv, 1)
        b_adb_drv = QPushButton("⬇️ הורדת דרייבר ADB")
        b_adb_drv.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://developer.android.com/studio/run/win-usb")))
        b_adb_check = QPushButton("🩺 בדיקת דרייבר ADB")
        b_adb_check.setToolTip("בדיקה קריאה-בלבד: האם דרייבר ה-USB של Google "
                               "מותקן במחשב הזה")
        b_adb_check.clicked.connect(lambda: self._check_drivers("adb"))
        b_adb_install = QPushButton("⚙️ התקנת דרייבר ADB (מתוך התוכנה)")
        b_adb_install.setToolTip("מתקין את דרייברי Android שארוזים בתוכנה (נדרשת הרשאת מנהל)")
        b_adb_install.clicked.connect(lambda: self._install_android_drivers("ADB"))
        gd.addWidget(b_adb_install)
        gd.addWidget(b_adb_drv)
        gd.addWidget(b_adb_check)
        gd.addWidget(self._fix_driver_button())
        v.addWidget(gb_drv)

        # בוטלאודר דרך ADB
        gb_boot = QGroupBox("בוטלאודר (דרך ADB)")
        gbv = QVBoxLayout(gb_boot)
        self.adb_boot_view = QTextEdit()
        self.adb_boot_view.setReadOnly(True)
        self.adb_boot_view.setMaximumHeight(95)
        self.adb_boot_view.setPlaceholderText("לחץ 'בדוק מצב בוטלאודר'.")
        gbv.addWidget(self.adb_boot_view)
        boot_row = QHBoxLayout()
        b_boot_read = QPushButton("🔍 בדוק מצב בוטלאודר")
        b_boot_read.clicked.connect(self._adb_boot_read)
        b_boot_unlock = QPushButton("🔓 פתח בוטלאודר")
        b_boot_unlock.setObjectName("btnWarn")
        b_boot_unlock.clicked.connect(lambda: self._adb_boot_change(True))
        b_boot_lock = QPushButton("🔒 נעל בוטלאודר")
        b_boot_lock.clicked.connect(lambda: self._adb_boot_change(False))
        # מעבר מ-Android (ADB) למצב Fastboot — בלי לגעת בבוטלאודר ובלי למחוק נתונים
        b_boot_fb = QPushButton("🚀 עבור למצב Fastboot")
        b_boot_fb.setToolTip("מאתחל את המכשיר הדלוק למצב Fastboot\u200f (adb reboot bootloader)\u200f "
                             "וממתין לזיהויו ב-Fastboot. הבוטלאודר לא נפתח ולא ננעל.")
        b_boot_fb.clicked.connect(self._adb_reboot_bootloader)
        boot_row.addWidget(b_boot_read)
        boot_row.addWidget(b_boot_unlock)
        boot_row.addWidget(b_boot_lock)
        boot_row.addWidget(b_boot_fb)
        boot_row.addWidget(self._help_dot("adb_reboot_bl"))
        boot_row.addStretch(1)
        gbv.addLayout(boot_row)
        v.addWidget(gb_boot)

        # מידע על המכשיר (קריאה בלבד)
        gb_info = QGroupBox("מידע על המכשיר (קריאה בלבד)")
        gi = QVBoxLayout(gb_info)
        self.adb_info_view = QTextEdit()
        self.adb_info_view.setReadOnly(True)
        self.adb_info_view.setPlaceholderText("לחץ 'קרא מידע' כדי לקרוא את פרטי המכשיר.")
        self.adb_info_view.setMaximumHeight(160)
        gi.addWidget(self.adb_info_view)
        info_btns = QHBoxLayout()
        b_read_info = QPushButton("ℹ️ קרא מידע")
        b_read_info.clicked.connect(self._read_adb_details)
        info_btns.addWidget(b_read_info)
        info_btns.addWidget(self._help_dot("adb_info"))
        info_btns.addStretch(1)
        gi.addLayout(info_btns)
        v.addWidget(gb_info)

        # ניהול אפליקציות
        gb_apps = QGroupBox("ניהול אפליקציות")
        ga = QVBoxLayout(gb_apps)

        # הסרה לפי שם חבילה
        row_un = QHBoxLayout()
        row_un.addWidget(QLabel("שם חבילה להסרה:"))
        self.adb_pkg_edit = QLineEdit()
        self.adb_pkg_edit.setPlaceholderText("למשל com.example.app")
        row_un.addWidget(self.adb_pkg_edit, 1)
        b_paste = QPushButton("📋 הדבק")
        b_paste.setToolTip("הדבקת שם חבילה שהועתק (למשל מתפריט הלחיצה הימנית בטבלה)")
        b_paste.clicked.connect(self._adb_paste_pkg)
        row_un.addWidget(b_paste)
        b_uninstall = QPushButton("🗑️ הסר (מסומנות / לפי שם)")
        b_uninstall.setToolTip("מסיר את כל האפליקציות שסומנו ✔ בטבלה; "
                               "אם לא סומנה אף אחת — את החבילה שבשדה")
        b_uninstall.clicked.connect(self._adb_uninstall)
        row_un.addWidget(b_uninstall)
        row_un.addWidget(self._help_dot("adb_uninstall"))
        ga.addLayout(row_un)

        # התקנה מקובץ APK
        row_in = QHBoxLayout()
        row_in.addWidget(QLabel("קובץ APK להתקנה:"))
        self.adb_apk_edit = QLineEdit()
        self.adb_apk_edit.setPlaceholderText("בחר קובץ \u200e.apk מהמחשב…")
        row_in.addWidget(self.adb_apk_edit, 1)
        b_apk_browse = QPushButton("…")
        b_apk_browse.setMaximumWidth(52)
        b_apk_browse.clicked.connect(self._adb_browse_apk)
        row_in.addWidget(b_apk_browse)
        ga.addLayout(row_in)
        fmt_lbl = QLabel("פורמטים נתמכים: APK · XAPK · APKM · APKS "
                         "(חבילות מפוצלות מותקנות אוטומטית).")
        fmt_lbl.setStyleSheet("color:#8b949e;")
        fmt_lbl.setWordWrap(True)
        ga.addWidget(fmt_lbl)
        row_opts = QHBoxLayout()
        self.adb_reinstall_check = QCheckBox("עדכן אם האפליקציה קיימת (-r)")
        self.adb_reinstall_check.setToolTip("מאפשר התקנה על גבי גרסה קיימת במקום כישלון")
        self.adb_reinstall_check.setChecked(True)
        row_opts.addWidget(self.adb_reinstall_check)
        self.adb_downgrade_check = QCheckBox("אפשר גם גרסה ישנה יותר (-d)")
        self.adb_downgrade_check.setToolTip(
            "מאפשר התקנה של גרסה נמוכה מהמותקנת (VERSION_DOWNGRADE)")
        row_opts.addWidget(self.adb_downgrade_check)
        b_install = QPushButton("📦 התקן (APK · XAPK · APKM · APKS)")
        b_install.clicked.connect(self._adb_install)
        row_opts.addWidget(b_install)
        row_opts.addWidget(self._help_dot("adb_install"))
        row_opts.addStretch(1)
        ga.addLayout(row_opts)

        # רשימת חבילות מותקנות (קריאה בלבד) — לעזרה באיתור שם חבילה
        row_list = QHBoxLayout()
        self.adb_sys_check = QCheckBox("הצג גם אפליקציות מערכת")
        row_list.addWidget(self.adb_sys_check)
        b_list = QPushButton("📋 רשימת אפליקציות מותקנות")
        b_list.clicked.connect(self._adb_list_packages)
        row_list.addWidget(b_list)
        b_info = QPushButton("ℹ️ מידע על האפליקציה")
        b_info.setToolTip("מידע מלא על האפליקציה שנבחרה (אפשר גם בלחיצה כפולה על שורה)")
        b_info.clicked.connect(self._adb_app_info)
        row_list.addWidget(b_info)
        row_list.addWidget(self._help_dot("adb_list"))
        row_list.addStretch(1)
        ga.addLayout(row_list)
        # טבלת אפליקציות: תמונה + שם אמיתי, חבילה, גרסה, גודל
        from PySide6.QtCore import QSize
        self.adb_apps_table = QTableWidget(0, 4)
        self.adb_apps_table.setHorizontalHeaderLabels(["אפליקציה", "שם חבילה", "גרסה", "גודל"])
        hh = self.adb_apps_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.adb_apps_table.setIconSize(QSize(40, 40))
        self.adb_apps_table.verticalHeader().setDefaultSectionSize(48)
        self.adb_apps_table.verticalHeader().setVisible(False)
        self.adb_apps_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.adb_apps_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.adb_apps_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.adb_apps_table.setMinimumHeight(320)
        self.adb_apps_table.itemClicked.connect(self._adb_app_clicked)
        self.adb_apps_table.itemDoubleClicked.connect(lambda _it: self._adb_app_info())
        # לחיצה ימנית: העתקת שם חבילה / העברה לשדה ההסרה / מידע / שחזור
        self.adb_apps_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.adb_apps_table.customContextMenuRequested.connect(self._apps_context_menu)
        ga.addWidget(self.adb_apps_table)
        self._apps_gen = 0
        self._apps_rows: dict = {}
        # הודעות התקנה/הסרה/טעינה
        self.adb_pkgs_view = QTextEdit()
        self.adb_pkgs_view.setReadOnly(True)
        self.adb_pkgs_view.setPlaceholderText(
            "הודעות: טעינת הרשימה, התקנה והסרה. לחיצה על שורה בטבלה ממלאת את שדה ההסרה.")
        self.adb_pkgs_view.setMaximumHeight(70)
        ga.addWidget(self.adb_pkgs_view)

        v.addWidget(gb_apps)

        # סייר קבצים (ADB)
        gb_fs = QGroupBox("סייר קבצים (ADB)")
        gfs = QVBoxLayout(gb_fs)
        fs_note = QLabel(
            "עיון בקבצים שבמכשיר, הורדה/העלאה, מחיקה, שינוי שם ועריכת טקסט. "
            "בלי root הגישה מוגבלת ל-/sdcard.")
        fs_note.setWordWrap(True)
        fs_note.setStyleSheet("color:#8b949e;")
        gfs.addWidget(fs_note)
        path_row = QHBoxLayout()
        b_fs_up = QPushButton("⬆️ למעלה")
        b_fs_up.clicked.connect(self._fs_up)
        path_row.addWidget(b_fs_up)
        b_fs_home = QPushButton("🏠 /sdcard")
        b_fs_home.clicked.connect(lambda: self._fs_load("/sdcard"))
        path_row.addWidget(b_fs_home)
        self.fs_path_edit = QLineEdit("/sdcard")
        self.fs_path_edit.returnPressed.connect(
            lambda: self._fs_load(self.fs_path_edit.text().strip() or "/sdcard"))
        path_row.addWidget(self.fs_path_edit, 1)
        b_fs_go = QPushButton("↵ עבור")
        b_fs_go.clicked.connect(
            lambda: self._fs_load(self.fs_path_edit.text().strip() or "/sdcard"))
        path_row.addWidget(b_fs_go)
        b_fs_refresh = QPushButton("🔄")
        b_fs_refresh.setToolTip("רענן")
        b_fs_refresh.setMaximumWidth(52)
        b_fs_refresh.clicked.connect(self._fs_refresh)
        path_row.addWidget(b_fs_refresh)
        gfs.addLayout(path_row)

        self.fs_table = QTableWidget(0, 3)
        self.fs_table.setHorizontalHeaderLabels(["שם", "גודל", "סוג"])
        fhh = self.fs_table.horizontalHeader()
        fhh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        fhh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        fhh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.fs_table.verticalHeader().setVisible(False)
        self.fs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.fs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.fs_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.fs_table.setMinimumHeight(260)
        self.fs_table.itemDoubleClicked.connect(self._fs_double_clicked)
        gfs.addWidget(self.fs_table)

        fs_btns = QHBoxLayout()
        for text, slot in (("⬇️ הורד", self._fs_download),
                           ("⬆️ העלה קובץ", self._fs_upload),
                           ("✏️ ערוך טקסט", self._fs_edit),
                           ("📁 תיקייה חדשה", self._fs_mkdir),
                           ("✏️ שנה שם", self._fs_rename),
                           ("🗑️ מחק", self._fs_delete)):
            b = QPushButton(text)
            if "מחק" in text:
                b.setObjectName("btnWarn")
            b.clicked.connect(slot)
            fs_btns.addWidget(b)
        fs_btns.addStretch(1)
        gfs.addLayout(fs_btns)
        self._fs_entries: list = []
        self._fs_cwd = "/sdcard"
        v.addWidget(gb_fs)

        # הרשאות ניהול מלאות למכשיר (device owner / device admin)
        gb_admin = QGroupBox("הרשאות ניהול מלאות למכשיר (למשל אפליקציות סינון)")
        gadm = QVBoxLayout(gb_admin)
        adm_note = QLabel(
            "מעניק לאפליקציה הרשאות בעלים על המכשיר (device owner) — נדרש לרוב "
            "אפליקציות סינון/בקרת-הורים כדי שלא ניתן יהיה להסירן.\n"
            "⚠️ דרישות: המכשיר חייב להיות ללא חשבונות (כולל חשבון Google) — "
            "מומלץ לבצע מיד אחרי איפוס לפני הוספת חשבונות.\n"
            "⚠️ הסרת הבעלות בהמשך עלולה לדרוש איפוס להגדרות יצרן.")
        adm_note.setWordWrap(True)
        adm_note.setStyleSheet("color:#c9a227;")
        gadm.addWidget(adm_note)
        row_adm = QHBoxLayout()
        row_adm.addWidget(QLabel("שם חבילה:"))
        self.adb_admin_edit = QLineEdit()
        self.adb_admin_edit.setPlaceholderText("com.example.filter  (או בחר שורה בטבלה)")
        row_adm.addWidget(self.adb_admin_edit, 1)
        b_adm_paste = QPushButton("📋 הדבק")
        b_adm_paste.clicked.connect(
            lambda: self.adb_admin_edit.setText(
                (QApplication.clipboard().text() or "").strip().splitlines()[0]
                if (QApplication.clipboard().text() or "").strip() else ""))
        row_adm.addWidget(b_adm_paste)
        gadm.addLayout(row_adm)
        row_adm2 = QHBoxLayout()
        b_owner = QPushButton("👑 הענק בעלות מלאה (device owner)")
        b_owner.setObjectName("btnWarn")
        b_owner.clicked.connect(lambda: self._adb_grant_admin(owner=True))
        row_adm2.addWidget(b_owner)
        b_admin = QPushButton("🛡️ הפעל כמנהל-התקן (device admin)")
        b_admin.clicked.connect(lambda: self._adb_grant_admin(owner=False))
        row_adm2.addWidget(b_admin)
        row_adm2.addWidget(self._help_dot("adb_admin"))
        row_adm2.addStretch(1)
        gadm.addLayout(row_adm2)
        v.addWidget(gb_admin)

        v.addStretch(1)
        return w

    def _adb_browse_apk(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר קובץ APK", "", "Android packages (*.apk *.apkm *.xapk *.apks);;All files (*)")
        if path:
            self.adb_apk_edit.setText(path)

    def _checked_packages(self) -> list[str]:
        """חבילות שסומנו בתיבת הסימון בטבלה."""
        t = self.adb_apps_table
        out = []
        for r in range(t.rowCount()):
            it, p = t.item(r, 0), t.item(r, 1)
            if it is not None and p is not None and it.checkState() == Qt.CheckState.Checked:
                out.append(p.text())
        return out

    def _adb_uninstall(self):
        pkgs = self._checked_packages()
        if not pkgs:
            one = self.adb_pkg_edit.text().strip()
            if one:
                pkgs = [one]
        if not pkgs:
            QMessageBox.warning(self, "לא נבחרה אפליקציה",
                                "סמן ✔ אפליקציות בטבלה (אפשר כמה), או הזן שם חבילה בשדה.")
            return
        adb = config.find_adb_exe()
        if not adb:
            QMessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
            return
        listing = "\n".join(pkgs[:15]) + (f"\n…ועוד {len(pkgs) - 15}" if len(pkgs) > 15 else "")
        keep = QMessageBox.question(
            self, "הסרת אפליקציות",
            f"להסיר {len(pkgs)} אפליקציות?\n\n{listing}\n\n"
            "'כן' = הסרה מלאה (כולל נתונים).\n"
            "'לא' = הסרה תוך שמירת נתונים ומטמון (-k).",
            _YES | _NO, _NO)
        if keep == _NO:
            full = QMessageBox.question(
                self, "אישור הסרה",
                f"להסיר {len(pkgs)} אפליקציות עם שמירת נתונים?\n"
                "(התקנה מחדש תחזיר את הנתונים)",
                _YES | _NO, _NO)
            if full != _YES:
                return
            keep_data = True
        else:
            keep_data = False
        self._say("info", f"מסיר {len(pkgs)} אפליקציות")
        # מד התקדמות להסרה
        if getattr(self, "_clear_timer", None):
            self._clear_timer.stop()
        self.progress.setStyleSheet("")
        self.progress.setRange(0, len(pkgs))
        self.progress.setValue(0)
        self._adb_busy = True     # הבדיקה האוטומטית ממתינה בזמן ההסרה

        def work():
            results = []
            try:
                for n, pkg in enumerate(pkgs, 1):
                    ok, msg = devinfo.adb_uninstall(str(adb), pkg, keep_data=keep_data)
                    results.append((pkg, ok, msg))
                    self._say("success" if ok else "error",
                              f"{pkg}: {msg}" if ok else f"הסרת {pkg} נכשלה: {msg}")
                    bus.adb_uninstall_progress.emit((n, len(pkgs), pkg, ok, msg))
            finally:
                self._adb_busy = False
            good = [r for r in results if r[1]]
            bad = [r for r in results if not r[1]]
            parts = []
            if good:
                parts.append(f"✅ הוסרו בהצלחה ({len(good)}):\n" + "\n".join(
                    f"• {p}" + ("  — הוסרה מהמשתמש (אפליקציית מערכת)" if "למשתמש" in m else "")
                    for p, _o, m in good))
            if bad:
                parts.append(f"❌ ההסרה נכשלה ({len(bad)}):\n" + "\n".join(
                    f"• {p}: {m}" for p, _o, m in bad))
            bus.adb_op_result.emit((not bad, "הסרת אפליקציות", "\n\n".join(parts)))

        threading.Thread(target=work, daemon=True).start()

    def _on_uninstall_progress(self, payload):
        n, total, pkg, ok, msg = payload
        self.progress.setValue(n)
        self.status_label.setText(f"מסיר אפליקציות… {n}/{total} ({n * 100 // total}%)")
        if ok:
            self._mark_app_row(pkg, "for_user" if "למשתמש" in msg else "removed")

    def _mark_app_row(self, pkg: str, state: str):
        """מסמן שורה בטבלה: for_user = הוסרה מהמשתמש, removed = הוסרה, "" = רגילה."""
        r = self._apps_rows.get(pkg)
        t = self.adb_apps_table
        if r is None or t.item(r, 0) is None:
            return
        app = getattr(self, "_apps_by_pkg", {}).get(pkg)
        base = app.display_name if app else pkg
        if app and app.system:
            base += "  (מערכת)"
        suffix = {"for_user": "  (הוסרה מהמשתמש)", "removed": "  (הוסרה)"}.get(state, "")
        it = t.item(r, 0)
        it.setText(base + suffix)
        if state:
            it.setCheckState(Qt.CheckState.Unchecked)
        color = QColor("#8b949e") if state else None
        for c in range(t.columnCount()):
            cell = t.item(r, c)
            if cell is not None:
                if color is not None:
                    cell.setForeground(color)
                else:
                    cell.setData(Qt.ItemDataRole.ForegroundRole, None)
        if app is not None:
            app.removed_for_user = (state == "for_user")

    def _on_op_result(self, payload):
        ok, title, text = payload
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 1)
        self.progress.setValue(self.progress.maximum())
        self.progress.setStyleSheet(
            "QProgressBar::chunk { background-color: #2ea043; }" if ok else "")
        self.status_label.setText(f"{title}: {'הסתיים בהצלחה' if ok else '❌ נכשל'}")
        if getattr(self, "_clear_timer", None):
            self._clear_timer.start()
        first = text.splitlines()[0] if text else ""
        self.adb_pkgs_view.setPlainText(first)
        if ok:
            QMessageBox.information(self, f"✅ {title}", text)
        else:
            QMessageBox.warning(self, f"❌ {title}", text)

    def _apps_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        pkg = self._selected_app_package()
        if not pkg:
            return
        app = getattr(self, "_apps_by_pkg", {}).get(pkg)
        m = QMenu(self)
        a_copy = m.addAction("📋 העתק שם חבילה")
        a_field = m.addAction("➡️ העבר לשדה ההסרה")
        a_info = m.addAction("ℹ️ מידע על האפליקציה")
        a_restore = None
        if app is not None and app.removed_for_user:
            m.addSeparator()
            a_restore = m.addAction("♻️ שחזר אפליקציה (הוסרה מהמשתמש)")
        chosen = m.exec(self.adb_apps_table.viewport().mapToGlobal(pos))
        if chosen == a_copy:
            QApplication.clipboard().setText(pkg)
            self.status_label.setText(f"הועתק: {pkg}")
        elif chosen == a_field:
            self.adb_pkg_edit.setText(pkg)
        elif chosen == a_info:
            self._adb_app_info()
        elif a_restore is not None and chosen == a_restore:
            self._adb_restore(pkg)

    def _adb_paste_pkg(self):
        text = (QApplication.clipboard().text() or "").strip().splitlines()
        if text:
            self.adb_pkg_edit.setText(text[0].strip())

    def _adb_restore(self, pkg: str):
        adb = config.find_adb_exe()
        if not adb:
            return

        def work():
            ok, msg = devinfo.adb_restore(str(adb), pkg)
            self._say("success" if ok else "error", f"שחזור {pkg}: {msg}")
            bus.adb_op_result.emit((ok, "שחזור אפליקציה",
                                    f"✅ {pkg} שוחזרה בהצלחה" if ok
                                    else f"❌ שחזור {pkg} נכשל:\n{msg}"))
            if ok:
                bus.adb_app_restored.emit(pkg)

        threading.Thread(target=work, daemon=True).start()

    def _adb_install(self):
        apk = Path(self.adb_apk_edit.text().strip())
        if not apk or not apk.is_file():
            QMessageBox.warning(self, "קובץ חסר", "בחר קובץ APK תקין")
            return
        adb = config.find_adb_exe()
        if not adb:
            QMessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
            return
        reinstall = self.adb_reinstall_check.isChecked()
        allow_downgrade = self.adb_downgrade_check.isChecked()
        self._say("info", f"מתקין: {apk.name}")
        self.adb_pkgs_view.setPlainText("מתקין… (התקנה עשויה להימשך עד דקה)")
        if getattr(self, "_clear_timer", None):
            self._clear_timer.stop()
        self.progress.setStyleSheet("")
        self.progress.setRange(0, 0)   # 'רץ' עד סיום ההתקנה

        def work():
            ok, msg = devinfo.adb_install(str(adb), apk, reinstall=reinstall,
                                          allow_downgrade=allow_downgrade)
            self._say("success" if ok else "error",
                      f"{apk.name} הותקן בהצלחה" if ok else f"התקנת {apk.name} נכשלה: {msg}")
            # חסימת שדרוג-לאחור גם עם -d → מציעים הסרה+התקנה (ב-thread הראשי)
            if (not ok) and allow_downgrade and "חוסם התקנת גרסה ישנה" in msg:
                bus.adb_install_downgrade.emit(str(apk))
                return
            bus.adb_op_result.emit((ok, "התקנת APK",
                                    f"✅ {apk.name} הותקן בהצלחה." if ok
                                    else f"❌ התקנת {apk.name} נכשלה:\n{msg}"))

        threading.Thread(target=work, daemon=True).start()

    def _on_install_downgrade(self, apk_str: str):
        apk = Path(apk_str)
        adb = config.find_adb_exe()
        if not adb:
            return
        keep = QMessageBox.question(
            self, "התקנת גרסה ישנה חסומה",
            f"אנדרואיד חוסם התקנת גרסה ישנה מהמותקנת ({apk.name}).\n\n"
            "אפשר להסיר קודם את הגרסה המותקנת ואז להתקין את הישנה.\n\n"
            "'כן' = הסרה מלאה (נתוני האפליקציה יימחקו).\n"
            "'לא' = הסרה תוך שמירת נתונים (-k) — לא תמיד עובד.",
            _YES | _NO | QMessageBox.StandardButton.Cancel, _NO)
        if keep == QMessageBox.StandardButton.Cancel:
            return
        keep_data = (keep == _NO)
        self._say("info", f"מסיר ומתקין מחדש: {apk.name}")
        self.progress.setStyleSheet("")
        self.progress.setRange(0, 0)
        self._adb_busy = True

        def work():
            try:
                ok, msg = devinfo.adb_install_replacing(str(adb), apk, keep_data=keep_data)
            finally:
                self._adb_busy = False
            self._say("success" if ok else "error", f"{apk.name}: {msg}")
            bus.adb_op_result.emit((ok, "התקנת APK (הסרה+התקנה)",
                                    f"✅ {apk.name}\n{msg}" if ok
                                    else f"❌ {apk.name}\n{msg}"))

        threading.Thread(target=work, daemon=True).start()

    def _adb_grant_admin(self, owner: bool):
        pkg = self.adb_admin_edit.text().strip() or self._selected_app_package() or ""
        pkg = pkg.split("/")[0].strip()
        if not pkg:
            QMessageBox.warning(self, "חסר שם חבילה",
                                "הזן שם חבילה או בחר אפליקציה בטבלה.")
            return
        adb = config.find_adb_exe()
        if not adb:
            QMessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
            return
        kind = "בעלות מלאה על המכשיר (device owner)" if owner else "מנהל-התקן (device admin)"
        warn = ("⚠️ הענקת בעלות מלאה דורשת מכשיר ללא חשבונות (כולל Google), "
                "והסרתה בהמשך עלולה לדרוש איפוס יצרן.\n\n" if owner else "")
        if QMessageBox.question(
                self, "אישור הענקת הרשאות",
                f"להעניק ל-{pkg} {kind}?\n\n{warn}להמשיך?",
                _YES | _NO, _NO) != _YES:
            return
        self._say("info", f"מעניק {kind} ל-{pkg}")
        self.progress.setStyleSheet("")
        self.progress.setRange(0, 0)
        self._adb_busy = True

        def work():
            try:
                comp = devinfo.adb_find_admin_receiver(str(adb), pkg)
                guessed = not comp
                if not comp:
                    comp = f"{pkg}/.DeviceAdminReceiver"   # ניחוש — אם לא נמצא receiver
                if owner:
                    ok, msg = devinfo.adb_set_device_owner(str(adb), comp)
                else:
                    ok, msg = devinfo.adb_set_active_admin(str(adb), comp)
            finally:
                self._adb_busy = False
            note = ""
            if not ok and guessed:
                note = ("\n\n⚠️ לא נמצא ברכיבי האפליקציה receiver של מנהל-התקן "
                        "(BIND_DEVICE_ADMIN). ייתכן שהאפליקציה אינה תומכת בהפיכה "
                        "למנהל מכשיר, או שהיא לא הותקנה כראוי.")
            self._say("success" if ok else "error", f"{pkg}: {msg}")
            bus.adb_op_result.emit((ok, "הענקת הרשאות ניהול",
                                    f"✅ {pkg}\n{msg}\n(רכיב: {comp})" if ok
                                    else f"❌ {pkg}\n{msg}\n(רכיב שנוסה: {comp}){note}"))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ סייר קבצים (ADB)
    def _fs_adb(self):
        adb = config.find_adb_exe()
        if not adb:
            QMessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
        return adb

    def _fs_load(self, path: str):
        adb = self._fs_adb()
        if not adb:
            return
        from ..core import adb_files
        path = path or "/sdcard"
        self.fs_path_edit.setText(path)
        self.fs_table.setRowCount(0)
        self._adb_busy = True

        def work():
            try:
                entries, err = adb_files.list_dir(str(adb), path)
            finally:
                self._adb_busy = False
            bus.adb_fs_listing.emit((path, entries, err))

        threading.Thread(target=work, daemon=True).start()

    def _on_fs_listing(self, payload):
        path, entries, err = payload
        if err:
            self._say("error", f"סייר קבצים: {err}")
            QMessageBox.warning(self, "שגיאת גישה", err)
            return
        self._fs_entries = entries
        self._fs_cwd = path
        self.fs_path_edit.setText(path)
        t = self.fs_table
        t.setRowCount(0)
        for e in entries:
            r = t.rowCount()
            t.insertRow(r)
            icon = "📁 " if e.is_dir else ("🔗 " if e.is_link else "📄 ")
            t.setItem(r, 0, QTableWidgetItem(icon + e.name))
            t.setItem(r, 1, QTableWidgetItem(e.size_str))
            t.setItem(r, 2, QTableWidgetItem(
                "תיקייה" if e.is_dir else ("קישור" if e.is_link else "קובץ")))
        self._say("info", f"סייר: {len(entries)} פריטים ב-{path}")

    def _fs_refresh(self):
        self._fs_load(self._fs_cwd)

    def _fs_up(self):
        from ..core import adb_files
        self._fs_load(adb_files.posix_parent(self._fs_cwd))

    def _fs_selected(self):
        r = self.fs_table.currentRow()
        if r < 0 or r >= len(self._fs_entries):
            QMessageBox.information(self, "בחר פריט", "בחר קובץ או תיקייה מהרשימה.")
            return None
        return self._fs_entries[r]

    def _fs_double_clicked(self, _item):
        r = self.fs_table.currentRow()
        if r < 0 or r >= len(self._fs_entries):
            return
        e = self._fs_entries[r]
        if e.is_dir:
            self._fs_load(e.path)
        elif e.is_text:
            self._fs_edit()
        else:
            self._fs_download()

    def _fs_op_async(self, title: str, fn, refresh: bool = True):
        self._adb_busy = True

        def work():
            try:
                ok, msg = fn()
            except Exception as e:      # noqa: BLE001
                ok, msg = False, str(e)
            finally:
                self._adb_busy = False
            bus.adb_fs_op.emit((ok, title, msg, refresh))

        threading.Thread(target=work, daemon=True).start()

    def _on_fs_op(self, payload):
        ok, title, text, refresh = payload
        self._say("success" if ok else "error", f"{title}: {text}")
        if ok:
            QMessageBox.information(self, f"✅ {title}", text)
            if refresh:
                self._fs_refresh()
        else:
            QMessageBox.warning(self, f"❌ {title}", text)

    def _fs_download(self):
        e = self._fs_selected()
        if not e:
            return
        adb = self._fs_adb()
        if not adb:
            return
        from ..core import adb_files
        if e.is_dir:
            dest_dir = QFileDialog.getExistingDirectory(self, "בחר תיקיית יעד להורדה")
            if not dest_dir:
                return
            local = Path(dest_dir) / e.name
        else:
            chosen, _ = QFileDialog.getSaveFileName(self, "שמור בשם", e.name)
            if not chosen:
                return
            local = Path(chosen)
        self._say("info", f"מוריד: {e.name}")
        self._fs_op_async("הורדת קובץ",
                          lambda: adb_files.pull(str(adb), e.path, local), refresh=False)

    def _fs_upload(self):
        adb = self._fs_adb()
        if not adb:
            return
        from ..core import adb_files
        path, _ = QFileDialog.getOpenFileName(self, "בחר קובץ להעלאה")
        if not path:
            return
        self._say("info", f"מעלה: {Path(path).name}")
        self._fs_op_async("העלאת קובץ",
                          lambda: adb_files.push(str(adb), Path(path), self._fs_cwd))

    def _fs_mkdir(self):
        adb = self._fs_adb()
        if not adb:
            return
        from ..core import adb_files
        name, ok = QInputDialog.getText(self, "תיקייה חדשה", "שם התיקייה:")
        if not ok or not name.strip():
            return
        self._fs_op_async("יצירת תיקייה",
                          lambda: adb_files.mkdir(str(adb), self._fs_cwd, name.strip()))

    def _fs_rename(self):
        e = self._fs_selected()
        if not e:
            return
        adb = self._fs_adb()
        if not adb:
            return
        from ..core import adb_files
        name, ok = QInputDialog.getText(self, "שינוי שם", "שם חדש:", text=e.name)
        if not ok or not name.strip():
            return
        self._fs_op_async("שינוי שם",
                          lambda: adb_files.rename(str(adb), e.path, name.strip()))

    def _fs_delete(self):
        e = self._fs_selected()
        if not e:
            return
        adb = self._fs_adb()
        if not adb:
            return
        from ..core import adb_files
        what = "התיקייה וכל תוכנה" if e.is_dir else "הקובץ"
        if QMessageBox.warning(
                self, "מחיקה",
                f"למחוק לצמיתות את {what}?\n\n{e.path}\n\n"
                "⚠️ אין 'סל מיחזור' ב-ADB — המחיקה בלתי הפיכה.",
                _YES | _NO, _NO) != _YES:
            return
        self._fs_op_async("מחיקה", lambda: adb_files.delete(str(adb), e.path, e.is_dir))

    def _fs_edit(self):
        e = self._fs_selected()
        if not e:
            return
        if e.is_dir:
            QMessageBox.information(self, "עריכה", "בחר קובץ טקסט, לא תיקייה.")
            return
        adb = self._fs_adb()
        if not adb:
            return
        from ..core import adb_files
        tmp_dir = config.WORKSPACE_DIR / "fs_edit"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        local = tmp_dir / e.name
        remote = e.path
        self._say("info", f"מושך לעריכה: {e.name}")
        self._adb_busy = True

        def work():
            try:
                ok, msg = adb_files.pull(str(adb), remote, local)
            finally:
                self._adb_busy = False
            bus.adb_fs_edit_ready.emit((ok, remote, str(local), msg))

        threading.Thread(target=work, daemon=True).start()

    def _on_fs_edit_ready(self, payload):
        ok, remote, local, msg = payload
        if not ok:
            QMessageBox.warning(self, "עריכה", f"המשיכה נכשלה:\n{msg}")
            return
        try:
            text = Path(local).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            QMessageBox.warning(self, "עריכה", f"לא ניתן לקרוא את הקובץ: {e}")
            return
        dlg = _TextEditDialog(self, Path(local).name, text)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            Path(local).write_text(dlg.text(), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "עריכה", f"שמירה מקומית נכשלה: {e}")
            return
        adb = self._fs_adb()
        if not adb:
            return
        parent = adb_files.posix_parent(remote)
        self._say("info", f"מעלה בחזרה: {Path(remote).name}")
        self._fs_op_async("שמירת קובץ",
                          lambda: adb_files.push(str(adb), Path(local), parent), refresh=True)

    def _adb_list_packages(self):
        adb = config.find_adb_exe()
        if not adb:
            QMessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
            return
        include_sys = self.adb_sys_check.isChecked()
        self._apps_gen += 1
        gen = self._apps_gen
        self.adb_apps_table.setRowCount(0)
        self.adb_pkgs_view.setPlainText("קורא רשימת אפליקציות…")
        self._apps_loading = True
        if getattr(self, "_clear_timer", None):
            self._clear_timer.stop()
        self.progress.setStyleSheet("")
        self.progress.setRange(0, 0)   # 'רץ' עד שמתקבלת הרשימה

        def work():
            try:
                _load(self)
            finally:
                if self._apps_gen == gen:
                    self._apps_loading = False

        def _load(self):
            from ..core import apk_info
            apps = apk_info.list_apps(str(adb), include_system=include_sys)
            if not apps:
                bus.adb_pkgs_text.emit(
                    "לא נמצאו אפליקציות (או שאין מכשיר ב-ADB).\n"
                    "נסה לסמן 'הצג גם אפליקציות מערכת'.")
                return
            bus.adb_apps_list.emit((gen, apps))
            bus.adb_pkgs_text.emit(
                f"נמצאו {len(apps)} אפליקציות — טוען שמות ותמונות… "
                "(בפעם הראשונה זה לוקח זמן; אחר כך זה נשמר ומופיע מיד)")
            for n, app in enumerate(apps, 1):
                if self._apps_gen != gen:
                    return                      # נלחץ שוב — הטעינה הישנה נעצרת
                try:
                    apk_info.load_app(str(adb), app)
                except Exception as e:          # אפליקציה אחת לא תעצור את כולן
                    app.note = str(e)[:120]
                bus.adb_app_update.emit((gen, app, n, len(apps)))
            if self._apps_gen == gen:
                bus.adb_pkgs_text.emit(f"✅ נטענו {len(apps)} אפליקציות עם שמות ותמונות.")
                self._say("success", f"נטענו {len(apps)} אפליקציות")

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- ערוץ תקשורת
    def _on_tool_combo(self, _i):
        tool = self.tool_combo.currentData() or "none"
        if tool == self._active_tool:
            return
        self._active_tool = tool
        self._last_probe_mode = None
        if tool == "none":
            self._say("info", "ערוץ תקשורת: לא נבחר — אין חיפוש מכשיר עד שתבחר ערוץ.")
            return
        names = {"auto": "אוטומטי", "adb": "ADB", "fastboot": "Fastboot",
                 "brom": "mtkclient (BROM)"}
        self._say("info", f"ערוץ תקשורת: {names.get(tool, tool)} — הזיהוי האוטומטי "
                          "ישתמש רק בו ולא ינסה דרכים אחרות.")
        self._probe_device()

    def _set_active_tool(self, tool: str):
        """קובע ערוץ (מבחירת המשתמש או נעילה אחרי זיהוי ראשון)."""
        i = self.tool_combo.findData(tool)
        if i < 0:
            return
        self._active_tool = tool
        self.tool_combo.blockSignals(True)
        self.tool_combo.setCurrentIndex(i)
        self.tool_combo.blockSignals(False)

    # ---------------------------------------------------------- בוטלאודר דרך ADB
    def _adb_boot_read(self):
        adb = config.find_adb_exe()
        if not adb:
            QMessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
            return
        self.adb_boot_view.setPlainText("בודק…")

        def work():
            from ..core import adb_boot
            bus.adb_boot_state.emit(adb_boot.read_state(str(adb)))

        threading.Thread(target=work, daemon=True).start()

    def _set_adb_boot(self, st: dict):
        from ..core import adb_boot
        text = adb_boot.summarize(st)
        self.adb_boot_view.setPlainText(text)
        self._say("info", text.splitlines()[0])
        if st.get("locked") is True:
            self._set_header_boot("🔒 נעול")
        elif st.get("locked") is False:
            self._set_header_boot("🔓 פתוח")

    def _adb_boot_change(self, unlock: bool):
        from ..core import adb_boot
        from ..core.jobs import Job, Step
        adb = config.find_adb_exe()
        if not adb or not config.find_fastboot_exe():
            QMessageBox.warning(self, "חסר כלי",
                                "צריך גם adb.exe וגם fastboot.exe בתיקיית tools.")
            return
        st = adb_boot.read_state(str(adb))
        if unlock and st.get("oem_allowed") is False:
            QMessageBox.warning(
                self, "ביטול נעילת OEM כבוי",
                "לפני פתיחת הבוטלאודר צריך להפעיל במכשיר:\n"
                "הגדרות ← אפשרויות מפתחים ← 'ביטול נעילת OEM' (OEM unlocking).\n\n"
                "הפעל, ואז נסה שוב.")
            return
        if unlock:
            warn = ("⚠️ אזהרה חמורה: פתיחת הבוטלאודר מוחקת את כל הנתונים במכשיר — "
                    "תמונות, אפליקציות, הגדרות וכל נתוני המשתמש!\n\n"
                    "ודא שיש לך גיבוי. להמשיך?")
        else:
            warn = ("⚠️ נעילת הבוטלאודר מוחקת גם היא את הנתונים במכשיר ברוב המכשירים.\n"
                    "ואם מותקנת במכשיר מערכת לא מקורית (ROM מותאם / Magisk) — "
                    "נעילה עלולה למנוע מהמכשיר לעלות!\n\nלהמשיך?")
        if QMessageBox.warning(self, "פתיחת בוטלאודר" if unlock else "נעילת בוטלאודר",
                               warn, _YES | _NO, _NO) != _YES:
            return
        verb = "פתיחת" if unlock else "נעילת"

        def build():
            job = Job(f"{verb} בוטלאודר (ADB → Fastboot)", [
                Step("אתחול למצב Fastboot", adb_boot.RebootToBootloader()),
                Step("המתנה למכשיר במצב Fastboot", adb_boot.WaitForFastboot(90)),
                Step(f"{verb} הבוטלאודר", adb_boot.FlashingLockCommand(unlock)),
            ], danger=True)
            job.notes.append("המכשיר יעבור למצב Fastboot. בסוף — אשר על מסך הטלפון "
                              "עם כפתורי הווליום, ולחץ על לחצן ההפעלה לאישור.")
            job.notes.append("הנתונים במכשיר יימחקו.")
            return job

        self._retry_action = None
        if self._request(self._plan(build)):
            self._set_active_tool("fastboot")   # המשתמש בחר לעבור ל-Fastboot

    def _adb_reboot_bootloader(self):
        """מעבר מהמכשיר הדלוק (ADB) למצב Fastboot — בלי לפתוח/לנעול את הבוטלאודר."""
        from ..core import adb_boot, device_info
        from ..core.jobs import Job, Step
        adb = config.find_adb_exe()
        if not adb:
            QMessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
            return
        if not device_info.adb_devices_connected(str(adb)):
            QMessageBox.warning(
                self, "לא נמצא מכשיר ב-ADB",
                "כדי לעבור למצב Fastboot צריך מכשיר דלוק ומחובר ב-ADB.\n\n"
                "חבר את המכשיר בכבל USB ואשר במסך המכשיר את בקשת ניפוי הבאגים.")
            return

        def build():
            job = Job("מעבר למצב Fastboot\u200f (ADB → Fastboot)\u200f", [
                Step("אתחול למצב Fastboot", adb_boot.RebootToBootloader()),
                Step("המתנה למכשיר במצב Fastboot", adb_boot.WaitForFastboot(60)),
            ])
            job.notes.append("המכשיר יאותחל למצב Fastboot. הבוטלאודר עצמו לא נפתח ולא ננעל, "
                              "והנתונים במכשיר לא נמחקים.")
            return job

        self._retry_action = None
        if self._request(self._plan(build)):
            self._set_active_tool("fastboot")

    def _generic_app_icon(self):
        from PySide6.QtWidgets import QStyle
        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def _app_icon(self, app):
        """בונה אייקון להצגה. אייקון אדפטיבי = רקע (צבע/תמונה) + שכבה קדמית
        שנחתכת למרכז (כמו שאנדרואיד מציג)."""
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap
        if not app.icon_file:
            return self._generic_app_icon()
        fg = QPixmap(app.icon_file)
        if fg.isNull():
            return self._generic_app_icon()
        size = 96
        out = QPixmap(size, size)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if app.adaptive:
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(0, 0, size, size), 22, 22)
            p.setClipPath(clip)
            if app.icon_bg_color:
                p.fillRect(0, 0, size, size, QColor(app.icon_bg_color))
            elif app.icon_bg_file:
                bg = QPixmap(app.icon_bg_file)
                if not bg.isNull():
                    p.drawPixmap(QRectF(-size / 4, -size / 4, size * 1.5, size * 1.5),
                                 bg, QRectF(bg.rect()))
            else:
                p.fillRect(0, 0, size, size, QColor("#FFFFFF"))
            # השכבה הקדמית היא 108dp מתוכם 72dp נראים — מגדילים פי 1.5 וחותכים
            p.drawPixmap(QRectF(-size / 4, -size / 4, size * 1.5, size * 1.5),
                         fg, QRectF(fg.rect()))
        else:
            p.drawPixmap(QRectF(0, 0, size, size), fg, QRectF(fg.rect()))
        p.end()
        return QIcon(out)

    def _on_apps_list(self, payload):
        gen, apps = payload
        if gen != self._apps_gen:
            return
        t = self.adb_apps_table
        t.setRowCount(len(apps))
        self._apps_rows = {}
        self._apps_by_pkg = {a.package: a for a in apps}
        generic = self._generic_app_icon()
        for r, app in enumerate(apps):
            self._apps_rows[app.package] = r
            first = QTableWidgetItem(generic, "טוען…")
            # תיבת סימון — להסרה של כמה אפליקציות יחד
            first.setFlags(first.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            first.setCheckState(Qt.CheckState.Unchecked)
            t.setItem(r, 0, first)
            t.setItem(r, 1, QTableWidgetItem(app.package))
            t.setItem(r, 2, QTableWidgetItem(""))
            t.setItem(r, 3, QTableWidgetItem(""))

    def _on_app_update(self, payload):
        gen, app, done, total = payload
        if gen != self._apps_gen:
            return
        r = self._apps_rows.get(app.package)
        if r is None:
            return
        t = self.adb_apps_table
        item = t.item(r, 0)
        if item is None:
            return
        item.setText(app.display_name + ("  (מערכת)" if app.system else ""))
        if app.removed_for_user:
            self._mark_app_row(app.package, "for_user")
        item.setIcon(self._app_icon(app))
        if app.note and not app.icon_file:
            item.setToolTip(f"לא נמצאה תמונה: {app.note}")
        t.item(r, 2).setText(app.version or "")
        t.item(r, 3).setText(format_size(app.size) if app.size else "")
        # מד ההתקדמות למטה מתקדם עם הטעינה
        if self.progress.maximum() != total:
            self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status_label.setText(f"טוען אפליקציות… {done}/{total} ({done * 100 // total}%)")
        if done == total:
            self.status_label.setText(f"נטענו {total} אפליקציות")
            self.progress.setStyleSheet("QProgressBar::chunk { background-color: #2ea043; }")
            if getattr(self, "_clear_timer", None):
                self._clear_timer.start()

    def _selected_app_package(self) -> str:
        t = self.adb_apps_table
        r = t.currentRow()
        if r < 0 or t.item(r, 1) is None:
            return ""
        return t.item(r, 1).text()

    def _adb_app_clicked(self, _item):
        pkg = self._selected_app_package()
        if pkg:
            self.adb_pkg_edit.setText(pkg)   # ממלא את שדה ההסרה

    def _adb_app_info(self):
        pkg = self._selected_app_package()
        if not pkg:
            QMessageBox.information(self, "מידע על אפליקציה",
                                    "בחר קודם אפליקציה מהטבלה.")
            return
        adb = config.find_adb_exe()
        if not adb:
            return

        def work():
            from ..core import apk_info
            try:
                bus.adb_app_details.emit(apk_info.app_details(str(adb), pkg))
            except Exception as e:
                self._say("error", f"קריאת מידע על {pkg} נכשלה: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _show_app_details(self, d: dict):
        pkg = d.get("package", "")
        r = self._apps_rows.get(pkg)
        name, icon, size = pkg, None, ""
        if r is not None and self.adb_apps_table.item(r, 0) is not None:
            name = self.adb_apps_table.item(r, 0).text()
            icon = self.adb_apps_table.item(r, 0).icon()
            size = self.adb_apps_table.item(r, 3).text()
        rows = [
            ("שם", name), ("שם חבילה", pkg),
            ("גרסה", d.get("versionName", "")), ("קוד גרסה", d.get("versionCode", "")),
            ("גודל ה-APK", size),
            ("הותקנה לראשונה", d.get("firstInstallTime", "")),
            ("עודכנה לאחרונה", d.get("lastUpdateTime", "")),
            ("הותקנה על ידי", d.get("installer", "") or "לא ידוע"),
            ("אנדרואיד מינימלי (SDK)", d.get("minSdk", "")),
            ("מיועדת ל-SDK", d.get("targetSdk", "")),
            ("הרשאות שאושרו", d.get("grantedPermissions", "")),
            ("מיקום הקוד", d.get("codePath", "")),
            ("תיקיית נתונים", d.get("dataDir", "")),
        ]
        html = "<table>" + "".join(
            f"<tr><td><b>{k}:</b>&nbsp;&nbsp;</td><td>{v}</td></tr>"
            for k, v in rows if v) + "</table>"
        dlg = QMessageBox(self)
        dlg.setWindowTitle(f"מידע על האפליקציה — {name}")
        dlg.setText(html)
        if icon is not None and not icon.isNull():
            dlg.setIconPixmap(icon.pixmap(64, 64))
        dlg.exec()

    def _read_gpt(self):
        self._retry_action = self._read_gpt
        self._gpt_attempt_ok = False   # לטיימר ההשהיה: הניסיון הנוכחי עוד לא הצליח
        collected: list[str] = []

        def on_done(ok: bool):
            if not ok:
                bus.status.emit("קריאת GPT נכשלה")
                return
            table = parse_gpt_output("\n".join(collected))
            if not table.partitions:
                bus.status.emit("לא נמצאו מחיצות בפלט GPT")
                log.warn("לא נמצאו מחיצות בפלט GPT")
                return
            self._gpt_attempt_ok = True   # הניסיון הנוכחי הצליח — הטיימר יבוטל בסיום
            log.info("GPT: on_done (thread רקע) — פולט gpt_parsed ל-thread הראשי")
            # חשוב: לא נוגעים כאן ב-widgets! on_done רץ ב-thread של הג'וב.
            # gpt_parsed מנותב ל-_set_gpt ב-thread הראשי, ושם מתעדכנים המעבד והטבלה.
            bus.gpt_parsed.emit(table)
            bus.status.emit(f"GPT נטען: {len(table.partitions)} מחיצות")

        def _build_gpt():
            j = plan_simple("קריאת GPT", MtkCommands.printgpt(),
                            on_done=on_done, on_output=collected.append)
            j.retries = 2            # חלון לחיבור מחדש אם המכשיר תקוע
            return j
        job = self._plan(_build_gpt)
        if self._request(job):
            self._arm_gpt_timeout()   # אם בעוד 75 שניות אין תשובה — הודעה + הוראות + נסה שוב
        elif getattr(self, "_gpt_timer", None):
            self._gpt_timer.stop()
            self._gpt_timer = None

    def _arm_gpt_timeout(self):
        """קריאת GPT יכולה להיתקע כשהמכשיר לא מוצג בפורט (או יצא ממנו בזמן הטעינה):
        mtkclient ממשיך להמתין לחיבור בלי לדווח כלום. אחרי 75 שניות בלי תשובה —
        הודעה ברורה עם הוראות החיבור וכפתור 'נסה שוב'.
        """
        if getattr(self, "_gpt_timer", None):
            self._gpt_timer.stop()   # ניסיון חוזר — מתחילים ספירה חדשה
        self._gpt_timeout_dialog = None
        timer = QTimer(self)
        timer.setSingleShot(True)

        def fire():
            self._gpt_timer = None
            if getattr(self, "_gpt_attempt_ok", False):
                return   # הניסיון הנוכחי הצליח — לא מפריעים
            cur = job_manager.current
            if job_manager.busy and cur is not None and cur.name != "קריאת GPT":
                return   # פעולה אחרת רצה — לא נתקענו, לא מפריעים
            dlg = QMessageBox(self)
            dlg.setIcon(QMessageBox.Icon.Warning)
            dlg.setWindowTitle("המכשיר לא זוהה")
            dlg.setText("לא התקבל חיבור מהמכשיר במשך דקה ורבע.\n"
                        "הניסיון לקרוא את טבלת המחיצות (GPT) דרך mtkclient לא הצליח.")
            dlg.setInformativeText(
                "הכי נפוץ: המכשיר לא הוכנס נכון למצב BROM/Preloader.\n"
                "🔽 לחץ 'הצג פרטים נוספים' למטה — שם הוראות חיבור מלאות שלב-אחר-שלב.")
            dlg.setDetailedText(
                "איך לחבר נכון במצב Preloader/BROM:\n"
                "1. כבה את המכשיר לגמרי (או הוצא סוללה אם אפשר).\n"
                "2. חבר כבל USB למחשב — בלי המכשיר בצד השני.\n"
                "3. לחץ והחזק את הכפתורים (Volume Down / Volume Up — אחד מהם, "
                "או שניהם יחד, לפי דגם המכשיר).\n"
                "4. תוך כדי ההחזקה חבר את קצה ה-USB למכשיר, והמשך להחזיק עוד 3–5 שניות.\n"
                "5. ברגע החיבור המכשיר מופיע בפורט לשניות בודדות — זה תקין; "
                "הפעולה תופסת אותו אוטומטית.\n\n"
                "אם זה לא עוזר: החלף כבל/פורט USB, וודא שהדרייברים מותקנים "
                "(לשונית mtkclient ← דרייברים — כולל דרייבר VCOM/Preloader של MediaTek).")
            retry = dlg.addButton("🔄 נסה שוב", QMessageBox.ButtonRole.AcceptRole)
            dlg.addButton("סגור", QMessageBox.ButtonRole.RejectRole)
            dlg.setDefaultButton(retry)
            self._gpt_timeout_dialog = dlg
            dlg.show()
            # הכפתור של Qt להרחבת הפרטים — נחליף את נוסח האנגלית שלו לעברית ברורה
            from PySide6.QtWidgets import QPushButton as _QBtn
            details_btn = dlg.findChild(_QBtn, "detailsButton")
            if details_btn is not None:
                details_btn.setText("🔽 הצג פרטים נוספים")
            dlg.exec()
            self._gpt_timeout_dialog = None
            if dlg.clickedButton() is retry:
                if job_manager.busy:
                    job_manager.cancel_current()   # מוודאים שהניסיון התקוע משוחרר
                QTimer.singleShot(400, self._read_gpt)

        timer.timeout.connect(fire)
        timer.start(75_000)
        self._gpt_timer = timer

    def _set_gpt(self, table: GptTable):
        log.info("GPT: _set_gpt (thread ראשי) — התחלת עדכון ממשק")
        self.gpt = table
        self._apply_detected_cpu(getattr(table, "cpu", ""))
        log.info("GPT: מילוי טבלת מחיצות")
        self._fill_partition_table(table)
        self.part_combo.clear()
        for p in table.partitions:
            self.part_combo.addItem(p.name)
        self._say("success", f"סה\"כ: {len(table.partitions)} מחיצות, "
                             f"גודל דיסק: {format_size(table.total_size)}")
        log.info("GPT: _set_gpt הסתיים — הצעת הבוטלאודר תוצג אחרי דיאלוג ההצלחה")
        # ההצעה לבדוק בוטלאודר מופעלת מ-_on_job_done, אחרי שדיאלוג ההצלחה נסגר —
        # רצף מסודר ולא מקונן.

    def _offer_bootloader_check(self):
        """מציע בדיקת מצב אבטחה/בוטלאודר אחרי קריאת GPT — בהתאם לערוץ התקשורת."""
        log.info("GPT: _offer_bootloader_check — התחלה")
        try:
            if job_manager.busy or self.gpt is None:
                return
            if QMessageBox.question(
                    self, "בדיקת בוטלאודר",
                    "ה-GPT נקרא בהצלחה.\nלבדוק עכשיו גם את מצב האבטחה / הבוטלאודר של המכשיר?\n"
                    "(קריאה בלבד — לא משנה כלום)", _YES | _NO, _YES) == _YES:
                self.tabs.setCurrentWidget(self.boot_tab)
                self._check_bootloader()
        except Exception as e:
            self._say("error", f"בדיקת הבוטלאודר לא הופעלה: {e}")

    def _apply_detected_cpu(self, cpu: str):
        """מעדכן את שם המעבד (ואת block_size) מהזיהוי האוטומטי.

        המעבד מסונכרן גם לכותרת מצב המכשיר למעלה ונשאר שם כל עוד המכשיר
        מחובר — לא משנה מאיזה ערוץ הוא הגיע (GPT של mtkclient / ADB / Fastboot).
        """
        cpu = (cpu or "").strip()
        log.info(f"GPT: _apply_detected_cpu (thread ראשי) — מעבד: {cpu or '—'}")
        if not cpu:
            return   # בלי שם מעבד לא מעדכנים כלום — לא מוחקים ערך קיים
        previous = self.chip_edit.text().strip()
        self.chip_edit.setText(cpu)
        self._suggest_block_size()
        self.cpu_header.setText(cpu)
        self.cpu_header.setToolTip(f"מעבד שזוהה מהמכשיר: {cpu}")
        self.cpu_header.setVisible(True)
        if previous and previous.upper() != cpu.upper():
            self._say("info", f"זוהה מעבד {cpu} — עודכן שם הדגם (היה {previous})")
        elif not previous:
            self._say("success", f"זוהה מעבד: {cpu}")

    # ------------------------------------------------------------ דרייברים
    def _check_drivers(self, kind: str):
        """בדיקת מצב הדרייברים במחשב — קריאה בלבד (pnputil / קובצי INF).

        kind: "mtk" (BROM/PreLoader + UsbDk), או "adb"/"fastboot" (הדרייבר שנדרש
        לפעולה של אותה לשונית). הבדיקה בודקת אם הדרייבר מותקן במחשב — לא מאמתת
        חיבור חי של מכשיר.
        """
        from ..core import drivers
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            st = (drivers.check_mediatek() if kind == "mtk"
                  else drivers.check_mode(kind))
        finally:
            QApplication.restoreOverrideCursor()
        text = drivers.format_status(st)
        for line in text.splitlines():
            self._say("info" if st.ok else "warning", line.strip())
        QMessageBox.information(self, "בדיקת דרייברים", text)

    def _install_usbdk(self):
        # קובץ ההתקנה מגיע עם התוכנה (tools\usbdk.msi); גיבוי: התיקייה הניידת
        msi = config.PROJECT_ROOT / "tools" / "usbdk.msi"
        if not msi.is_file():
            msi = config.PORTABLE_ROOT / "usbdk.msi"
        if not msi.is_file():
            QMessageBox.warning(self, "חסר",
                                f"לא נמצא usbdk.msi בתיקיית tools של התוכנה:\n{config.PROJECT_ROOT / 'tools'}")
            return
        if QMessageBox.question(self, "התקנת דרייברים",
                                "יופעל מתקין Windows\u200f (msiexec)\u200f עבור UsbDk.\n"
                                "ייתכן שתידרש הרשאת מנהל (UAC).\nלהמשיך?",
                                _YES | _NO) != _YES:
            return
        subprocess.Popen(["msiexec", "/i", str(msi)])
        self._say("info", "המתקין הופעל — עקוב אחרי חלון ההתקנה")

    # ------------------------------------------------ דרייברים: Android + תיקון למכשיר מחובר
    def _install_android_drivers(self, name: str):
        """מתקין את דרייבר ה-ADB/Fastboot שארוז בתוכנה (tools\\fastboot_driver).

        מכשיר שהמזהה שלו לא מופיע בדרייבר — מטופל בכפתור 'תקן דרייבר למכשיר המחובר'.
        """
        self._install_driver_folder("fastboot_driver", f"דרייבר {name}")

    def _fix_driver_button(self) -> QPushButton:
        b = QPushButton("🔧 תקן דרייבר למכשיר המחובר")
        b.setToolTip("מאתר מכשיר Android/MediaTek שמחובר בלי דרייבר ומצמיד לו את הדרייבר "
                     "המתאים מהתוכנה — גם כשהמזהה שלו לא מוכר (נדרשת הרשאת מנהל)")
        b.clicked.connect(self._fix_connected_driver)
        return b

    def _fix_connected_driver(self):
        """מריץ את tools\\fix_driver.ps1 בהרשאת מנהל ומציג את התוצאה."""
        tools = config.PROJECT_ROOT / "tools"
        ps1 = tools / "fix_driver.ps1"
        if not ps1.is_file():
            QMessageBox.warning(self, "חסר", f"לא נמצא הקובץ:\n{ps1}")
            return
        if QMessageBox.question(
                self, "תקן דרייבר למכשיר המחובר",
                "התוכנה תחפש מכשיר Android/MediaTek שמחובר עכשיו בלי דרייבר, "
                "ותצמיד לו את הדרייבר המתאים (ADB / Fastboot / BROM).\n\n"
                "ודא שהמכשיר מחובר במצב הרצוי. תידרש הרשאת מנהל (UAC).\nלהמשיך?",
                _YES | _NO) != _YES:
            return
        import tempfile
        report = Path(tempfile.gettempdir()) / "askateroov_fix_driver.txt"
        try:
            report.unlink()
        except OSError:
            pass
        self._say("info", "מתקן דרייבר למכשיר המחובר — אשר את חלון ההרשאה…")

        def work():
            args = (f"-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"{ps1}\" "
                    f"-ToolsDir \"{tools}\" -ReportPath \"{report}\"")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                                "Start-Process powershell -Verb RunAs -Wait -ArgumentList '"
                                + args.replace("'", "''") + "'"],
                               creationflags=flags, timeout=300)
            except Exception as e:
                bus.driver_fix_result.emit([("ERR", "", f"ההפעלה נכשלה: {e}")])
                return
            rows = []
            try:
                for line in report.read_text(encoding="utf-8-sig").splitlines():
                    p = line.split("\t")
                    if len(p) >= 3:
                        rows.append((p[0], p[1], p[2]))
            except OSError:
                rows = [("ERR", "", "התיקון לא הסתיים — אולי חלון ההרשאה נדחה.")]
            bus.driver_fix_result.emit(rows)

        threading.Thread(target=work, daemon=True).start()

    def _on_driver_fix_result(self, rows):
        ok = [r for r in rows if r[0] == "OK"]
        err = [r for r in rows if r[0] == "ERR"]
        lines = []
        for _st, kind, text in ok:
            lines.append(f"✅ {kind}: הותקן — {text}")
        for _st, kind, text in err:
            lines.append(f"❌ {kind}: {text}" if kind else f"❌ {text}")
        if not ok and not err:
            lines.append("לא נמצא מכשיר Android מחובר שחסר לו דרייבר.\n"
                         "אם המכשיר לא מזוהה — ודא שהוא מחובר ובמצב הנכון (ADB / Fastboot / BROM).")
        for l in lines:
            self._say("success" if l.startswith("✅") else "warning", l)
        (QMessageBox.information if ok and not err else QMessageBox.warning)(
            self, "תקן דרייבר למכשיר המחובר", "\n".join(lines))

    def _install_mtk_vcom(self):
        """התקנת דרייבר MediaTek VCOM/PreLoader מתוך התוכנה (tools\\mediatek_driver)."""
        self._install_driver_folder("mediatek_driver", "דרייבר MediaTek VCOM")

    def _install_driver_folder(self, folder: str, title: str):
        """התקנת דרייבר מתיקייה בתוך tools.

        עדיפות: קובצי INF ‏(pnputil — עם הרשאת מנהל), ואם אין — קובץ התקנה (exe/msi) שבתיקייה.
        """
        d = config.PROJECT_ROOT / "tools" / folder
        infs = sorted(d.rglob("*.inf")) if d.is_dir() else []
        setups = [] if infs else sorted(
            [p for p in (d.rglob("*") if d.is_dir() else []) if p.suffix.lower() in (".exe", ".msi")])
        if not infs and not setups:
            QMessageBox.warning(
                self, "חסר",
                f"לא נמצאו קובצי {title} בתיקייה:\n"
                f"{d}\n\n"
                "הורד את הדרייבר (כפתור ההורדה שליד), חלץ אותו לתיקייה הזו ונסה שוב.")
            return
        what = (f"יותקנו {len(infs)} קובצי INF דרך pnputil" if infs
                else f"יופעל קובץ ההתקנה {setups[0].name}")
        if QMessageBox.question(self, f"התקנת {title}",
                                f"{what}.\nתידרש הרשאת מנהל (UAC).\nלהמשיך?",
                                _YES | _NO) != _YES:
            return
        try:
            if infs:
                arg = f'/add-driver "{d}\\*.inf" /subdirs /install'
                subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                                  "Start-Process pnputil -Verb RunAs -Wait -ArgumentList '"
                                  + arg.replace("'", "''") + "'"])
            elif setups[0].suffix.lower() == ".msi":
                subprocess.Popen(["msiexec", "/i", str(setups[0])])
            else:
                subprocess.Popen([str(setups[0])], cwd=str(setups[0].parent))
        except OSError as e:
            self._say("error", f"הפעלת התקנת הדרייבר נכשלה: {e}")
            return
        self._say("info", f"התקנת {title} הופעלה — אשר את חלון ההרשאה, "
                          "ואחר כך בדוק עם כפתור 🩺 הבדיקה שליד")

    def _open_drivers_link(self):
        QDesktopServices.openUrl(QUrl(_DRIVERS_URL))

    # ------------------------------------------------------------ Scatter
    def _gen_scatter_full(self):
        if not self.gpt:
            QMessageBox.warning(self, "אין GPT", "קודם טען GPT בלשונית mtkclient")
            return
        chip = self.chip_edit.text().strip()
        if is_placeholder_chip(chip):
            self._say("error", "אין שם מעבד — Scatter לא נוצר")
            QMessageBox.warning(self, "חסר שם מעבד",
                                "שם המעבד (platform) ריק או אינו אמיתי.\n\n"
                                "קרא GPT מהמכשיר (המעבד יזוהה אוטומטית), או הזן דגם ידנית "
                                "למשל MT6580.")
            return
        out = config.SCATTER_DIR / scatter_filename(chip)
        if self.gpt.cpu and self.gpt.cpu.upper() != chip.upper():
            if QMessageBox.question(
                    self, "אי-התאמה במעבד",
                    f"המכשיר דיווח על {self.gpt.cpu}, אבל בשדה כתוב {chip}.\n"
                    "ליצור בכל זאת עם השם שבשדה?", _YES | _NO, _NO) != _YES:
                return
        # שם מכשיר (אופציונלי): אם ימולא — הסקטאר יישמר בבנק בתיקייה נפרדת לפי המכשיר,
        # כך שסקטארים מאותו מעבד למכשירים שונים לא יתנגשו (בלי מספור אוטומטי).
        device = ""
        dev, ok = QInputDialog.getText(
            self, "שם המכשיר (אופציונלי)",
            "הזן שם מכשיר להפקת הסקטאר (למשל Redmi_9A):\n"
            "הסקטאר יישמר בבנק בתיקייה נפרדת לפי שם זה.\n\n"
            "אפשר להשאיר ריק או ללחוץ 'דלג' — אז יישמר לפי שם המעבד.")
        if ok and dev.strip():
            device = dev.strip()
        try:
            generate_scatter(self.gpt, out, chip_name=chip, block_size=self._block_size())
        except ValueError as e:
            QMessageBox.warning(self, "חסר שם מעבד", str(e))
            return
        self._scatter_done(out, chip, device)

    def _block_size(self) -> int:
        raw = self.block_size_edit.text().strip()
        try:
            return int(raw, 16) if raw.lower().startswith("0x") else int(raw)
        except ValueError:
            self._say("warning", f"block_size לא חוקי ('{raw}') — משתמש בברירת מחדל")
            return DEFAULT_BLOCK_SIZE

    def _scatter_done(self, path: Path, chip: str, device: str = ""):
        self._say("success", f"Scatter נוצר: {path}")
        self.scatter_path_edit.setText(str(path))
        problems = validate_scatter(path)
        msg = f"Scatter נוצר:\n{path}"
        if problems:
            self._say("error", f"אימות נכשל — {len(problems)} בעיות")
            for pr in problems:
                self._say("warning", f"  • {pr}")
            msg += "\n\n⚠️ נמצאו בעיות תקינות:\n" + "\n".join(f"• {p}" for p in problems)
        else:
            self._say("success", "אימות SP Flash עבר בהצלחה")
            msg += "\n\n✅ הקובץ עבר אימות ל-SP Flash Tool"
        if self.bank_on_generate.isChecked():
            try:
                # קבוצה (תיקייה) = שם המכשיר אם מולא, אחרת שם המעבד
                group = device or chip
                note = f"נוצר עבור {device} ({chip})" if device else f"נוצר עבור {chip}"
                entry = scatter_bank.save_generated(path, group, note=note,
                                                    device=device, cpu=chip)
                msg += f"\n\nנשמר גם בבנק הסקטארים:\n{entry.group}/{entry.name}"
                self._say("success", f"נשמר בבנק: {entry.group}/{entry.name}")
                self._refresh_bank()
            except OSError as e:
                self._say("warning", f"שמירה לבנק נכשלה: {e}")
        QMessageBox.information(self, "הושלם", msg)

    # ------------------------------------------------------------ שאיבה
    def _read_checked(self):
        self._retry_action = self._read_checked
        if not self._require_flashdump_channel("שאיבה"):
            return
        if not self.gpt:
            # אין GPT — שאיבה לפי שם מחיצה ידני (קריאה בטוחה, בלי סיכון למכשיר)
            if QMessageBox.question(
                    self, "שאיבה ללא GPT",
                    "לא נטען GPT.\n\nאפשר לשאוב מחיצה גם בלי GPT — רק צריך להקליד "
                    "את שם המחיצה במדויק (למשל boot).\n(קריאה בלבד — לא מסכנת את המכשיר.)\n\n"
                    "מומלץ לטעון GPT קודם כדי לבחור מרשימה. להמשיך בכל זאת?",
                    _YES | _NO, _NO) != _YES:
                return
            name, ok = QInputDialog.getText(
                self, "שם מחיצה לשאיבה",
                "הזן את שם המחיצה לשאיבה (בדיוק כפי שהיא במכשיר, למשל boot):")
            if not ok or not name.strip():
                return
            self._request(self._plan(plan_read_partitions, [name.strip()], config.DUMPS_DIR))
            return
        names = self._checked_partitions()
        if not names:
            # תאימות: אם לא סומן כלום אבל יש שורה נבחרת — שואבים אותה
            row = self.part_list.currentRow()
            if row >= 0:
                names = [self.part_list.item(row, 1).text()]
        if not names:
            QMessageBox.warning(self, "לא סומנו מחיצות", "סמן מחיצה אחת או יותר בעמודת ✔")
            return
        self._request(self._plan(plan_read_partitions, names, config.DUMPS_DIR))

    def _read_preloader(self):
        self._retry_action = self._read_preloader
        self._request(self._plan(plan_read_preloader, config.DUMPS_DIR))

    def _read_all(self):
        self._retry_action = self._read_all
        if not self._require_flashdump_channel("שאיבה"):
            return
        self._request(self._plan(plan_read_all, config.DUMPS_DIR))

    # ------------------------------------------------------------ צריבה
    def _browse_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "בחר Image", "",
                                              "Image files (*.img *.bin *.mbn);;All files (*)")
        if path:
            self.image_edit.setText(path)

    def _flash_image(self):
        self._retry_action = None   # צריבה לא חוזרת אוטומטית — רק בלחיצת המשתמש
        if not self._require_flashdump_channel("צריבה"):
            return
        image = Path(self.image_edit.text().strip())
        if not image.is_file():
            QMessageBox.warning(self, "קובץ חסר", "בחר קובץ Image תקין")
            return
        if self.gpt:
            # מסלול רגיל ובטוח: מחיצה מה-GPT + אימות גודל + גיבוי אוטומטי
            part_name = self.part_combo.currentText()
            part = self.gpt.get(part_name)
            self._request(self._plan(plan_write_partition, part_name, image,
                                     part.length if part else None,
                                     backup_first=self.backup_check.isChecked()))
            return
        # אין GPT — ברירת המחדל היא לטעון GPT, אבל המשתמש יכול להמשיך בלי, עם אזהרה
        if QMessageBox.warning(
                self, "צריבה ללא GPT",
                "לא נטען GPT.\n\n⚠️ בלי GPT אין אימות גודל ואין גיבוי אוטומטי — "
                "צריבת קובץ לא מתאים עלולה לפגוע במכשיר.\n\n"
                "מומלץ לטעון GPT קודם (לשונית mtkclient). להמשיך בכל זאת?",
                _YES | _NO, _NO) != _YES:
            return
        part_name, ok = QInputDialog.getText(
            self, "שם מחיצה לצריבה",
            "הזן את שם המחיצה לצריבה (בדיוק כפי שהיא במכשיר, למשל boot):")
        if not ok or not part_name.strip():
            return
        self._request(self._plan(plan_write_partition, part_name.strip(), image,
                                 None, backup_first=False))

    # ------------------------------------------------------------ Bootloader
    def _check_bootloader(self):
        self._retry_action = self._check_bootloader
        collected: list[str] = []

        def on_done(ok: bool):
            if not ok:
                bus.status.emit("בדיקת בוטלאודר נכשלה")
                return
            sec = parse_target_config("\n".join(collected))
            bus.sec_parsed.emit(sec)

        self._request(self._plan(
            lambda: plan_simple("בדיקת מצב אבטחה / בוטלאודר",
                                MtkCommands.gettargetconfig(),
                                on_done=on_done, on_output=collected.append)))

    def _set_header_boot(self, text: str, tooltip: str = ""):
        """מעדכן את חיווי הבוטלאודר בכותרת העליונה; tooltip ריק = שומרים על הקיים."""
        self.hdr_boot.setText(text or "—")
        if tooltip:
            self.hdr_boot.setToolTip(tooltip)
            self._boot_header_tooltip = tooltip

    def _battery_header_text(self, info: "devinfo.DeviceInfo | None") -> str:
        """טקסט הסוללה לכותרת — ריק כשאין נתון להצגה."""
        if info is None:
            return ""
        battery = getattr(info, "battery", None)
        if battery is not None:
            return f"🔋 {battery}%"
        if (getattr(info, "mode", "") == "fastboot"
                and getattr(info, "voltage_mv", None) is not None):
            return f"🔋 {info.voltage_mv}mV"
        return ""

    def _sync_battery_header(self, info: "devinfo.DeviceInfo | None" = None):
        """מנהל את מקטע הסוללה בכותרת העליונה.

        מופעל עם כל מידע חי חדש (device_info) וגם באופן מפורש אחרי פעולות
        שלא מדווחות סוללה (header_refresh) — ואז משלים את הנתון האחרון שידוע,
        כך שהסוללה בכותרת תמיד תתואם את מצב המכשיר בפועל.
        """
        if info is not None:
            self._last_dev_info = info
        else:
            info = self._last_dev_info
        text = self._battery_header_text(info)
        if text:
            self.battery_header.setText(text)
            low = bool(info is not None and hasattr(info, "battery_too_low")
                       and info.battery_too_low())
            # אדום ומודגש כשהסוללה נמוכה; רגיל אחרת
            self.battery_header.setStyleSheet(
                "color: #f85149; font-weight: bold;" if low else "")
            self.battery_header.setVisible(True)
            tip = self._boot_header_tooltip or self.hdr_boot.toolTip()
            self.battery_header.setToolTip(f"סוללה — {tip}" if tip else "סוללה")
        else:
            self.battery_header.setVisible(False)

    def _set_sec(self, sec: dict):
        cpu = str(sec.get("מעבד", "") or "")
        if cpu:
            self._apply_detected_cpu(cpu)   # מעבד מ-gettargetconfig → לכותרת
        summary = summarize_bootloader(sec)
        self.boot_status.setPlainText(summary)
        sbc = sec.get("Secure Boot (SBC)") if sec else None
        if sbc is True:
            self._set_header_boot("🔒 Secure Boot")
        elif sbc is False:
            self._set_header_boot("🔓 אין Secure Boot")
        else:
            self._set_header_boot("—")

    # ============================================================ #6: ניתוב לפי ערוץ תקשורת
    def _effective_channel(self) -> str:
        """הערוץ הפעיל בפועל: adb / fastboot / brom / none.

        אם המשתמש בחר ערוץ מפורש — הוא קובע. אם 'אוטומטי' — לפי המצב האחרון שזוהה.
        """
        ch = getattr(self, "_active_tool", "auto")
        if ch and ch != "auto":
            return ch
        mode = getattr(self, "_last_probe_mode", None)
        if not mode:
            mode = getattr(getattr(self, "_last_dev_info", None), "mode", None)
        if mode in ("preloader", "brom"):
            return "brom"
        return mode or "none"

    def _channel_label(self, ch: str) -> str:
        return {"adb": "ADB", "fastboot": "Fastboot",
                "brom": "mtkclient (BROM)", "none": "לא מזוהה"}.get(ch, ch)

    def _bootloader_check_router(self):
        """בדיקת מצב בוטלאודר — לפי ערוץ התקשורת הפעיל."""
        ch = self._effective_channel()
        label = self._channel_label(ch)
        if ch == "adb":
            self.boot_status.setPlainText(
                "הבדיקה רצה בערוץ ADB — התוצאה מוצגת בכותרת למעלה ובלשונית ADB.")
            self._adb_boot_read()
        elif ch == "fastboot":
            self.boot_status.setPlainText(
                "הבדיקה רצה בערוץ Fastboot — התוצאה מוצגת בכותרת ובלשונית Fastboot.")
            self._fb_info()
        elif ch == "brom":
            self._check_bootloader()
        else:
            QMessageBox.information(
                self, "אין ערוץ תקשורת פעיל",
                "לא זוהה מכשיר בערוץ פעיל.\n"
                "חבר מכשיר, או בחר ערוץ למעלה בשדה 'ערוץ תקשורת'.")

    def _bootloader_change_router(self, unlock: bool):
        """פתיחה/נעילה של בוטלאודר — לפי ערוץ התקשורת הפעיל."""
        ch = self._effective_channel()
        verb = "פתיחת" if unlock else "נעילת"
        act = "פתיחה" if unlock else "נעילה"
        if ch == "brom":
            self._seccfg("unlock" if unlock else "lock")
        elif ch == "fastboot":
            self._fastboot_lock_change(unlock)
        elif ch == "adb":
            if QMessageBox.question(
                    self, f"{verb} בוטלאודר",
                    f"אתה במצב ADB, שאינו מאפשר {act} של הבוטלאודר.\n\n"
                    "להעביר את המכשיר למצב Fastboot ולהמשיך?\n"
                    f"המעבר עצמו אינו משפיע על המכשיר כלל — רק ה{act} עצמה משנה "
                    "(ומוחקת את כל הנתונים).",
                    _YES | _NO, _NO) == _YES:
                self._adb_boot_change(unlock)   # מאתחל ל-Fastboot, מבצע, ומעביר ערוץ ל-Fastboot
        else:
            QMessageBox.information(
                self, "אין ערוץ תקשורת פעיל",
                "לא זוהה מכשיר. חבר מכשיר ובחר ערוץ תקשורת.")

    def _fastboot_lock_change(self, unlock: bool):
        """פתיחה/נעילה כשהמכשיר כבר במצב Fastboot."""
        from ..core import adb_boot
        from ..core.jobs import Job, Step
        if not config.find_fastboot_exe():
            QMessageBox.warning(self, "חסר כלי", "fastboot.exe לא נמצא בתיקיית tools.")
            return
        verb = "פתיחת" if unlock else "נעילת"
        if unlock:
            warn = ("⚠️ אזהרה חמורה: פתיחת הבוטלאודר מוחקת את כל הנתונים במכשיר!\n\n"
                    "ודא שיש לך גיבוי. להמשיך?")
        else:
            warn = ("⚠️ נעילת הבוטלאודר מוחקת גם היא את הנתונים ברוב המכשירים.\n"
                    "אם מותקנת מערכת לא מקורית — נעילה עלולה למנוע מהמכשיר לעלות!\n\nלהמשיך?")
        if QMessageBox.warning(self, f"{verb} בוטלאודר", warn, _YES | _NO, _NO) != _YES:
            return

        def build():
            job = Job(f"{verb} בוטלאודר (Fastboot)",
                      [Step(f"{verb} הבוטלאודר", adb_boot.FlashingLockCommand(unlock))],
                      danger=True)
            job.notes.append("אשר על מסך הטלפון עם כפתורי הווליום ולחצן ההפעלה.")
            job.notes.append("הנתונים במכשיר יימחקו.")
            return job

        self._retry_action = None
        self._request(self._plan(build))

    def _require_flashdump_channel(self, op: str) -> bool:
        """צריבה/שאיבה של mtkclient אפשריות רק ב-BROM/Preloader.

        אם הערוץ הפעיל הוא ADB/Fastboot — מציע מעבר ל-mtkclient (BROM) ומחזיר False.
        """
        ch = self._effective_channel()
        if ch in ("brom", "none"):
            return True   # BROM — הערוץ הנכון; none — נותנים לבדיקות הקיימות (GPT וכו') לטפל
        label = self._channel_label(ch)
        extra = ("\n(לצריבה במצב Fastboot השתמש בלשונית Fastboot.)"
                 if ch == "fastboot" and op == "צריבה" else "")
        if QMessageBox.question(
                self, f"{op} במצב {label}",
                f"אתה במצב תקשורת {label}, שבו לא ניתן לבצע {op} דרך mtkclient.\n\n"
                f"{op} מתבצעת במצב mtkclient\u200f (BROM/Preloader)\u200f.{extra}\n\n"
                "לעבור לערוץ mtkclient\u200f (BROM)\u200f? (יש לחבר את המכשיר במצב BROM/Preloader)",
                _YES | _NO, _NO) == _YES:
            self._set_active_tool("brom")
            self._say("info", f"הערוץ הועבר ל-mtkclient\u200f (BROM)\u200f עבור {op}")
        return False

    def _seccfg(self, flag: str):
        self._retry_action = None
        def build():
            job = plan_simple(f"seccfg {flag}", MtkCommands.seccfg(flag))
            job.danger = True
            if flag == "unlock":
                job.notes.append(
                    "⚠️ אזהרה חמורה: פתיחת ה-Bootloader מוחקת את כל הנתונים מהמכשיר — "
                    "תמונות, אפליקציות, הגדרות וכל נתוני המשתמש. "
                    "המכשיר יחזור למצב של אחרי איפוס יצרן. ודא שיש לך גיבוי לפני שתמשיך!")
            else:
                job.notes.append("הפעולה נועלת את ה-Bootloader\u200f (seccfg)\u200f.")
            return job
        self._request(self._plan(build))

    # ------------------------------------------------------------ גיבוי NVRAM (הועבר מתחזוקת תקשורת)
    def _backup_nvram(self):
        self._retry_action = self._backup_nvram
        self._request(self._plan(plan_backup_nvram))

    # ------------------------------------------------------------ לוגים
    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "ייצוא לוג", str(config.LOGS_DIR / "log.txt"),
                                              "Text (*.txt)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.log_view.toPlainText())
                self._say("success", f"לוג יוצא אל {path}")
            except OSError as e:
                QMessageBox.critical(self, "שגיאה", f"כתיבת לוג נכשלה: {e}")

    def closeEvent(self, event):
        if job_manager.busy:
            if QMessageBox.question(self, "פעולה פעילה",
                                    "יש פעולה פעילה מול המכשיר. לסגור בכל זאת?\n"
                                    "(הפעולה תבוטל)", _YES | _NO, _NO) != _YES:
                event.ignore()
                return
            job_manager.cancel_current()
        self.port_monitor.stop()
        # שמירת הלוג בסגירה — הקובץ נשמר ואינו נמחק
        try:
            path = log.export_summary("החלון נסגר על ידי המשתמש.")
            log.info(f"הלוג נשמר: {path}")
        except Exception:
            pass
        super().closeEvent(event)
