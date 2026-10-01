# -*- coding: utf-8 -*-
"""
החלון הראשי — הסקטארוב. פריסה RTL (מימין לשמאל).

מרכז שליטה: כל פעולה מול המכשיר נבנית כתוכנית (Job), מוצגת למשתמש
בחלון "אישור פעולה" עם הפקודות המדויקות — ורצה רק אחרי אישור מפורש.
"""
from __future__ import annotations

import html
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QPoint, QRectF, QSize, Qt, QUrl,
                            QTimer, QVariantAnimation)
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QFont, QIcon, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QSizePolicy,
    QStackedWidget,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QScrollArea,
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
from ..core import root_pipeline, root_audit, magisk_patch
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
from . import ui_kit
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
    "root_brom": ("רוטינג אוטומטי — BROM בלבד",
                  "מה זה עושה: מבצע רוטינג (Magisk) אוטומטי מקצה לקצה דרך mtkclient/BROM "
                  "בלבד — בלי מצב מפתחים, בלי ADB, בלי בוטלואדר Fastboot. שואב את "
                  "boot/init_boot מהמכשיר עצמו, מפעיל עליו Magisk בצד המחשב, וצורב בחזרה.\n"
                  "למה זה משמש: המסלול המהיר והבטוח ביותר — עובד גם על מכשירים כבויים/"
                  "תקועים, כל עוד יש session תקין מול ה-DA.\n"
                  "השלכות: כתיבה למכשיר (שלב 2 בלבד) — לכל שלב יש אישור נפרד, וגיבוי "
                  "אוטומטי נשמר לפני כתיבה. Unlock (אם מסומן) מוחק את כל נתוני המשתמש."),
    "root_fastboot": ("רוטינג אוטומטי — עם Fastboot",
                      "מה זה עושה: כמו 'BROM בלבד', אך כאשר BROM לא מסוגל לכתוב (הגנת "
                      "seccfg) — עובר ל-Fastboot רק לשתי הפעולות החסומות: Unlock ו-Write. "
                      "כל השאר (זיהוי, שאיבה, פאץ', אימות) עדיין דרך BROM.\n"
                      "למה זה משמש: למכשירים שבהם BROM לבד לא מספיק.\n"
                      "השלכות: דורש בוטלואדר הניתן לפתיחה (OEM Unlocking דלוק בהגדרות "
                      "מפתחים) ואישור פיזי בכפתורי עוצמת קול על המכשיר. Unlock מוחק נתונים."),
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
    "fb_unlock": ("פתיחת בוטלאודר (fastboot flashing unlock)",
                  "מה זה עושה: פותח את הבוטלאודר של מכשיר שמחובר במצב Fastboot.\n"
                  "למה זה משמש: בוטלאודר פתוח מאפשר לצרוב מחיצות (boot, recovery, vbmeta וכו').\n"
                  "השלכות: ⚠️ פתיחת הבוטלאודר מוחקת את כל הנתונים במכשיר — תמונות, אפליקציות, "
                  "הגדרות וכל נתוני המשתמש! במכשירים רבים צריך קודם להפעיל 'ביטול נעילת OEM' "
                  "באפשרויות המפתחים, ולאשר במסך הטלפון עם כפתורי הווליום."),
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
        p.setBrush(QBrush(QColor(theme.colors()["btn"]) if on else QColor(theme.colors()["border"])))
        radius = self._h / 2.0
        p.drawRoundedRect(QRectF(0, 0, self._w, self._h), radius, radius)
        d = self._h - 4          # קוטר העיגול (המחוון)
        x = (self._w - d - 2) if on else 2.0
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QRectF(x, 2, d, d))
        p.end()


class _StatValue(QLabel):
    """ערך בכרטיס המכשיר (מעבד / סוללה), כמו בדמו: שלושת הנתונים קבועים בכרטיס,
    וכשאין נתון מוצג "—" במקום שהערך ייעלם. כך הקוד שמעדכן אותם (setText /
    setVisible / clear) נשאר בדיוק כמו שהוא."""

    def __init__(self):
        super().__init__("—")
        self.setObjectName("statValue")

    def setVisible(self, visible: bool) -> None:
        if not visible:
            self.setText("—")
            self.setStyleSheet("")
        super().setVisible(True)

    def clear(self) -> None:
        self.setText("—")


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
        bb.button(QDialogButtonBox.StandardButton.Save).setText("שמור והעלה")
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
        # ה"גלולה" של הלשונית הנבחרת — מצוירת כאן ונעה בהחלקה ללשונית החדשה (כמו בדמו)
        self._pill = QRectF()
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(320)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_pill_step)
        self._prev_index = -1   # הלשונית שממנה הגלולה יוצאת
        self.currentChanged.connect(self._slide_pill)
        self.tabMoved.connect(lambda *_: setattr(self, "_prev_index", self.currentIndex()))

    def _pill_rect(self, i: int) -> QRectF:
        """מקום הגלולה של לשונית i — המלבן שהלשונית מצוירת בו (שוליים 5/2 מ-theme.py)."""
        if i < 0:
            return QRectF()
        r = QRectF(self.tabRect(i))
        top = 5 + (int(r.height() * (1 - self.BRANCH_SCALE)) if i in self._branch else 0)
        return r.adjusted(2, top, -2, -5)

    def _slide_pill(self, i: int):
        end = self._pill_rect(i)
        if self._anim.state() == QAbstractAnimation.State.Running:
            start = self._pill   # באמצע תנועה — ממשיכים מהמקום הנוכחי
        else:
            # נקודת ההתחלה מחושבת עכשיו, מהלשונית הקודמת (לא ממיקום שמור ישן —
            # הוא עלול להיות מלפני שהחלון קיבל את גודלו הסופי)
            prev = self._prev_index
            start = self._pill_rect(prev) if 0 <= prev < self.count() and prev != i else QRectF()
        self._prev_index = i
        if start.isNull() or start == end or not self.isVisible():
            # בלי תנועה — לפני שהחלון מוצג (בזמן הבנייה המיקומים עוד לא סופיים), או כשאין
            # ממה לזוז; paintEvent מחשב את המקום העדכני בעצמו
            self._anim.stop()
            self._pill = QRectF()
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

    def _on_pill_step(self, value):
        self._pill = value
        self.update()

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
        # הגלולה — לפני הלשוניות (הרקע של הלשונית הנבחרת שקוף ב-theme.py)
        running = self._anim.state() == QAbstractAnimation.State.Running
        pill = self._pill if running else self._pill_rect(self.currentIndex())
        if not running:
            self._pill = pill
        if not pill.isNull():
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.colors()["btn"]))
            p.drawRoundedRect(pill, 10, 10)
            p.restore()
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



# ---------------------------------------------------------------------- אשף הגדרות רוטינג אוטומטי
#
# יותר מדי אפשרויות לדיאלוג אחד — פוצל לשלבים: כל מסך שואל דבר אחד, עם הסבר קצר,
# וברירת מחדל בטוחה. סיכום מלא בסוף לפני שמתחילים בפועל. בעיצוב החלונות החדשים
# (ui_kit.Modal): כרטיס באמצע על רקע מוחשך, "שלב X מתוך Y" בכותרת, ו"הקודם / הבא".


class _WizPage(QWidget):
    """מסך אחד באשף. title / subtitle מוצגים בכותרת החלון; wizard() — האשף שמכיל אותו."""

    title = ""
    subtitle = ""

    def __init__(self):
        super().__init__()
        self._wiz = None
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(12)

    def wizard(self):
        return self._wiz

    def initializePage(self):   # נקרא בכל כניסה למסך
        pass

    def _note(self, text: str, name: str = "hint") -> QLabel:
        lbl = QLabel(ui_kit.rtl(text))
        lbl.setObjectName(name)
        lbl.setWordWrap(True)
        self.lay.addWidget(lbl)
        return lbl


class _MagiskVersionPage(_WizPage):
    title = "גרסת Magisk"
    subtitle = "איזו גרסת Magisk תשמש לפאץ' ה-boot/init_boot?"

    def __init__(self, apks):
        super().__init__()
        self.combo = QComboBox()
        for p in apks:
            self.combo.addItem(p.name, p)
        self.lay.addWidget(self.combo)
        self._note("ברירת מחדל מומלצת: הגרסה העדכנית ביותר (הראשונה ברשימה). גרסה "
                   "ישנה יותר משמשת רק אם יש סיבה ספציפית להעדיף אותה על פני העדכנית.")
        self.lay.addStretch(1)


class _AbiPage(_WizPage):
    title = "ארכיטקטורת מעבד (ABI)"
    subtitle = "צריך לדעת אם המכשיר 64-bit או 32-bit כדי לבחור את הבינארי הנכון."

    def __init__(self, guess, cpu_hint: str = ""):
        super().__init__()
        self._cpu_hint = cpu_hint
        self.combo = QComboBox()
        self.combo.addItem("64-bit (ARM64) — רוב המכשירים מ-2017 ואילך", "arm64-v8a")
        self.combo.addItem("32-bit בלבד (שבבים ישנים: MT6580/MT6570/MT6572/...)", "armeabi-v7a")
        self.combo.setCurrentIndex(0 if guess.is64bit_guess else 1)
        self.lay.addWidget(self.combo)

        self.guess_label = self._note(
            f"הצעה לפי השבב שזוהה: {guess.reason}" +
            ("" if guess.confident else " — לא ודאי, מומלץ לבדוק."))

        row = QHBoxLayout()
        b_adb = QPushButton("🔍 בדוק אוטומטית (אם הטלפון דלוק ומחובר ב-ADB)")
        b_adb.setObjectName("btnSoft")
        b_adb.clicked.connect(self._check_via_adb)
        row.addWidget(b_adb)
        row.addStretch(1)
        self.lay.addLayout(row)

        self.status_label = self._note("", "modalText")
        self._note(
            "איך לדעת בעצמך: אם הטלפון דלוק — הגדרות ← אודות הטלפון ← מידע תוכנה, או "
            "פשוט לחפש בגוגל את שם/דגם הטלפון עם \"64 bit or 32 bit\". ככלל אצבע: שבבי "
            "MediaTek ישנים מאוד (2013–2016, לרוב MT65xx כמו MT6580/MT6572) הם 32-bit "
            "בלבד; כל שבב מ-2017 ואילך (Helio, Dimensity, וכל MT67xx/68xx/69xx) הוא 64-bit.")
        self.lay.addStretch(1)

    def _check_via_adb(self):
        exe = config.find_adb_exe()
        if exe is None:
            self.status_label.setText(ui_kit.rtl("⚠️ adb.exe לא נמצא בתוך התוכנה."))
            return
        abi = devinfo.read_adb_abi(str(exe)).strip().lower()
        if not abi:
            self.status_label.setText(ui_kit.rtl(
                "⚠️ לא נמצא מכשיר ב-ADB. ודא שהטלפון דלוק, ניפוי USB מופעל, "
                "ושאישרת את חלון ההרשאה על המסך."))
            return
        if abi in ("arm64-v8a", "x86_64"):
            self.combo.setCurrentIndex(0)
            self.status_label.setText(ui_kit.rtl(f"✅ זוהה בהצלחה דרך ADB: {abi} (64-bit)"))
        elif abi in ("armeabi-v7a", "armeabi", "x86"):
            self.combo.setCurrentIndex(1)
            self.status_label.setText(ui_kit.rtl(f"✅ זוהה בהצלחה דרך ADB: {abi} (32-bit)"))
        else:
            self.status_label.setText(
                ui_kit.rtl(f"⚠️ התקבל ערך לא מוכר: '{abi}' — נא לבחור ידנית."))


class _AdvancedPage(_WizPage):
    title = "אפשרויות מתקדמות"
    subtitle = "ברירת המחדל (הכל לא מסומן) מתאימה כמעט תמיד."

    def __init__(self):
        super().__init__()
        self.keep_verity = QCheckBox("שמור dm-verity (KEEPVERITY)")
        self.keep_fe = QCheckBox("שמור הצפנה כפויה (KEEPFORCEENCRYPT)")
        self.legacy_sar = QCheckBox("מכשיר Legacy SAR (רק אם הפאץ' הרגיל לא עולה)")
        for cb in (self.keep_verity, self.keep_fe, self.legacy_sar):
            self.lay.addWidget(cb)
        self.lay.addStretch(1)


class _UnlockPage(_WizPage):
    title = "Unlock (seccfg)"
    subtitle = "אופציונלי — רק אם BROM לא יצליח לכתוב בלי זה."

    def __init__(self):
        super().__init__()
        warn = self._note("<b>⚠️ פתיחת בוטלואדר (Unlock) מוחקת את כל נתוני המשתמש במכשיר!</b>",
                          "noticeDanger")
        warn.setTextFormat(Qt.TextFormat.RichText)
        self.unlock_cb = QCheckBox("גם לבצע Unlock (seccfg) לפני הכתיבה, אם צריך")
        self.lay.addWidget(self.unlock_cb)
        self.lay.addStretch(1)


class _SummaryPage(_WizPage):
    title = "סיכום — לפני התחלה"
    subtitle = "בדוק את הבחירות ולחץ 'סיום' כדי להתחיל בשלב 1 (ניתוח, לא מסוכן)."

    def __init__(self):
        super().__init__()
        self.kv = ui_kit.KeyValueList(170)
        self.lay.addWidget(self.kv)
        self.lay.addStretch(1)

    def initializePage(self):
        wiz = self.wizard()
        yn = lambda cb: "כן" if cb.isChecked() else "לא"   # noqa: E731
        rows = [
            ("גרסת Magisk", wiz.magisk_page.combo.currentText()),
            ("ארכיטקטורת מעבד", wiz.abi_page.combo.currentText()),
            ("שמור dm-verity", yn(wiz.adv_page.keep_verity)),
            ("שמור הצפנה כפויה", yn(wiz.adv_page.keep_fe)),
            ("מכשיר Legacy SAR", yn(wiz.adv_page.legacy_sar)),
        ]
        if wiz.unlock_page is not None:
            rows.append(("גם Unlock (seccfg)",
                         "כן — מוחק נתונים!" if wiz.unlock_page.unlock_cb.isChecked() else "לא"))
        self.kv.set_rows(rows)


class _DevRootWizard(ui_kit.Modal):
    """אשף ההגדרות — run() מחזיר "finish" כשהמשתמש אישר, אחרת "" (ביטול / סגירה)."""

    def __init__(self, apks, guess, cpu_hint: str, use_fastboot: bool, parent=None):
        super().__init__(
            parent, "הגדרות רוטינג אוטומטי" + (" — Fastboot" if use_fastboot else " — BROM"),
            icon="info", wide=True)
        self.magisk_page = _MagiskVersionPage(apks)
        self.abi_page = _AbiPage(guess, cpu_hint)
        self.adv_page = _AdvancedPage()
        self.unlock_page = None
        self._pages: list[_WizPage] = [self.magisk_page, self.abi_page, self.adv_page]
        if not use_fastboot:
            self.unlock_page = _UnlockPage()
            self._pages.append(self.unlock_page)
        self.summary_page = _SummaryPage()
        self._pages.append(self.summary_page)
        self._subtitle = self.add_text("", "hint")
        self._stack = QStackedWidget()
        for p in self._pages:
            p._wiz = self
            self._stack.addWidget(p)
        self.add(self._stack)
        # מימין לשמאל: הבא / סיום · הקודם · ביטול
        self._b_next = self.add_button("הבא", "next", "btnPrimary", default=True)
        self._b_back = self.add_button("הקודם", "back", "btnSoft")
        self.add_button("ביטול", "")
        for b, slot in ((self._b_next, self._next), (self._b_back, self._back)):
            b.clicked.disconnect()   # לא סוגרים את החלון — רק מחליפים מסך
            b.clicked.connect(slot)
        self._index = 0
        self._go(0)

    def _go(self, i: int):
        self._index = i
        page = self._pages[i]
        page.initializePage()
        self._stack.setCurrentIndex(i)
        self.title_label.setText(ui_kit.rtl(
            f"שלב {i + 1} מתוך {len(self._pages)} — {page.title}"))
        self._subtitle.setText(ui_kit.rtl(page.subtitle))
        last = i == len(self._pages) - 1
        self._b_next.setText("🔥 סיום — התחל ניתוח" if last else "הבא")
        self._b_back.setVisible(i > 0)

    def _next(self):
        if self._index >= len(self._pages) - 1:
            self._finish("finish")
        else:
            self._go(self._index + 1)

    def _back(self):
        if self._index > 0:
            self._go(self._index - 1)


def _log_bidi(text: str) -> str:
    """שורת לוג בלי עברית (למשל פלט mtkclient) — עטיפה בבידוד כיווניות משמאל לימין,
    כך שהיא נקראת תקין אבל מיושרת לימין כמו כל הלוג."""
    if any("\u0590" <= ch <= "\u05ff" for ch in text):
        return text
    return "\u2066" + text + "\u2069"


class _SettingsPopup(QWidget):
    """חלון ההגדרות (כמו בדמו): נפתח מתחת לגלגל השיניים ונסגר בלחיצה מחוץ לו —
    שם וגרסה · ערכת צבע (שני כרטיסים עם דוגמת צבעים) · סדר לשוניות עצמאי · אודות."""

    def __init__(self, win: "MainWindow"):
        super().__init__(win, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._win = win
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("settingsPanel")
        panel.setFixedWidth(380)
        outer.addWidget(panel)
        # בלי צל — כדי שהטקסט יהיה חד כמו בשאר התוכנה; המסגרת מ-theme.py מספיקה
        v = QVBoxLayout(panel)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(0)

        def section(row: bool = False):
            box = QWidget()
            lay = QHBoxLayout(box) if row else QVBoxLayout(box)
            lay.setContentsMargins(14, 14, 14, 14)
            lay.setSpacing(14 if row else 8)
            return box, lay

        def separator():
            s = QFrame()
            s.setObjectName("kvSep")
            s.setFixedHeight(1)
            v.addWidget(s)

        def label(text: str, name: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName(name)
            lbl.setWordWrap(True)
            return lbl

        # שם התוכנה והגרסה
        box, lay = section()
        lay.addWidget(label(config.APP_TITLE.split(" — ")[0], "setTitle"))   # "הסקטארוב", כמו בדמו
        lay.addWidget(label(f"גרסה {config.APP_VERSION}", "hint"))
        v.addWidget(box)
        separator()
        # ערכת צבע — שני כרטיסים עם דוגמת הצבעים; הנבחר מודגש
        box, lay = section()
        lay.addWidget(label("ערכת צבע", "setLabel"))
        cards = QHBoxLayout()
        cards.setSpacing(8)
        self._cards = {}
        for dark in (True, False):   # גרפיט רך (ברירת המחדל) — ראשון, מימין
            pal = theme.PALETTES[dark]
            card = ui_kit.ThemeCard(pal["name"], (pal["bg"], pal["surface"], pal["btn"]), win.dark == dark)
            card.setToolTip("הבחירה נשמרת להפעלה הבאה")
            card.clicked.connect(lambda d=dark: self._pick(d))
            cards.addWidget(card, 1)
            self._cards[dark] = card
        lay.addLayout(cards)
        lay.addWidget(label("הבחירה נשמרת להפעלה הבאה · ברירת המחדל: "
                            f"{theme.PALETTES[True]['name']}", "hint"))
        v.addWidget(box)
        separator()
        # סדר לשוניות עצמאי — מתג, והלחיצה מחילה מיד
        box, lay = section(row=True)
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addWidget(label("סדר לשוניות עצמאי", "setLabel"))
        col.addWidget(label("כשדלוק — גוררים לשוניות כדי לשנות את הסדר. "
                            "כיבוי מחזיר את הסדר הקבוע.", "hint"))
        lay.addLayout(col, 1)
        sw = _ToggleSwitch(box, height=26)
        sw.setChecked(win._flex_tabs)
        sw.setToolTip("דלוק: אפשר לגרור לשוניות ולשנות את סדרן (הסדר נשמר להפעלה הבאה).\n"
                      "כבוי: חוזר לסדר ברירת המחדל של התוכנה.")
        sw.toggled.connect(win._set_flex_tabs)
        lay.addWidget(sw, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addWidget(box)
        separator()
        # אודות — הטקסט של היום
        box, lay = section()
        lay.addWidget(label("אודות", "setLabel"))
        about = label(win._about_text(), "hint")
        about.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(about)
        v.addWidget(box)

    def _pick(self, dark: bool):
        self._win._set_theme(dark)
        for d, card in self._cards.items():
            card.set_selected(d == dark)

    def open_below(self, anchor: QWidget):
        """פותח מתחת לגלגל השיניים (בקצה השמאלי של הפס העליון, כמו בדמו), בתוך המסך."""
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height()))
        x, y = pos.x(), pos.y() + 6
        screen = anchor.screen().availableGeometry() if anchor.screen() else None
        if screen is not None:
            x = max(screen.left(), min(x, screen.right() - self.width()))
            y = max(screen.top(), min(y, screen.bottom() - self.height()))
        self.move(x, y)
        self.show()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{config.APP_TITLE} v{config.APP_VERSION}")
        # גודל התחלתי 1100x740, אבל לא יותר מהשטח הזמין בפועל במסך —
        # במסכים קטנים/עם הגדלת תצוגה (DPI Scaling) זה מונע חלון שחלקו
        # נשפך מעבר לגבול הנראה של המסך ונחתך.
        _w, _h = 1100, 740
        _screen = QApplication.primaryScreen()
        if _screen is not None:
            _avail = _screen.availableGeometry()
            _w = min(_w, max(600, _avail.width() - 20))
            _h = min(_h, max(400, _avail.height() - 20))
        self.resize(_w, _h)
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
        # סמלי השאיבה/הצריבה — מצוירים מקומית, בצבע ההדגשה של הערכה (מתעדכנים בהחלפת ערכה)
        self.icon_read = guiicons.curved_left_arrow_icon(color=theme.colors()["accent"])
        self.icon_flash = guiicons.down_arrow_icon(color=theme.colors()["accent"])
        self._brom_suggest_open = False     # דיאלוג הצעת GPT פתוח?
        self.port_monitor = PortMonitor()
        self.port_monitor.on_change = self._on_ports_changed

        self._build_ui()
        self._connect_bus()
        self._update_idle_header()   # בפתיחה: 'אין ערוץ תקשורת פעיל'

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
        dot = QLabel()
        dot.setPixmap(ui_kit.svg_pixmap("info", theme.colors()["muted"], 18))
        dot.setProperty("helpDot", True)   # נצבע מחדש בהחלפת ערכה (ui_kit.refresh_all)
        title, body = _ACTION_HELP.get(key, ("", "אין מידע."))
        dot.setCursor(Qt.CursorShape.PointingHandCursor)
        dot.setToolTip("לחץ למידע נוסף")

        def show(_=False):
            ui_kit.MessageBox.information(self, title, body)

        dot.mousePressEvent = show
        return dot

    def _plan(self, factory, *args, **kwargs) -> Job | None:
        """בונה תוכנית עבודה; מציג שגיאה אם mtkclient חסר או הקלט לא תקין."""
        try:
            return factory(*args, **kwargs)
        except (RuntimeError, ValueError, OSError) as e:
            self._say("error", str(e))
            ui_kit.MessageBox.critical(self, "שגיאה – לא ניתן לבצע",
                                 f"{e}\n\nבדוק את ההוראות (כפתור ההוראות בראש הלשונית).")
            return None

    def _request(self, job: Job | None) -> bool:
        """חלון 'אישור פעולה' — רק אחרי אישור מפורש העבודה רצה."""
        if job is None:
            return False
        if job_manager.busy:
            ui_kit.MessageBox.warning(self, "עסוק",
                                "יש פעולה פעילה — המתן לסיומה או לחץ 'בטל פעולה'.")
            return False
        # חלון "אישור פעולה" כמו בדמו: שם הפעולה + תגית הסוג (קריאה / כתיבה / מסוכנת),
        # הפקודות שירוצו, וההערות. בפעולה מסוכנת "ביטול" הוא ברירת המחדל, כמו קודם.
        kind = job.effective_kind
        danger = kind == "danger"
        pill_text, pill_kind = {"read": ("קריאה בלבד", "ok"), "write": ("כתיבה", "warn"),
                                "danger": ("⚠ פעולה מסוכנת", "danger")}.get(kind, ("קריאה בלבד", "ok"))
        dlg = ui_kit.Modal(self, ("⚠ " if danger else "") + "אישור פעולה")
        op_row = QWidget()
        orl = QHBoxLayout(op_row)
        orl.setContentsMargins(0, 0, 0, 0)
        orl.setSpacing(10)
        op_name = QLabel(ui_kit.rtl(f"<b>{html.escape(job.name)}</b>"))
        op_name.setObjectName("modalOp")
        op_name.setTextFormat(Qt.TextFormat.RichText)
        orl.addWidget(op_name, 0)
        orl.addWidget(ui_kit.Pill(pill_text, pill_kind), 0, Qt.AlignmentFlag.AlignVCenter)
        orl.addStretch(1)
        dlg.add(op_row)
        dlg.add_text("לבצע את הפעולה הבאה?", "hint")
        dlg.add_text("פקודות שירוצו:", "hint")
        dlg.add(ui_kit.commands_box([(s.name, s.command.describe()) for s in job.steps]))
        if job.notes:
            dlg.add_text("<br>".join(self._note_html(n) for n in job.notes),
                         "noticeDanger" if danger else "noticeInfo")
        dlg.add_button("אשר והרץ", "run", "btnDanger" if danger else "btnPrimary", default=not danger)
        dlg.add_button("ביטול", "", default=danger)
        if dlg.run() != "run":
            self._say("info", f"בוטל על ידי המשתמש: {job.name}")
            return False
        try:
            job_manager.submit(job)
        except RuntimeError as e:
            ui_kit.MessageBox.warning(self, "עסוק", str(e))
            return False
        self.cancel_btn.setEnabled(True)
        if getattr(self, "_clear_timer", None):
            self._clear_timer.stop()
        self._busy_progress(True)
        self.status_label.setText(f"{job.name}: מתחיל…")
        if job.danger:
            self.tabs.setCurrentWidget(self.logs_tab)
        return True

    @staticmethod
    def _note_html(note: str) -> str:
        """הערה בחלון האישור. ערך באנגלית אחרי "שם: " (למשל נתיב הגיבוי) — מבודד
        משמאל לימין ונשבר בכל תיקייה, כדי שיוצג שלם ובסדר הנכון."""
        head, sep, tail = note.partition(": ")
        if sep and tail and ui_kit.ltr(tail) != tail:   # אין בו עברית
            return html.escape(head + sep) + html.escape(ui_kit.ltr(ui_kit.breakable_path(tail)))
        return html.escape(note)

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        tb = QToolBar("תצוגה")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)   # סמל + טקסט (כפתור הבנק)
        self.toolbar = tb
        self.addToolBar(tb)
        # לוגו התוכנה — בקצה הימני של הפס העליון (כמו בדמו), לפני בנק הסקטארים
        from .logo import LogoLabel
        self.logo_label = LogoLabel()
        tb.addWidget(self.logo_label)
        _gap = QWidget()
        _gap.setFixedWidth(10)
        tb.addWidget(_gap)
        # בנק הסקטארים בפס העליון: סמל + כפתור — מיד אחרי הלוגו (ראשונים בתוספת ב-RTL)
        from .logo import BankGlyph
        self.bank_glyph = BankGlyph()
        self.bank_glyph.setVisible(False)   # מוצג רק כשבנק הוא התצוגה הפעילה
        tb.addWidget(self.bank_glyph)
        self.bank_action = QAction(ui_kit.svg_icon("archive", theme.colors()["text"], 17),
                                   "בנק סקטארים", self)
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
        # מספר הגרסה — "גלולה" קטנה ליד גלגל השיניים (כמו בדמו)
        self.version_pill = QLabel(f"גרסה {config.APP_VERSION}")
        self.version_pill.setObjectName("versionPill")
        self.version_pill.setFixedHeight(26)   # "גלולה" קטנה — לא נמתחת לגובה הפס
        tb.addWidget(self.version_pill)
        # הגדרות — סמל בלבד (בלי המילה "הגדרות"): גרסה · אודות · סדר לשוניות גמיש.
        # ממוקם בתוספת לפני כפתורי העיצוב, כך שהם נשארים בקצה השמאלי בדיוק כמו היום.
        self.settings_action = QAction(guiicons.gear_icon(color=theme.colors()["muted"]), "", self)
        self.settings_action.setToolTip(f"הגדרות – גרסה v{config.APP_VERSION} · אודות · עיצוב")
        self.settings_action.triggered.connect(self._open_settings_menu)
        tb.addAction(self.settings_action)
        # עיצוב בהיר/כהה — לא בפס העליון: נכנס לתפריט ההגדרות (מתחת למתג הסדר).
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        # שמות הערכות — מ-theme.PALETTES (True = גרפיט רך, ברירת המחדל; False = כחול לילה)
        self.light_action = QAction(theme.PALETTES[False]["name"], self)
        self.dark_action = QAction(theme.PALETTES[True]["name"], self)
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
        self.tabs.addTab(self.device_tab, " mtkclient")
        # שאיבה וצריבה — צמוד ל-mtkclient (הן מתבצעות דרכו)
        rb_tab = self._scrollable(self._tab_readback())
        self.tabs.addTab(rb_tab, " שאיבה (Readback)")
        fl_tab = self._scrollable(self._tab_flash())
        self.tabs.addTab(fl_tab, " צריבה (Download)")
        self._rb_tab, self._fl_tab = rb_tab, fl_tab   # לעדכון צבע הסמלים בהחלפת ערכה
        # Scatter — רביעי מימין, צמוד לצריבה (לבקשת המשתמש)
        self.scatter_tab = self._scrollable(self._tab_scatter())
        self.tabs.addTab(self.scatter_tab, " Scatter")
        self.adb_tab = self._scrollable(self._tab_adb())
        self.tabs.addTab(self.adb_tab, " ADB")
        # Fastboot צמוד ל-ADB (לבקשת המשתמש)
        self.fastboot_tab = self._scrollable(self._tab_fastboot())
        self.tabs.addTab(self.fastboot_tab, " Fastboot")
        self.boot_tab = self._scrollable(self._tab_bootloader())
        self.tabs.addTab(self.boot_tab, " Bootloader")
        self.dev_tab = self._scrollable(self._tab_dev_features())
        self.tabs.addTab(self.dev_tab, " בפיתוח")
        # לוג — אחרונה משמאל, בקצה השורה (לבקשת המשתמש)
        self.logs_tab = self._tab_logs()
        self.tabs.addTab(self.logs_tab, " לוג")
        self._apply_tab_icons()           # סמלים מצוירים בכל הלשוניות (במקום אימוג'י)
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
        # כרטיס המכשיר (כמו בדמו): סמל מצב · כותרת | מעבד · בוטלאודר · סוללה · ערוץ תקשורת.
        # אותם רכיבים שהקוד מעדכן (cpu_header / hdr_boot / battery_header / tool_combo) —
        # רק מסודרים בכרטיס.
        self.header = QFrame()
        self.header.setObjectName("deviceCard")
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(20, 14, 20, 14)
        hl.setSpacing(22)
        self.device_status = DeviceStatusWidget()
        self.device_status.setMinimumWidth(250)
        hl.addWidget(self.device_status)
        _vsep = QFrame()
        _vsep.setObjectName("vsep")
        _vsep.setFixedSize(1, 40)
        hl.addWidget(_vsep)
        # שם המעבד — מסונכרן מכל ערוץ זיהוי (GPT של mtkclient / ADB / Fastboot)
        self.cpu_header = _StatValue()
        hl.addWidget(self._stat_block("מעבד", self.cpu_header))
        self.hdr_boot = QLabel("—")
        self.hdr_boot.setObjectName("statValue")
        self.hdr_boot.setToolTip("מצב הבוטלאודר/אבטחה — מתעדכן אחרי בדיקת אבטחה או קריאת מידע")
        hl.addWidget(self._stat_block("בוטלאודר", self.hdr_boot))
        # סוללה — הסוללה המצוירת + אחוז (ADB) או מתח (Fastboot); "—" כשאין נתון.
        # מסונכרן מהמידע החי העדכני ביותר גם אחרי פעולות שלא מדווחות סוללה
        self.battery_header = _StatValue()
        hl.addWidget(self._stat_block("סוללה", self.battery_header, lead=self.device_status.battery))
        hl.addStretch(1)
        _chan_lbl = QLabel("ערוץ תקשורת")
        _chan_lbl.setObjectName("chanLabel")
        hl.addWidget(_chan_lbl)
        self.tool_combo = QComboBox()
        self.tool_combo.setMinimumWidth(180)
        for text, key in (("לא נבחר", "none"), ("אוטומטי", "auto"), ("ADB", "adb"),
                          ("Fastboot", "fastboot"), ("mtkclient\u200f (BROM)\u200f", "brom")):
            self.tool_combo.addItem(text, key)
        self.tool_combo.setToolTip(
            "התוכנה תתחבר למכשיר רק דרך הערוץ שנבחר.\n"
            "'לא נבחר' – אין חיפוש מכשיר עד שבוחרים ערוץ.\n"
            "'אוטומטי' – מתחבר דרך הערוץ הראשון שמזהה את המכשיר, ונשאר בו.")
        self.tool_combo.currentIndexChanged.connect(self._on_tool_combo)
        hl.addWidget(self.tool_combo)

        # שורת המצב — בתחתית (כמו בדמו): נקודת מצב + טקסט · מד התקדמות דק · בטל פעולה
        progbar = QFrame()
        progbar.setObjectName("statusCard")
        progbar.setFixedHeight(50)
        bl = QHBoxLayout(progbar)
        bl.setContentsMargins(16, 0, 16, 0)
        bl.setSpacing(16)
        self.status_dot = QLabel()
        self.status_dot.setObjectName("statusDot")
        self.status_dot.setFixedSize(8, 8)
        bl.addWidget(self.status_dot)
        self.status_label = QLabel("מוכן")
        self.status_label.setMinimumWidth(280)
        bl.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setObjectName("statusProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)   # האחוזים מוצגים בטקסט המצב
        bl.addWidget(self.progress, 1)
        self.cancel_btn = QPushButton("בטל פעולה")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_job)
        bl.addWidget(self.cancel_btn)
        self._progress_state("idle")

        central = QWidget()
        cl = QVBoxLayout(central)
        # ריווח כמו בדמו: שוליים 24/18 ומרווח 14 בין הכרטיס, הלשוניות ושורת המצב
        cl.setContentsMargins(24, 18, 24, 18)
        cl.setSpacing(14)

        cl.addWidget(self.header)
        cl.addWidget(self.tabs, 1)
        cl.addWidget(self.bank_tab, 1)   # מוצג רק כשבנק הסקטארים מופעל מהפס העליון
        self.bank_tab.hide()
        cl.addWidget(progbar)   # שורת המצב בתחתית
        self.setCentralWidget(central)
        # הודעות קצרות בפינה השמאלית התחתונה, מעל שורת המצב (כמו בדמו)
        self.toasts = ui_kit.ToastHost(self)

    def _stat_block(self, caption: str, value: QLabel, lead: QWidget | None = None) -> QWidget:
        """נתון בכרטיס המכשיר (כמו בדמו): כותרת קטנה מעל, והערך מתחתיה.
        lead — ווידג'ט שמופיע לפני הערך (למשל הסוללה המצוירת)."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        cap = QLabel(caption)
        cap.setObjectName("statCaption")
        v.addWidget(cap)
        row = QHBoxLayout()
        row.setSpacing(8)
        if lead is not None:
            row.addWidget(lead, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(value)
        row.addStretch(1)
        v.addLayout(row)
        return box

    def _progress_state(self, state: str):
        """מצב שורת המצב (כמו בדמו): צבע המילוי במד ההתקדמות וצבע נקודת המצב.
        run = פעולה רצה (כחול) · ok = הסתיימה בהצלחה (ירוק) · err = נכשלה/בוטלה (אדום) ·
        idle = מוכן (ירוק)."""
        self.progress.setStyleSheet(theme.progress_qss({"ok": "ok", "err": "cancel"}.get(state, "")))
        self.status_dot.setProperty("state", state)
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)

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
            _PAD = 2 * 10 + 4 + 2 * 2   # ריווח פנימי + מסגרת + שוליים בין הלשוניות (theme.py)
            w = max(40, (self.tabs.width() - 14) // n - _PAD)
            if w == getattr(self, "_last_tab_w", None):
                return   # אין שינוי — לא מחילים שוב (מונע לולאה)
            self._last_tab_w = w
            base = QApplication.instance().font().pointSizeF() or 9.0
            bar_font = QFont(QApplication.instance().font())
            bar_font.setPointSizeF(round(base * 1.25, 1))
            self.tabs.tabBar().setFont(bar_font)   # הגופן נשלט מכאן (כדי שהקטנת הענפים תעבוד בציור)
            # רק על שורת הלשוניות — גיליון סגנון על כל אזור הלשוניות היה מעצב ומצייר
            # מחדש את כל התוכן שבתוכן בכל שינוי גודל של החלון (ריצוד בפתיחה)
            self.tabs.tabBar().setStyleSheet(
                f"QTabBar::tab {{ min-width: {w}px; padding: 8px 10px; }}")
            self._mark_branch_tabs()

    def _apply_tab_icons(self):
        """סמלים מצוירים בלשוניות (במקום אימוג'י): בצבע ההדגשה, ובלשונית הנבחרת — בצבע
        הטקסט שעל הגלולה. לפי הווידג'ט, כך שעובד גם אחרי שינוי סדר הלשוניות."""
        c = theme.colors()

        def two_state(normal: QIcon, selected: QIcon) -> QIcon:
            icon = QIcon()
            icon.addPixmap(normal.pixmap(QSize(18, 18)), QIcon.Mode.Normal, QIcon.State.Off)
            icon.addPixmap(selected.pixmap(QSize(18, 18)), QIcon.Mode.Normal, QIcon.State.On)
            return icon

        kinds = {self.device_tab: "chip", self.scatter_tab: "file", self.adb_tab: "phone",
                 self.fastboot_tab: "bolt", self.boot_tab: "lock", self.dev_tab: "spark",
                 self.logs_tab: "scroll"}
        icons = {w: two_state(ui_kit.svg_icon(k, c["accent"], 18), ui_kit.svg_icon(k, c["btn_text"], 18))
                 for w, k in kinds.items()}
        icons[self._rb_tab] = two_state(guiicons.curved_left_arrow_icon(color=c["accent"]),
                                        guiicons.curved_left_arrow_icon(color=c["btn_text"]))
        icons[self._fl_tab] = two_state(guiicons.down_arrow_icon(color=c["accent"]),
                                        guiicons.down_arrow_icon(color=c["btn_text"]))
        for w, icon in icons.items():
            i = self.tabs.indexOf(w)
            if i >= 0:
                self.tabs.setTabIcon(i, icon)

    @staticmethod
    def _tab_key(text: str) -> str:
        """מפתח להשוואת שם לשונית — בלי סמלים ורווחים, כך שסדר ששמור מגרסה קודמת
        (עם אימוג'י בשם) עדיין מתאים לשמות החדשים."""
        return "".join(ch for ch in text if ch.isalnum())

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
        """חלון ההגדרות (כמו בדמו) — מתחת לגלגל השיניים. נסגר בלחיצה מחוץ לו."""
        anchor = self.toolbar.widgetForAction(self.settings_action) or self.toolbar
        _SettingsPopup(self).open_below(anchor)

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
        # השוואה בלי סמלים ורווחים — סדר ששמור מגרסה קודמת (עם אימוג'י בשם) עדיין מתאים
        rank = {self._tab_key(t): i for i, t in enumerate(saved)}
        widgets = sorted(
            ((rank.get(self._tab_key(self.tabs.tabText(i)), len(saved) + i), self.tabs.widget(i))
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
        self._refresh_button_icons()
        self._say("info", f"עיצוב {theme.PALETTES[on]['name']} הופעל")
        self._toast("info", f"עיצוב {theme.PALETTES[on]['name']} הופעל")

        self._mtk_color = theme.mtk_color
        self._warn_color = theme.warn_color

    def _refresh_button_icons(self):
        """כל הסמלים המצוירים — בצבעי הערכה הפעילה (נקרא בהחלפת ערכה).

        על כפתור צבעוני: בצבע הטקסט של הכפתור. בלשוניות ובכפתורי ההורדה: צבע ההדגשה.
        """
        c = theme.colors()
        if hasattr(self, "btn_read_sel"):
            self.btn_read_sel.setIcon(guiicons.curved_left_arrow_icon(color=c["btn_text"]))
        if hasattr(self, "btn_flash_main"):
            self.btn_flash_main.setIcon(guiicons.down_arrow_icon(color="#ffffff"))
        self.icon_read = guiicons.curved_left_arrow_icon(color=c["accent"])
        self.icon_flash = guiicons.down_arrow_icon(color=c["accent"])
        if hasattr(self, "logs_tab"):
            self._apply_tab_icons()   # כל הלשוניות — לפי הווידג'ט, גם אחרי שינוי סדר
        if hasattr(self, "bank_action"):
            self.bank_action.setIcon(ui_kit.svg_icon("archive", c["text"], 17))
        if hasattr(self, "_bank_back_btn"):
            self._bank_back_btn.setIcon(ui_kit.svg_icon("back", c["text"], 18))
        if hasattr(self, "settings_action"):
            self.settings_action.setIcon(guiicons.gear_icon(color=c["muted"]))
        for b in self.findChildren(QPushButton):
            if b.property("iconKind") == "globe":
                b.setIcon(guiicons.globe_icon(color=c["accent"]))
        if hasattr(self, "device_status"):
            self.device_status.refresh_theme()   # עיגול המצב והסוללה בכרטיס המכשיר
        if hasattr(self, "logo_label"):
            self.logo_label.update()             # הלוגו מצויר בצבעי הערכה
        ui_kit.refresh_all(self)                 # כרטיסים, סמני עזרה, כפתורי סמל
        if getattr(self, "_fs_entries", None):
            self._fs_apply_icons()

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
        """לשונית mtkclient (לפי הדמו): זיהוי מכשיר · סביבת פייתון · פורטים · דרייברים."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(14)
        b_help = QPushButton("הוראות BROM")
        b_help.clicked.connect(lambda: self._show_mode_instructions("brom"))
        v.addWidget(ui_kit.tab_header(
            "mtkclient", "זיהוי המכשיר במצב BROM/Preloader, דרייברים וסביבת העבודה.",
            "mtkclient (BROM)", extra=(b_help,)))
        grid = self._cards_grid()

        # ---- זיהוי מכשיר (קריאה בלבד)
        c_det = ui_kit.Card("זיהוי מכשיר", "קריאת טבלת המחיצות מזהה גם את שם המעבד", "search",
                            ui_kit.Pill("קריאה בלבד", "ok"))
        c_det.add(ui_kit.steps_list([
            "כבה את המכשיר לגמרי.",
            "חבר בכבל USB תוך כדי החזקת <b>Volume Down</b> (או <b>Volume Up</b> — תלוי במכשיר).",
            "אם לא זוהה — החזק את <b>לחצן ההפעלה כ-10 שניות תוך כדי החיבור</b>, "
            "והוא יתאפס ויזוהה אוטומטית.",
        ]))
        # חלופה ל-UsbDk: mtkclient דרך פורט COM (דרייבר VCOM)
        self.serial_check = QCheckBox(
            "חיבור דרך פורט COM (דרייבר MediaTek VCOM) — חלופה כש-UsbDk לא עובד")
        self.serial_check.setToolTip(
            "ב-Windows 11 עם 'בידוד ליבה' דלוק, הדרייבר UsbDk נחסם לעיתים — ואז mtkclient "
            "לא מצליח לדבר עם המכשיר ב-BROM.\n"
            "כשהאפשרות מסומנת, mtkclient מתחבר דרך פורט ה-COM של דרייבר ה-VCOM "
            "(--serialport), בלי UsbDk.\n"
            "דורש: דרייבר MediaTek VCOM מותקן (בכרטיס הדרייברים).\n"
            "לא חל על בדיקת האבטחה (gettargetconfig) ועל פתיחה/נעילת seccfg — "
            "הן רצות תמיד ב-USB ישיר.")
        self.serial_check.toggled.connect(self._set_serialport)
        c_det.add(self.serial_check)
        btn_gpt = QPushButton("קרא טבלת מחיצות (GPT)")
        btn_gpt.setObjectName("btnPrimary")
        btn_gpt.clicked.connect(self._read_gpt)
        c_det.add_action(btn_gpt)
        c_det.add_action(self._help_dot("gpt"))
        grid.addWidget(c_det, 0, 0)

        # ---- סביבת פייתון: תיבת מצב למעלה, הפירוט המלא בלחיצה
        c_py = ui_kit.Card("סביבת פייתון", "מה ש-mtkclient צריך כדי לרוץ", "terminal")
        self.pyenv_status = ui_kit.StatusBox("לא נבדק עדיין…")
        c_py.add(self.pyenv_status)
        # התקנה והורדות — מתחת לתיבת המצב (בשורת הפעולות אין להם מקום בחלון ברוחב רגיל)
        py_inst = QHBoxLayout()
        py_inst.setSpacing(10)
        self.btn_auto_python = QPushButton("התקן פייתון וספריות ל-mtkclient (אוטומטי)")
        self.btn_auto_python.setObjectName("btnSoft")
        self.btn_auto_python.setToolTip(
            "מוריד ומתקין את פייתון הרשמי עם PATH מסומן, ואת כל הספריות ש-mtkclient צריך — "
            "בלי שאלות ובלי הרשאת מנהל. אם פייתון כבר מותקן — מתקין רק את הספריות.")
        self.btn_auto_python.clicked.connect(self._auto_install_python)
        py_inst.addWidget(self.btn_auto_python)
        # שתי ההורדות — בתפריט; המסגרת האדומה כשפייתון חסר מופיעה על הכפתור הזה
        self.btn_install_python = ui_kit.menu_button("הורדות", [
            ("הורדת פייתון להתקנה (האתר הרשמי)", self._open_python_download),
            ("הורדת פייתון נייד (MTKClient Portable)",
             lambda: QDesktopServices.openUrl(QUrl(_MTK_PORTABLE_URL))),
        ])
        self.btn_install_python.setToolTip(
            "הורדת פייתון להתקנה מהאתר הרשמי, או פייתון נייד (MTKClient Portable) — "
            "mtkclient עם פייתון, בלי התקנה.")
        self._style_install_python(alert=False)
        py_inst.addWidget(self.btn_install_python)
        py_inst.addStretch(1)
        c_py.add_layout(py_inst)
        self.pyenv_text = QTextEdit()
        self.pyenv_text.setReadOnly(True)
        self.pyenv_text.setMinimumHeight(140)
        self.pyenv_text.setMaximumHeight(200)
        self.pyenv_text.setPlaceholderText("לא נבדק עדיין…")
        self.pyenv_text.setVisible(False)
        c_py.add(self.pyenv_text)
        b_py = QPushButton("בדוק שוב")
        b_py.setToolTip("זיהוי סביבת פייתון — בדיקה בלבד")
        b_py.clicked.connect(self._detect_pyenv)
        c_py.add_action(b_py)
        c_py.add_action(QWidget(), 1)
        self._pyenv_toggle = QPushButton("הצג פירוט מלא")
        self._pyenv_toggle.setObjectName("btnGhost")
        self._pyenv_toggle.clicked.connect(self._toggle_pyenv_details)
        c_py.add_action(self._pyenv_toggle)
        grid.addWidget(c_py, 0, 1)

        # ---- פורטים מחוברים (ניטור חי)
        c_ports = ui_kit.Card("פורטים מחוברים", "מתעדכן לבד כשמכשיר מתחבר או מתנתק", "plug",
                              ui_kit.Pill("● ניטור חי", "ok"))
        self.ports_table = QTableWidget(0, 5)
        self.ports_table.setHorizontalHeaderLabels(["פורט", "תיאור", "מצב", "VID", "PID"])
        self.ports_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ports_table.verticalHeader().setVisible(False)
        self.ports_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ports_table.setMinimumHeight(120)
        self.ports_table.setMaximumHeight(200)
        c_ports.add(self.ports_table)
        refresh_btn = QPushButton("רענן עכשיו")
        refresh_btn.setObjectName("btnGhost")
        refresh_btn.setToolTip("הטבלה מתעדכנת אוטומטית; השתמש רק אם נראה שהיא לא התעדכנה")
        refresh_btn.clicked.connect(self._refresh_ports)
        c_ports.add_action(refresh_btn)
        grid.addWidget(c_ports, 1, 0)

        # ---- דרייברים (BROM)
        c_drv = ui_kit.Card("דרייברים", "מה שנדרש במחשב כדי לדבר עם המכשיר במצב BROM", "wrench")
        self.mtk_usbdk_pill = ui_kit.Pill("לא נבדק", "neutral")
        self.mtk_vcom_pill = ui_kit.Pill("לא נבדק", "neutral")
        c_drv.add(self._kv_status_box([("UsbDk (חיבור USB ישיר)", self.mtk_usbdk_pill),
                                       ("MediaTek VCOM (פורט COM)", self.mtk_vcom_pill)]))
        b_fix = self._fix_driver_button()
        b_fix.setText("תקן דרייבר למכשיר המחובר")
        b_fix.setObjectName("btnSoft")
        c_drv.add_action(b_fix)
        btn_check = QPushButton("בדיקת מצב הדרייברים")
        btn_check.setToolTip("בודק אם הדרייברים MediaTek VCOM/PreLoader ו-UsbDk "
                             "מותקנים במחשב (קריאה בלבד).")
        btn_check.clicked.connect(lambda: self._check_drivers("mtk"))
        c_drv.add_action(btn_check)
        c_drv.add_action(ui_kit.menu_button("התקנה והורדה", [
            ("התקנת דרייבר UsbDk (מתוך התוכנה)", self._install_usbdk),
            ("התקנת דרייבר MediaTek VCOM (מתוך התוכנה)", self._install_mtk_vcom),
            None,
            ("הורדת UsbDk\u200f (GitHub — Daynix)\u200f", lambda: QDesktopServices.openUrl(QUrl(_USBDK_URL))),
            ("הורדת דרייברי MediaTek VCOM\u200f (mtkdriver.com)\u200f", self._open_drivers_link),
        ]))
        grid.addWidget(c_drv, 1, 1)

        v.addLayout(grid)
        v.addStretch(1)
        return self._scrollable(w)   # גלילה במקום "מעיכה" של החלקים

    def _cards_grid(self) -> QGridLayout:
        """רשת כרטיסים בשתי עמודות שוות (כמו בדמו)."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return grid

    def _kv_status_box(self, rows) -> QFrame:
        """מסגרת עם שורות "שם ← תגית מצב" (כמו בדמו), למשל מצב הדרייברים."""
        box = QFrame()
        box.setObjectName("kvList")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for i, (name, pill) in enumerate(rows):
            if i:
                sep = QFrame()
                sep.setObjectName("kvSep")
                sep.setFixedHeight(1)
                lay.addWidget(sep)
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(16, 10, 16, 10)
            lbl = QLabel("\u200f" + name)   # מימין לשמאל גם כשהשם מתחיל באנגלית (UsbDk …)
            lbl.setObjectName("kvVal")
            lbl.setWordWrap(True)
            h.addWidget(lbl, 1)
            h.addWidget(pill)
            lay.addWidget(row)
        return box

    @staticmethod
    def _side_column(*cards) -> QWidget:
        """עמודה צדדית: כרטיסים בגובה הטבעי שלהם, מלמעלה (כמו בדמו)."""
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        for c in cards:
            v.addWidget(c)
        v.addStretch(1)
        return col

    def _toggle_pyenv_details(self):
        show = not self.pyenv_text.isVisible()
        self.pyenv_text.setVisible(show)
        self._pyenv_toggle.setText("הסתר פירוט" if show else "הצג פירוט מלא")

    def _set_pyenv_status(self, summary: str, ok: bool):
        """תיבת המצב של סביבת הפייתון — מהשורה הראשונה של הדוח (ושורת "פייתון פעיל")."""
        lines = [ln.strip() for ln in (summary or "").splitlines() if ln.strip()]
        title = lines[0] if lines else ""
        for mark in ("🟢", "🔴"):
            title = title.replace(mark, "").strip()
        sub = next((ln for ln in lines if ln.startswith("פייתון פעיל:")), "")
        if not sub and len(lines) > 1 and not lines[1].startswith("────"):
            sub = lines[1]
        self.pyenv_status.set(title, sub, "ok" if ok else "err")

    # ------------------------------------------------------------ לשונית Scatter
    def _tab_scatter(self) -> QWidget:
        """לשונית Scatter (לפי הדמו): יצירה · בדיקה — פעולות במחשב בלבד."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(14)
        v.addWidget(ui_kit.tab_header(
            "Scatter", "יצירה ובדיקה של קובצי Scatter לתוכנת SP Flash Tool.",
            chip_html="פעולה <b>במחשב בלבד</b>"))
        grid = self._cards_grid()

        # ---- יצירה
        c_gen = ui_kit.Card("יצירת Scatter מטבלת ה-GPT",
                            "קובץ בפורמט של תוכנת SP Flash Tool · המעבד מתמלא לבד אחרי קריאת GPT",
                            "doc_plus", ui_kit.Pill("לא נוגע במכשיר", "neutral"))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.chip_edit = QLineEdit()
        self.chip_edit.setPlaceholderText("MT6580")
        self.chip_edit.setToolTip(
            "שם המעבד (platform). מתמלא אוטומטית כשקוראים GPT — MT6580 וכדומה. "
            "שם זה נכתב לתוך ה-Scatter וגם לשם הקובץ, ולכן הוא חובה.")
        self.chip_edit.editingFinished.connect(self._suggest_block_size)
        form.addRow("מעבד (platform):", self.chip_edit)
        self.block_size_edit = QLineEdit(f"0x{DEFAULT_BLOCK_SIZE:x}")
        self.block_size_edit.setToolTip(
            "גודל הגוש המוצהר ב-Scatter. מתעדכן אוטומטית לפי המעבד: "
            "מעבדים ישנים (MT65xx, MT6735/37/53) — 0x20000, מודרניים — 0x200000. "
            "אם יש לך Scatter מקורי של המכשיר — העדף את הערך שבו.")
        form.addRow("גודל בלוק (block_size):", self.block_size_edit)
        c_gen.add_layout(form)
        self.bank_on_generate = QCheckBox("שמור אוטומטית גם ל'בנק סקטארים' תחת שם המעבד")
        self.bank_on_generate.setChecked(True)
        c_gen.add(self.bank_on_generate)
        b1 = QPushButton("צור קובץ Scatter")
        b1.setObjectName("btnPrimary")
        b1.setToolTip(
            "Scatter מלא ל-SP Flash Tool: preloader\u200f (EMMC_BOOT_1)\u200f + pgpt + כל מחיצות "
            "ה-GPT + sgpt.\nהקובץ נשמר בשם Android_scatter_<שם המעבד>.txt.")
        b1.clicked.connect(self._gen_scatter_full)
        c_gen.add_action(b1)
        grid.addWidget(c_gen, 0, 0)

        # ---- בדיקה (התוצאה והתצוגה המקדימה — בתוך הכרטיס)
        c_val = ui_kit.Card("בדיקת קובץ Scatter",
                            "בודק שהקובץ תואם לתוכנת SP Flash Tool, ומאתר שגיאות מבנה לפני "
                            "שמשתמשים בו", "doc_check", ui_kit.Pill("לא נוגע במכשיר", "neutral"))
        lbl = QLabel("קובץ Scatter")
        lbl.setObjectName("hint")
        c_val.add(lbl)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.scatter_path_edit = QLineEdit()
        self.scatter_path_edit.setPlaceholderText("לא נבחר קובץ")
        self.scatter_path_edit.textChanged.connect(self._scatter_path_changed)
        row.addWidget(self.scatter_path_edit, 1)
        btn_browse = QPushButton("בחר קובץ…")
        btn_browse.clicked.connect(self._browse_scatter)
        row.addWidget(btn_browse)
        c_val.add_layout(row)
        self.scatter_result = QWidget()   # שורות "בדיקה ← תגית" (מתמלא ב-_show_scatter_result)
        QVBoxLayout(self.scatter_result).setContentsMargins(0, 0, 0, 0)
        self.scatter_result.setVisible(False)
        c_val.add(self.scatter_result)
        self.scatter_preview = QPlainTextEdit()
        self.scatter_preview.setObjectName("preview")
        self.scatter_preview.setReadOnly(True)
        self.scatter_preview.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.scatter_preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.scatter_preview.setMaximumHeight(260)
        self.scatter_preview.setVisible(False)
        c_val.add(self.scatter_preview)
        b_val = QPushButton("בדוק קובץ")
        b_val.setToolTip("אימות תקינות ל-SP Flash Tool")
        b_val.clicked.connect(self._validate_scatter_file)
        c_val.add_action(b_val)
        b_prev = QPushButton("תצוגה מקדימה")
        b_prev.clicked.connect(self._preview_scatter_file)
        c_val.add_action(b_prev)
        grid.addWidget(c_val, 0, 1)

        v.addLayout(grid)
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
            ui_kit.MessageBox.warning(self, "חסר קובץ", "בחר קובץ Scatter קודם")
            return None
        return Path(p)

    def _validate_scatter_file(self):
        path = self._current_scatter_path()
        if not path:
            return
        problems = validate_scatter(path)
        # התוצאה — בתוך הכרטיס (במקום חלון), כמו בדמו
        if not problems:
            self._say("success", f"הקובץ תקין ל-SP Flash: {path.name}")
            self._show_scatter_result([
                ("תאימות לתוכנת SP Flash Tool", "תואם", "ok"),
                ("בדיקות המבנה", "עבר את כל הבדיקות", "ok"),
            ])
            return
        self._say("error", f"נמצאו {len(problems)} בעיות בקובץ")
        for pr in problems:
            self._say("warning", f"  • {pr}")
        self._show_scatter_result(
            [("תאימות לתוכנת SP Flash Tool", "לא תקין", "danger")]
            + [(pr, "בעיה", "danger") for pr in problems])

    def _show_scatter_result(self, rows):
        """תוצאת בדיקת ה-Scatter בתוך הכרטיס: שורות "בדיקה ← תגית" (כמו בדמו)."""
        lay = self.scatter_result.layout()
        while lay.count():
            item = lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        lay.addWidget(self._kv_status_box([(t, ui_kit.Pill(p, k)) for t, p, k in rows]))
        self.scatter_result.setVisible(True)

    def _scatter_path_changed(self, *_):
        """נבחר קובץ אחר — התוצאה והתצוגה המקדימה הקודמות כבר לא שייכות אליו."""
        self.scatter_result.setVisible(False)
        self.scatter_preview.setVisible(False)

    def _preview_scatter_file(self):
        path = self._current_scatter_path()
        if not path:
            return   # כבר הוצגה האזהרה "בחר קובץ Scatter קודם"
        if not path.is_file():
            ui_kit.MessageBox.warning(self, "קובץ חסר", "הקובץ לא נמצא")
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self._toast("err", f"קריאה נכשלה: {e}")
            return
        # התצוגה המקדימה — בתוך הכרטיס (במקום חלון)
        self.scatter_preview.setPlainText(text)
        self.scatter_preview.setVisible(True)

    # ------------------------------------------------------------ לשונית בנק סקטארים
    def _tab_scatter_bank(self) -> QWidget:
        """בנק הסקטארים (כמו בדמו): "חזור לתוכנה" · כרטיס הקבוצות (לפי מעבד / לפי מכשיר)
        · כרטיס הקבצים — הטבלה, תצוגת התוכן בתוך הכרטיס, והפעולות."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(16)
        self._bank_back_btn = QPushButton(" חזור לתוכנה")
        self._bank_back_btn.setIcon(ui_kit.svg_icon("back", theme.colors()["text"], 18))
        self._bank_back_btn.setToolTip("סגירת בנק הסקטארים וחזרה ללשוניות התוכנה")
        self._bank_back_btn.clicked.connect(self._bank_back)
        head.addWidget(self._bank_back_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(ui_kit.tab_header(
            "בנק סקטארים",
            "ארכיון קובצי Scatter (SP Flash Tool) — מסודר לפי מעבד או לפי מכשיר."), 1)
        v.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)
        # ---- כרטיס הקבוצות: לפי מעבד / לפי מכשיר, ורשימה עם מספר הקבצים בכל קבוצה
        side = QFrame()
        side.setObjectName("card")
        side.setFixedWidth(280)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(16, 16, 16, 16)
        sv.setSpacing(12)
        self._bank_by = "cpu"
        self._bank_filter = None
        seg = QHBoxLayout()
        seg.setSpacing(6)
        seg_group = QButtonGroup(side)
        seg_group.setExclusive(True)
        for key, text in (("cpu", "לפי מעבד"), ("device", "לפי מכשיר")):
            b = QPushButton(text)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(key == "cpu")
            b.clicked.connect(lambda _=False, k=key: self._bank_set_grouping(k))
            seg_group.addButton(b)
            seg.addWidget(b, 1)
        sv.addLayout(seg)
        self._bank_groups_lay = QVBoxLayout()
        self._bank_groups_lay.setSpacing(4)
        sv.addLayout(self._bank_groups_lay)
        sv.addStretch(1)
        info = QLabel(
            "כאן נשמרים קובצי Scatter שהתוכנה יצרה או שהזנת ידנית, מאורגנים "
            "לפי מעבד או מכשיר. אפשר גם פשוט להעתיק קבצים ידנית לתיקיות שבבנק "
            "וללחוץ רענון.")
        info.setObjectName("hint")
        info.setWordWrap(True)
        sv.addWidget(info)
        b_folder = QPushButton("פתח את תיקיית הבנק")
        b_folder.setObjectName("btnGhost")
        b_folder.clicked.connect(self._bank_open_folder)
        sv.addWidget(b_folder, 0, Qt.AlignmentFlag.AlignLeft)   # בממשק מימין לשמאל — בצד ימין
        body.addWidget(side)

        # ---- כרטיס הקבצים
        refresh = ui_kit.icon_button("refresh", "רענון")
        refresh.clicked.connect(self._bank_refresh_clicked)
        card = ui_kit.Card("כל הקבצים", "", "file", refresh)
        card.expand_body()
        self._bank_card = card
        self.bank_table = QTableWidget(0, 5)
        self.bank_table.setHorizontalHeaderLabels(
            ["שם קובץ", "מעבד", "מכשיר", "מקור", "תאריך"])
        self.bank_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.bank_table.verticalHeader().setVisible(False)
        self.bank_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.bank_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.bank_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.bank_table.setMinimumHeight(220)
        self.bank_table.itemSelectionChanged.connect(self._bank_selection_changed)
        card.add(self.bank_table, 1)
        # "הצג תוכן" — בתוך הכרטיס, במקום חלון נפרד (כמו בדמו)
        self._bank_preview_box = QPlainTextEdit()
        self._bank_preview_box.setObjectName("preview")
        self._bank_preview_box.setReadOnly(True)
        self._bank_preview_box.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._bank_preview_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._bank_preview_box.setMaximumHeight(220)
        self._bank_preview_box.hide()
        card.add(self._bank_preview_box)
        self.bank_summary = QLabel()
        self.bank_summary.setObjectName("hint")
        self.bank_summary.setWordWrap(True)
        card.add(self.bank_summary)
        b_imp = QPushButton("ייבא קובץ Scatter…")
        b_imp.setObjectName("btnPrimary")
        b_imp.clicked.connect(self._bank_import)
        card.add_action(b_imp)
        for text, slot in (("הצג תוכן", self._bank_preview),
                           ("העבר לקבוצה", self._bank_move),
                           ("שנה שם", self._bank_rename)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            card.add_action(b)
        card.add_action(QWidget(), 1)
        b_del = QPushButton("מחק")
        b_del.setObjectName("btnDangerOutline")
        b_del.clicked.connect(self._bank_delete)
        card.add_action(b_del)
        body.addWidget(card, 1)
        v.addLayout(body, 1)
        self._refresh_bank()
        return w

    def _bank_group_of(self, e) -> str:
        """הקבוצה של קובץ — לפי מעבד (או תיקיית הקבוצה) או לפי מכשיר."""
        if self._bank_by == "cpu":
            return e.cpu or e.group          # ישן/ידני: התיקייה היא בד"כ שם המעבד
        return e.device or "ללא שם מכשיר"

    def _bank_group_button(self, name, count: int) -> QPushButton:
        """שורה ברשימת הקבוצות (כמו בדמו): שם הקבוצה, ומספר הקבצים בה."""
        b = QPushButton()
        b.setObjectName("bankGroup")
        b.setCheckable(True)
        selected = name == self._bank_filter
        b.setChecked(selected)
        b.setFixedHeight(44)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(b)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(10)
        lbl = QLabel(name or "הכל")
        lbl.setObjectName("bankGroupName")
        lbl.setProperty("selected", "true" if selected else "false")
        cnt = QLabel(str(count))
        cnt.setObjectName("countBadge")
        for x in (lbl, cnt):
            x.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        h.addWidget(lbl, 1)
        h.addWidget(cnt)
        b.clicked.connect(lambda _=False, g=name: self._bank_select_group(g))
        return b

    def _refresh_bank(self):
        entries = scatter_bank.list_entries()
        counts: dict = {}
        for e in entries:
            g = self._bank_group_of(e)
            counts[g] = counts.get(g, 0) + 1
        if self._bank_filter not in counts:
            self._bank_filter = None
        lay = self._bank_groups_lay
        while lay.count():
            item = lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for name, n in [(None, len(entries))] + sorted(counts.items()):
            lay.addWidget(self._bank_group_button(name, n))
        shown = [e for e in entries
                 if self._bank_filter is None or self._bank_group_of(e) == self._bank_filter]
        self._bank_entries = shown
        self.bank_table.setRowCount(0)
        for e in shown:
            row = self.bank_table.rowCount()
            self.bank_table.insertRow(row)
            cpu = e.cpu or e.group      # ישן/ידני: התיקייה היא בד"כ שם המעבד
            dev = e.device or "—"       # רק שם מכשיר שמולא במפורש — אחרת ריק
            for col, val in enumerate([e.name, cpu, dev, e.source_label, e.modified_str]):
                self.bank_table.setItem(row, col, QTableWidgetItem(str(val)))
        self._bank_card.title.setText(self._bank_filter or "כל הקבצים")
        self._bank_preview_box.hide()
        self._bank_selection_changed()
        st = scatter_bank.stats()
        self.bank_summary.setText(
            f"סה\"כ {st['total']} קבצים | נוצרו בתוכנה: {st['generated']} | "
            f"הוזנו ידנית: {st['manual']} | קבוצות: {st['groups']}\nמיקום: {st['root']}")

    def _bank_set_grouping(self, key: str):
        self._bank_by = key
        self._bank_filter = None
        self._refresh_bank()

    def _bank_select_group(self, name):
        self._bank_filter = name
        self._refresh_bank()

    def _bank_refresh_clicked(self):
        self._refresh_bank()
        self.toasts.show("info", "הבנק רוענן")

    def _bank_selection_changed(self):
        """שורת המשנה בכרטיס: מספר הקבצים, והקובץ שנבחר (כמו בדמו)."""
        entries = getattr(self, "_bank_entries", [])
        row = self.bank_table.currentRow()
        sel = entries[row].name if 0 <= row < len(entries) and self.bank_table.selectedItems() else ""
        self._bank_card.desc.setText(f"{len(entries)} קבצים" + (f" · נבחר: {sel}" if sel else ""))
        self._bank_card.desc.setVisible(True)
        self._bank_preview_box.hide()

    def _selected_bank_entry(self):
        entries = getattr(self, "_bank_entries", [])
        row = self.bank_table.currentRow()
        if row < 0 or row >= len(entries) or not self.bank_table.selectedItems():
            self.toasts.show("warn", "קודם בחר קובץ ברשימה")
            return None
        return entries[row]

    def _ask_text(self, title: str, op: str, prompt: str, value: str = "", choices=()):
        """חלון קלט קצר (כמו בדמו): כותרת · שם הקובץ · שדה (עם הצעות) · שמור / ביטול.
        מחזיר את הטקסט, או None כשמבטלים / משאירים ריק."""
        dlg = ui_kit.Modal(self, title, f"<b>{html.escape(op)}</b>" if op else "")
        dlg.add_text(html.escape(prompt), "hint")
        if choices:
            field = QComboBox()
            field.setEditable(True)
            field.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            field.addItems(list(choices))
            field.setCurrentText(value)
            get = field.currentText
        else:
            field = QLineEdit(value)
            get = field.text
        dlg.add(field)
        dlg.focus_on(field)
        dlg.add_button("שמור", "ok", "btnPrimary", default=True)
        dlg.add_button("ביטול", "")
        if dlg.run() != "ok":
            return None
        return get().strip() or None

    def _bank_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר קובץ Scatter", "", "Scatter files (*.txt *.scatter *.cfg);;All files (*)")
        if not path:
            return
        group = self._ask_text("קבוצת יעד", Path(path).name,
                               "שם מעבד או מכשיר (למשל MT6765 או Redmi_9A):", "",
                               scatter_bank.groups())
        if not group:
            return
        try:
            entry = scatter_bank.import_file(Path(path), group)
        except (OSError, FileNotFoundError) as e:
            self._say("error", f"הייבוא נכשל: {e}")
            self.toasts.show("err", f"הייבוא נכשל: {e}")
            return
        self._say("success", f"נוסף לבנק: {entry.group}/{entry.name}")
        self.toasts.show("ok", f"הקובץ יובא לבנק: {entry.group}/{entry.name}")
        self._refresh_bank()

    def _bank_preview(self):
        """"הצג תוכן" — בתוך הכרטיס (במקום חלון נפרד)."""
        entry = self._selected_bank_entry()
        if not entry:
            return
        self._bank_preview_box.setPlainText(scatter_bank.read_entry_text(entry))
        self._bank_preview_box.show()

    def _bank_move(self):
        entry = self._selected_bank_entry()
        if not entry:
            return
        group = self._ask_text("העברה לקבוצה", entry.name, "שם מעבד או מכשיר חדש:",
                               entry.group, scatter_bank.groups())
        if not group:
            return
        try:
            scatter_bank.move_to_group(entry, group)
        except OSError as e:
            self._say("error", f"ההעברה נכשלה: {e}")
            self.toasts.show("err", f"ההעברה נכשלה: {e}")
            return
        self._say("info", f"הועבר לקבוצה: {group}")
        self.toasts.show("ok", f"הקובץ הועבר ל-{group}")
        self._refresh_bank()

    def _bank_rename(self):
        entry = self._selected_bank_entry()
        if not entry:
            return
        name = self._ask_text("שינוי שם", entry.name, "שם קובץ חדש:", entry.name)
        if not name:
            return
        try:
            scatter_bank.rename_entry(entry, name)
        except (OSError, FileExistsError) as e:
            self._say("error", f"השינוי נכשל: {e}")
            self.toasts.show("err", f"השינוי נכשל: {e}")
            return
        self.toasts.show("ok", "השם שונה")
        self._refresh_bank()

    def _bank_delete(self):
        entry = self._selected_bank_entry()
        if not entry:
            return
        dlg = ui_kit.Modal(self, "⚠ מחיקה מהבנק",
                           f"<b>{html.escape(entry.group)}/{html.escape(entry.name)}</b>")
        dlg.add_text("הקובץ יימחק מהבנק לצמיתות. להמשיך?", "hint")
        dlg.add_button("מחק", "del", "btnDanger")
        dlg.add_button("ביטול", "", default=True)
        if dlg.run() != "del":
            return
        scatter_bank.delete_entry(entry)
        self._say("warning", f"נמחק מהבנק: {entry.name}")
        self.toasts.show("ok", "נמחק מהבנק")
        self._refresh_bank()

    def _bank_open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(scatter_bank.bank_root())))

    def _bank_back(self):
        """חזרה מבנק הסקטארים אל לשוניות התוכנה."""
        if getattr(self, "_bank_active", False):
            self._toggle_bank_view()

    # ------------------------------------------------------------ לשונית שאיבה
    def _tab_readback(self) -> QWidget:
        """לשונית שאיבה (לפי הדמו): מחיצות (מצב ריק ← טבלה) · תיקיית יעד."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(14)
        v.addWidget(ui_kit.tab_header(
            "שאיבה (Readback)",
            "העתקת מחיצות מהמכשיר לקבצים במחשב — גיבוי לפני צריבה, או לשחזור בעתיד.",
            "mtkclient (BROM)"))
        grid = self._cards_grid()
        grid.setColumnStretch(0, 2)

        c_parts = ui_kit.Card("מחיצות", "סמן את המחיצות לשאיבה", "database",
                              ui_kit.Pill("קריאה בלבד", "ok"))
        self.part_list = QTableWidget(0, 4)
        self.part_list.setHorizontalHeaderLabels(["✔", "מחיצה", "התחלה", "גודל"])
        hh = self.part_list.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.part_list.verticalHeader().setVisible(False)
        self.part_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.part_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.part_list.setMinimumHeight(330)
        self.part_list.itemChanged.connect(self._update_selection_label)
        self.part_list.cellClicked.connect(self._toggle_row_check)
        # לפני קריאת GPT — מצב ריק עם כפתור לצעד הבא (כמו בדמו)
        b_gpt_empty = QPushButton("קרא טבלת מחיצות (GPT)")
        b_gpt_empty.setObjectName("btnPrimary")
        b_gpt_empty.clicked.connect(self._read_gpt)
        self._parts_empty = ui_kit.EmptyBox("עדיין לא נקראה טבלת מחיצות מהמכשיר.",
                                            b_gpt_empty, min_height=240)
        # הטבלה ושורת הבחירה — מוצגות אחרי קריאת GPT (לפני כן: מצב ריק עם כפתור)
        self._parts_page = QWidget()
        pv = QVBoxLayout(self._parts_page)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(12)
        pv.addWidget(self.part_list)
        sel_row = QHBoxLayout()
        sel_row.setSpacing(8)
        b_all = QPushButton("סמן הכל")
        b_all.clicked.connect(lambda: self._set_all_checks(True))
        b_none = QPushButton("נקה סימון")
        b_none.clicked.connect(lambda: self._set_all_checks(False))
        self.sel_label = QLabel("לא סומנו מחיצות")
        self.sel_label.setObjectName("hint")
        sel_row.addWidget(b_all)
        sel_row.addWidget(b_none)
        sel_row.addWidget(self.sel_label, 1)
        btn_dump_gpt = QPushButton("טען GPT לרשימה")
        btn_dump_gpt.setObjectName("btnGhost")
        btn_dump_gpt.clicked.connect(self._read_gpt)
        sel_row.addWidget(btn_dump_gpt)
        sel_row.addWidget(self._help_dot("gpt"))
        pv.addLayout(sel_row)
        self._parts_stack = QStackedWidget()
        self._parts_stack.addWidget(self._parts_empty)
        self._parts_stack.addWidget(self._parts_page)
        c_parts.add(self._parts_stack)
        self.btn_read_sel = QPushButton(" שאב מחיצות מסומנות")
        self.btn_read_sel.setObjectName("btnPrimary")   # הפעולה העיקרית בלשונית — בצבע ההדגשה
        self.btn_read_sel.setIcon(guiicons.curved_left_arrow_icon(color=theme.colors()["btn_text"]))
        self.btn_read_sel.clicked.connect(self._read_checked)
        c_parts.add_action(self.btn_read_sel)
        c_parts.add_action(self._help_dot("readback"))
        btn_read_all = QPushButton("שאב את כל המחיצות (rl)")
        btn_read_all.clicked.connect(self._read_all)
        c_parts.add_action(btn_read_all)
        btn_read_pre = QPushButton("שאב Preloader")
        btn_read_pre.clicked.connect(self._read_preloader)
        c_parts.add_action(btn_read_pre)
        grid.addWidget(c_parts, 0, 0)

        # הנתיב נשבר בכל תיקייה (ולא רק אחרי "C:") — כך הכרטיס הצר לא נמתח; מיושר לימין
        c_dest = ui_kit.Card("תיקיית יעד", "\u200f" + ui_kit.breakable_path(str(config.DUMPS_DIR)),
                             "folder")
        c_dest.desc.setToolTip(str(config.DUMPS_DIR))
        btn_open = QPushButton("פתח תיקייה")
        btn_open.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(config.DUMPS_DIR))))
        c_dest.add_action(btn_open)
        grid.addWidget(self._side_column(c_dest), 0, 1)

        v.addLayout(grid)
        v.addStretch(1)
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
        # לפני קריאת GPT — מצב ריק עם כפתור; אחרי — הטבלה
        self._parts_stack.setCurrentWidget(self._parts_page if table.partitions else self._parts_empty)

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
        """לשונית צריבה (לפי הדמו): צריבת Image למחיצה · לפני שצורבים (רשימת בדיקה חיה)."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(14)
        v.addWidget(ui_kit.tab_header(
            "צריבה (Download)",
            "כתיבת קובץ Image על מחיצה במכשיר — עם גיבוי אוטומטי לפני כן.",
            "mtkclient (BROM)"))
        grid = self._cards_grid()
        grid.setColumnStretch(0, 2)

        c_fl = ui_kit.Card("צריבת Image למחיצה",
                           "בחר קובץ ומחיצה — הפקודה המדויקת תוצג לפני ההרצה", "download",
                           ui_kit.Pill("כתיבה", "warn"), danger=True)
        lbl_img = QLabel("קובץ Image")
        lbl_img.setObjectName("hint")
        c_fl.add(lbl_img)
        img_row = QHBoxLayout()
        img_row.setSpacing(8)
        self.image_edit = QLineEdit()
        self.image_edit.setPlaceholderText("לא נבחר קובץ")
        img_row.addWidget(self.image_edit, 1)
        btn_browse = QPushButton("בחר קובץ…")
        btn_browse.clicked.connect(self._browse_image)
        img_row.addWidget(btn_browse)
        c_fl.add_layout(img_row)
        lbl_part = QLabel("מחיצת יעד")
        lbl_part.setObjectName("hint")
        c_fl.add(lbl_part)
        self.part_combo = QComboBox()
        self.part_combo.setPlaceholderText("— קודם קרא טבלת מחיצות —")
        c_fl.add(self.part_combo)
        # מחיצה רגישה — אזהרה אדומה בתוך הכרטיס (כמו בדמו)
        self.flash_sens_note = QLabel("")
        self.flash_sens_note.setObjectName("noticeDanger")
        self.flash_sens_note.setWordWrap(True)
        self.flash_sens_note.setVisible(False)
        c_fl.add(self.flash_sens_note)
        self.backup_check = QCheckBox("גיבוי אוטומטי של המחיצה לפני צריבה (מומלץ)")
        self.backup_check.setChecked(True)
        c_fl.add(self.backup_check)
        btn_flash = QPushButton(" צרוב למחיצה")
        btn_flash.setObjectName("btnDanger")   # צריבה — כפתור אדום (כמו Download ב-SP Flash)
        btn_flash.setIcon(guiicons.down_arrow_icon(color="#ffffff"))   # לבן — נראה על האדום
        self.btn_flash_main = btn_flash
        btn_flash.clicked.connect(self._flash_image)
        c_fl.add_action(btn_flash)
        c_fl.add_action(self._help_dot("flash"))
        grid.addWidget(c_fl, 0, 0)

        c_pre = ui_kit.Card("לפני שצורבים", "מתעדכן לבד לפי מצב המכשיר", "doc_check")
        self.preflash = ui_kit.Checklist([
            "מחובר בערוץ mtkclient\u200f (BROM)\u200f",
            "טבלת המחיצות נקראה",
            "נבחרו קובץ ומחיצה",
            "גיבוי אוטומטי לפני הצריבה",
        ])
        c_pre.add(self.preflash)
        info = QLabel(
            "סדר הפעולה: אימות גודל ← גיבוי המחיצה הקיימת (+SHA256) אל workspace\\backups ← צריבה.\n"
            "אם הגיבוי נכשל — הצריבה לא מתבצעת.\n"
            "מצבי SP Flash\u200f (Download Only / Format All)\u200f — בתכנון.")
        info.setObjectName("hint")
        info.setWordWrap(True)
        c_pre.add(info)
        grid.addWidget(self._side_column(c_pre), 0, 1)

        self.image_edit.textChanged.connect(self._update_preflash)
        self.part_combo.currentTextChanged.connect(self._on_flash_part_changed)
        self.backup_check.toggled.connect(self._update_preflash)

        v.addLayout(grid)
        v.addStretch(1)
        return w

    def _on_flash_part_changed(self, name: str):
        """מחיצה רגישה נבחרה — אזהרה אדומה בכרטיס הצריבה."""
        warn = get_partition_warning(name) if name else ""
        self.flash_sens_note.setText(f"\u200f⚠️ {name}: {warn}" if warn else "")
        self.flash_sens_note.setVisible(bool(warn))
        self._update_preflash()

    def _update_preflash(self, *_):
        """רשימת "לפני שצורבים" — מתעדכנת לפי מצב המכשיר והבחירות (תצוגה בלבד)."""
        if not hasattr(self, "preflash"):
            return
        mode = getattr(getattr(self, "_last_dev_info", None), "mode", "none")
        self.preflash.set_states([
            mode == "brom",
            self.gpt is not None,
            bool(self.image_edit.text().strip()) and bool(self.part_combo.currentText().strip()),
            self.backup_check.isChecked(),
        ])

    # ------------------------------------------------------------ לשונית Bootloader
    def _tab_bootloader(self) -> QWidget:
        """לשונית Bootloader (לפי הדמו): מצב אבטחה · פתיחה / נעילה — לפי ערוץ התקשורת."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(14)
        self._boot_header = ui_kit.tab_header(
            "Bootloader", "בדיקה, פתיחה ונעילה — לפי ערוץ התקשורת הפעיל.",
            chip_html="לפי הערוץ: <b>—</b>")
        v.addWidget(self._boot_header)
        grid = self._cards_grid()

        c_sec = ui_kit.Card(
            "מצב אבטחה / בוטלאודר",
            "בודק את מצב הבוטלאודר לפי ערוץ התקשורת הפעיל: ADB\u200f (getprop)\u200f · "
            "Fastboot\u200f (getvar)\u200f · mtkclient\u200f (gettargetconfig)\u200f. "
            "קריאה בלבד — לא משנה כלום במכשיר.", "shield", ui_kit.Pill("קריאה בלבד", "ok"))
        self.boot_status = QTextEdit()
        self.boot_status.setReadOnly(True)
        self.boot_status.setPlaceholderText(
            "לא נבדק עדיין. חבר מכשיר במצב BROM/Preloader ולחץ 'בדוק מצב אבטחה'.")
        self.boot_status.setMaximumHeight(150)
        c_sec.add(self.boot_status)
        b_check = QPushButton("בדוק מצב אבטחה / בוטלאודר")
        b_check.setObjectName("btnPrimary")
        b_check.clicked.connect(self._bootloader_check_router)
        c_sec.add_action(b_check)
        c_sec.add_action(self._help_dot("security"))
        grid.addWidget(c_sec, 0, 0)

        c_lock = ui_kit.Card(
            "פתיחה / נעילה",
            "הכפתורים פועלים לפי ערוץ התקשורת הפעיל: mtkclient\u200f (seccfg)\u200f · "
            "Fastboot\u200f (flashing)\u200f · "
            "ADB (מעביר אוטומטית ל-Fastboot).", "lock", ui_kit.Pill("מוחק נתונים", "danger"),
            danger=True)
        note = QLabel(
            "⚠️ פתיחת ה-Bootloader\u200f (Unlock)\u200f מוחקת את כל הנתונים מהמכשיר — תמונות, "
            "אפליקציות, הגדרות וכל נתוני המשתמש. ודא שיש לך גיבוי לפני שימוש!")
        note.setObjectName("noticeDanger")
        note.setWordWrap(True)
        c_lock.add(note)
        btn_unlock = QPushButton("פתח בוטלאודר")
        btn_unlock.setObjectName("btnDanger")
        btn_unlock.clicked.connect(lambda: self._bootloader_change_router(True))
        c_lock.add_action(btn_unlock)
        c_lock.add_action(self._help_dot("seccfg"))
        btn_lock = QPushButton("נעל בוטלאודר")
        btn_lock.setObjectName("btnDangerOutline")
        btn_lock.clicked.connect(lambda: self._bootloader_change_router(False))
        c_lock.add_action(btn_lock)
        grid.addWidget(c_lock, 0, 1)

        v.addLayout(grid)
        v.addStretch(1)
        return w

    def _update_boot_chip(self, *_):
        """התגית בכותרת לשונית Bootloader: "לפי הערוץ: X" — מתעדכנת עם הערוץ."""
        hdr = getattr(self, "_boot_header", None)
        if hdr is None or hdr.chip is None:
            return
        ch = self._effective_channel()
        label = self._channel_label(ch) if ch != "none" else "אין ערוץ פעיל"
        hdr.chip.setText(f"לפי הערוץ: <b>{ui_kit.ltr(label)}</b>")

    # ------------------------------------------------------------ לשונית בפיתוח (רוטינג אוטומטי)
    def _tab_dev_features(self) -> QWidget:
        """לשונית בפיתוח (לפי הדמו): תגית "ניסיוני", אזהרה, ושתי ארכיטקטורות."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(14)
        v.addWidget(ui_kit.tab_header(
            "בפיתוח", "תהליכי רוט ניסיוניים — עדיין בבדיקה.",
            extra=(ui_kit.Pill("ניסיוני", "warn"),)))
        warn = QLabel(
            "⚠️ תכונה ניסיונית בפיתוח. כל שלב מוצג לאישור מפורש לפני שהוא רץ, וגיבוי "
            "אוטומטי נשמר לפני כל כתיבה — אך המסלול טרם נבדק על מכשיר אמיתי. מומלץ "
            "להתחיל במכשיר לא-קריטי.")
        warn.setObjectName("noticeWarn")
        warn.setWordWrap(True)
        v.addWidget(warn)
        grid = self._cards_grid()

        c1 = ui_kit.Card("ארכיטקטורה 1 — BROM בלבד",
                         "מסלול מלא דרך mtkclient/BROM בלבד: זיהוי ← שאיבה ← פאץ' Magisk בצד "
                         "המחשב ← צריבה חזרה. לא דורש ADB/מצב מפתחים כלל.",
                         "spark", ui_kit.Pill("כתיבה", "warn"))
        c1.add(ui_kit.steps_list(["זיהוי ושאיבה דרך BROM",
                                  "פאץ' Magisk בצד המחשב",
                                  "צריבה חזרה דרך BROM"]))
        b1 = QPushButton("התחל רוטינג אוטומטי (BROM)")
        b1.setObjectName("btnPrimary")
        b1.clicked.connect(lambda: self._dev_start_architecture(False))
        c1.add_action(b1)
        c1.add_action(self._help_dot("root_brom"))
        grid.addWidget(c1, 0, 0)

        c2 = ui_kit.Card("ארכיטקטורה 2 — עם Fastboot",
                         "זהה לחלוטין לארכיטקטורה 1 בזיהוי/שאיבה/פאץ' — אך Unlock ו-Write עוברים "
                         "ל-Fastboot כשל-BROM אין הרשאת כתיבה (seccfg). דורש אישור פיזי "
                         "בכפתורי עוצמת קול על המכשיר, ו-OEM Unlocking דלוק במצב מפתחים.",
                         "bolt", ui_kit.Pill("כתיבה", "warn"))
        c2.add(ui_kit.steps_list(["זיהוי ושאיבה דרך BROM",
                                  "פאץ' Magisk בצד המחשב",
                                  "פתיחה וצריבה דרך Fastboot (אישור בכפתורי עוצמת הקול)"]))
        b2 = QPushButton("התחל רוטינג אוטומטי (עם Fastboot)")
        b2.setObjectName("btnPrimary")
        b2.clicked.connect(lambda: self._dev_start_architecture(True))
        c2.add_action(b2)
        c2.add_action(self._help_dot("root_fastboot"))
        grid.addWidget(c2, 0, 1)

        v.addLayout(grid)
        v.addStretch(1)
        return w

    def _dev_scan_magisk_apks(self):
        d = config.PROJECT_ROOT / "tools" / "Magisk"
        return sorted(d.glob("Magisk-v*.apk"), reverse=True)

    def _dev_config_dialog(self, use_fastboot: bool):
        """אשף (חלון Modal) בשלבים: גרסת Magisk -> ABI -> מתקדם -> [Unlock] -> סיכום.
        מחזיר dict של הבחירות, או None בביטול."""
        apks = self._dev_scan_magisk_apks()
        if not apks:
            ui_kit.MessageBox.critical(self, "אין קובצי Magisk",
                                 "לא נמצאו קובצי Magisk-vX.apk בתוך tools\\Magisk.")
            return None
        guessed_cpu = getattr(self.gpt, "cpu", "") if self.gpt else ""
        guess = magisk_patch.guess_abi(guessed_cpu)
        wiz = _DevRootWizard(apks, guess, guessed_cpu, use_fastboot, self)
        if wiz.run() != "finish":
            return None
        return {
            "magisk_apk": wiz.magisk_page.combo.currentData(),
            "abi": wiz.abi_page.combo.currentData(),
            "keep_verity": wiz.adv_page.keep_verity.isChecked(),
            "keep_forceencrypt": wiz.adv_page.keep_fe.isChecked(),
            "legacy_sar": wiz.adv_page.legacy_sar.isChecked(),
            "do_seccfg_unlock": wiz.unlock_page.unlock_cb.isChecked() if wiz.unlock_page else False,
        }

    def _dev_start_architecture(self, use_fastboot: bool):
        if job_manager.busy:
            ui_kit.MessageBox.warning(self, "עסוק", "יש פעולה פעילה — המתן לסיומה.")
            return
        cfg = self._dev_config_dialog(use_fastboot)
        if cfg is None:
            return
        state = root_pipeline.PipelineState(
            magisk_apk=cfg["magisk_apk"], magiskboot_abi=cfg["abi"],
            do_seccfg_unlock=cfg["do_seccfg_unlock"], keep_verity=cfg["keep_verity"],
            keep_forceencrypt=cfg["keep_forceencrypt"], legacy_sar=cfg["legacy_sar"])
        state.job_dir = root_audit.new_job_dir()
        self._dev_submit_job1(state, use_fastboot)

    def _dev_submit_job1(self, state, use_fastboot: bool):
        def _build():
            job = root_pipeline.build_job1_analyze(state)
            job.on_done = lambda ok: bus.root_pipeline_step.emit(
                {"stage": "job1", "ok": ok, "state": state, "use_fastboot": use_fastboot})
            return job
        self._request(self._plan(_build))

    def _dev_submit_job1b(self, state, use_fastboot: bool):
        def _build():
            job = root_pipeline.build_job1b_preflight(state)
            job.on_done = lambda ok: bus.root_pipeline_step.emit(
                {"stage": "job1b", "ok": ok, "state": state, "use_fastboot": use_fastboot})
            return job
        self._request(self._plan(_build))

    def _dev_submit_job2(self, state, use_fastboot: bool):
        def _build():
            builder = (root_pipeline.build_job2_fastboot if use_fastboot
                      else root_pipeline.build_job2_brom)
            job = builder(state)
            job.on_done = lambda ok: bus.root_pipeline_step.emit(
                {"stage": "job2", "ok": ok, "state": state, "use_fastboot": use_fastboot})
            return job
        self._request(self._plan(_build))

    def _on_root_pipeline_step(self, payload: dict):
        """מנותב מ-bus.root_pipeline_step (thread-safe) — רץ ב-thread הראשי בלבד."""
        stage = payload["stage"]
        ok = payload["ok"]
        state = payload["state"]
        use_fastboot = payload["use_fastboot"]
        if stage == "job1":
            if not ok:
                ui_kit.MessageBox.critical(self, "שלב 1 נכשל",
                                     "הניתוח/הפאץ' נכשלו — לא נכתב כלום למכשיר. "
                                     "פרטים בלשונית הלוג.")
                return
            self._dev_submit_job1b(state, use_fastboot)
        elif stage == "job1b":
            if not ok:
                ui_kit.MessageBox.critical(self, "Preflight נכשל",
                                     "האימות לפני הכתיבה נכשל — הפעולה נעצרה ולא נכתב "
                                     "כלום למכשיר. פרטים בלשונית הלוג.")
                return
            report_text = state.preflight_report.as_text() if state.preflight_report else ""
            summary = (f"מחיצת יעד: {state.target_partition}\n"
                      f"Slot: {state.slot_detail}\n"
                      f"vbmeta עצמאי: {'כן' if state.has_vbmeta else 'לא'}\n\n"
                      f"Preflight:\n{report_text}")
            box = ui_kit.Modal(self, "תוצאות שלב 1 — לפני כתיבה סופית", icon="info", wide=True)
            box.add_text("הניתוח הושלם. לבדוק ולהמשיך לכתיבה הסופית?", "hint")
            ui_kit.MessageBox.add_body(box, summary)
            box.add_button("🔥 המשך לכתיבה הסופית", "go", "btnDanger")
            box.add_button("ביטול", "", default=True)
            if box.run() == "go":
                self._dev_submit_job2(state, use_fastboot)
        elif stage == "job2":
            if ok:
                ui_kit.MessageBox.information(self, "רוטינג הושלם",
                                        "הכתיבה אומתה בהצלחה (SHA256 תואם).\n"
                                        f"תיעוד מלא נשמר ב:\n{state.job_dir}")
            else:
                ui_kit.MessageBox.critical(self, "הכתיבה נכשלה",
                                     "הכתיבה/האימות נכשלו — פרטים בלשונית הלוג.\n"
                                     f"גיבוי המקור נשמר ב:\n{state.job_dir / 'backups'}")


    # ------------------------------------------------------------ לשונית Fastboot
    def _tab_fastboot(self) -> QWidget:
        """לשונית Fastboot (לפי הדמו): זיהוי ומידע · צריבה/מחיקה · אתחול · בוטלאודר ·
        דרייברים. אותן פונקציות כמו קודם."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(14)
        b_fb_help = QPushButton("הוראות Fastboot")
        b_fb_help.clicked.connect(lambda: self._show_mode_instructions("fastboot"))
        v.addWidget(ui_kit.tab_header(
            "Fastboot", "צריבה ומחיקה לפי שם מחיצה, ופעולות בוטלאודר.", "Fastboot",
            extra=(b_fb_help,)))
        grid = self._cards_grid()

        # ---- זיהוי ומידע (קריאה בלבד)
        c_id = ui_kit.Card("זיהוי ומידע",
                           "המכשיר חייב להיות במצב Fastboot, ודרייבר 'Android Bootloader Interface' "
                           "מותקן. אחרת המכשיר לא יזוהה.", "search", ui_kit.Pill("קריאה בלבד", "ok"))
        # זיהוי אוטומטי: שם המכשיר ומצב הבוטלאודר מתעדכנים לבד כשמכשיר ב-Fastboot מחובר
        self.fb_auto_label = QLabel("לא מחובר מכשיר ב-Fastboot")
        self.fb_auto_label.setObjectName("statusTitle")
        self.fb_auto_label.setWordWrap(True)
        c_id.add(self.fb_auto_label)
        self.fb_status = QTextEdit()
        self.fb_status.setReadOnly(True)
        self.fb_status.setPlaceholderText("לא נבדק עדיין.")
        self.fb_status.setMaximumHeight(150)
        c_id.add(self.fb_status)
        b_dev = QPushButton("זהה מכשיר")
        b_dev.setObjectName("btnPrimary")
        b_dev.setToolTip("fastboot devices")
        b_dev.clicked.connect(self._fb_detect)
        c_id.add_action(b_dev)
        c_id.add_action(self._help_dot("fb_detect"))
        b_info = QPushButton("מידע ומצב נעילה")
        b_info.setToolTip("fastboot getvar all")
        b_info.clicked.connect(self._fb_info)
        c_id.add_action(b_info)
        c_id.add_action(self._help_dot("fb_info"))
        grid.addWidget(c_id, 0, 0)

        # ---- צריבה / מחיקה
        c_fl = ui_kit.Card("צריבה / מחיקה", "דורש בוטלאודר פתוח", "download",
                           ui_kit.Pill("כתיבה", "warn"), danger=True)
        lbl_img = QLabel("קובץ Image")
        lbl_img.setObjectName("hint")
        c_fl.add(lbl_img)
        img_row = QHBoxLayout()
        img_row.setSpacing(8)
        self.fb_image_edit = QLineEdit()
        self.fb_image_edit.setPlaceholderText("לא נבחר קובץ")
        img_row.addWidget(self.fb_image_edit, 1)
        b_browse = QPushButton("בחר קובץ…")
        b_browse.clicked.connect(self._fb_browse_image)
        img_row.addWidget(b_browse)
        c_fl.add_layout(img_row)
        lbl_part = QLabel("שם מחיצה")
        lbl_part.setObjectName("hint")
        c_fl.add(lbl_part)
        self.fb_part_edit = QLineEdit()
        self.fb_part_edit.setPlaceholderText("boot / recovery / vbmeta / …")
        c_fl.add(self.fb_part_edit)
        b_flash = QPushButton("צרוב")
        b_flash.setObjectName("btnDanger")
        b_flash.setToolTip("fastboot flash")
        b_flash.clicked.connect(self._fb_flash)
        c_fl.add_action(b_flash)
        c_fl.add_action(self._help_dot("fb_flash"))
        b_erase = QPushButton("מחק מחיצה")
        b_erase.setObjectName("btnDangerOutline")
        b_erase.setToolTip("fastboot erase")
        b_erase.clicked.connect(self._fb_erase)
        c_fl.add_action(b_erase)
        c_fl.add_action(self._help_dot("fb_erase"))
        grid.addWidget(c_fl, 0, 1)

        # ---- אתחול
        c_rb = ui_kit.Card("אתחול", "הפעלה מחדש למערכת, או חזרה ל-Fastboot", "reboot")
        b_rb = QPushButton("הפעל מחדש (מערכת)")
        b_rb.clicked.connect(lambda: self._fb_reboot(""))
        c_rb.add_action(b_rb)
        c_rb.add_action(self._help_dot("fb_reboot"))
        b_rbl = QPushButton("אתחל ל-Fastboot")
        b_rbl.setToolTip("מפעיל מחדש את המכשיר לתוך מצב ה-Bootloader\u200f (Fastboot)\u200f")
        b_rbl.clicked.connect(lambda: self._fb_reboot("bootloader"))
        c_rb.add_action(b_rbl)
        c_rb.add_action(self._help_dot("fb_reboot_bl"))
        grid.addWidget(c_rb, 1, 0)

        # ---- בוטלאודר — אותה פעולה כמו בלשונית Bootloader (עם האזהרה ו'אישור פעולה')
        c_bl = ui_kit.Card("בוטלאודר", "פתיחת הבוטלאודר מאפשרת צריבה", "unlock",
                           ui_kit.Pill("מוחק נתונים", "danger"), danger=True)
        b_unlock = QPushButton("פתח בוטלאודר")
        b_unlock.setObjectName("btnDanger")
        b_unlock.setToolTip("fastboot flashing unlock — ⚠️ מוחק את כל הנתונים במכשיר")
        b_unlock.clicked.connect(lambda: self._fastboot_lock_change(True))
        c_bl.add_action(b_unlock)
        c_bl.add_action(self._help_dot("fb_unlock"))
        grid.addWidget(c_bl, 1, 1)

        # ---- דרייברים למצב Fastboot (ברוחב מלא, בתחתית הלשונית)
        c_drv = ui_kit.Card("דרייברים למצב Fastboot",
                            "אם המכשיר לא מזוהה במצב Fastboot — צריך את הדרייבר "
                            "Android Bootloader Interface", "wrench")
        self.fb_drv_pill = ui_kit.Pill("לא נבדק", "neutral")   # מתעדכן אחרי "בדיקת דרייבר Fastboot"
        c_drv.add(self._kv_status_box([("ממשק Bootloader של Android", self.fb_drv_pill)]))
        b_fix = self._fix_driver_button()
        b_fix.setText("תקן דרייבר למכשיר המחובר")
        b_fix.setObjectName("btnSoft")
        c_drv.add_action(b_fix)
        b_drv_check = QPushButton("בדיקת דרייבר Fastboot")
        b_drv_check.setToolTip("בדיקה קריאה-בלבד: האם דרייבר Android Bootloader "
                               "Interface מותקן במחשב הזה")
        b_drv_check.clicked.connect(lambda: self._check_drivers("fastboot"))
        c_drv.add_action(b_drv_check)
        c_drv.add_action(ui_kit.menu_button("התקנה והורדה", [
            ("התקנת דרייבר Fastboot (מתוך התוכנה)", lambda: self._install_android_drivers("Fastboot")),
            None,
            ("הורדת דרייבר Fastboot\u200f (Google)\u200f", lambda: QDesktopServices.openUrl(
                QUrl("https://developer.android.com/studio/run/win-usb"))),
        ]))
        grid.addWidget(c_drv, 2, 0, 1, 2)

        v.addLayout(grid)
        v.addStretch(1)
        return w

    def _fb_browse_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר Image", "", "Image files (*.img *.bin);;All files (*)")
        if path:
            self.fb_image_edit.setText(path)

    def _fb_guard(self) -> bool:
        if not config.fastboot_available():
            ui_kit.MessageBox.warning(self, "אין fastboot",
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
        if info is None or getattr(info, "mode", "none") == "none":
            # אין מכשיר — המעבד בכותרת לא נשאר מחיבור קודם
            self.cpu_header.clear()
            self.cpu_header.setVisible(False)
        elif getattr(info, "cpu", ""):
            # המעבד בכרטיס המכשיר — מכל ערוץ, גם ADB (תצוגה בלבד: לא משנה את
            # שם המעבד בלשונית Scatter; זה נעשה רק מ-GPT / Fastboot כמו קודם)
            self.cpu_header.setText(info.cpu)
            self.cpu_header.setToolTip(f"מעבד שזוהה מהמכשיר: {info.cpu}")
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
        # מתח סוללה מתוך getvar all → לכותרת (רק אם המכשיר באמת דיווח ערך מספרי)
        volt = (vars_ or {}).get("מתח סוללה", "")
        mv = devinfo._parse_voltage_mv(volt) if volt else None
        if mv:
            prev = self._last_dev_info
            if prev is not None and getattr(prev, "mode", "") == "fastboot":
                prev.voltage_mv = mv
                prev.extra = f"מתח סוללה: {volt}"
                bus.device_info.emit(prev)
            else:
                bus.device_info.emit(devinfo.DeviceInfo(
                    mode="fastboot", model=(vars_ or {}).get("מוצר", ""),
                    voltage_mv=mv, extra=f"מתח סוללה: {volt}"))

    def _load_previous_logs(self):
        """#1: טוען לתצוגת הלוגים את הלוג מההפעלה הקודמת (לא נמחק בסגירה)."""
        try:
            files = sorted(config.LOGS_DIR.glob("log_*.txt"))
            files = [f for f in files if f.name != log.log_file.name]
            if not files:
                return
            prev = files[-1]
            text = prev.read_text(encoding="utf-8", errors="replace").splitlines()
            muted = theme.colors()["muted"]   # הלוג הקודם — באפור של הערכה
            # רמה "prev" — מוצג רק בסינון "הכל" (אין לשורות האלה רמה משלהן)
            self._log_add(
                "prev",
                f'<p dir="rtl" style="margin:0"><span style="color:{muted}">'
                f'──── לוג מהפעלה קודמת ({_log_bidi(prev.name)}) ────</span></p>',
                f"──── לוג מהפעלה קודמת ({prev.name}) ────")
            for line in text[-400:]:
                safe = _log_bidi(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                self._log_add(
                    "prev",
                    f'<p dir="rtl" style="margin:0"><span style="color:{muted}">{safe}</span></p>',
                    line)
            self._log_add(
                "prev",
                f'<p dir="rtl" style="margin:0"><span style="color:{muted}">'
                '──── סוף הלוג הקודם — פעולות חדשות מכאן ────</span></p>',
                "──── סוף הלוג הקודם — פעולות חדשות מכאן ────")
        except Exception:
            pass

    def _fb_flash(self):
        if not self._fb_guard():
            return
        self._retry_action = None   # צריבה לא חוזרת אוטומטית
        image = Path(self.fb_image_edit.text().strip())
        part = self.fb_part_edit.text().strip()
        if not part:
            ui_kit.MessageBox.warning(self, "חסר שם מחיצה", "הזן שם מחיצה (למשל boot)")
            return
        if not image.is_file():
            ui_kit.MessageBox.warning(self, "קובץ חסר", "בחר קובץ Image תקין")
            return
        self._request(self._plan(plan_fastboot_flash, part, image))

    def _fb_erase(self):
        if not self._fb_guard():
            return
        self._retry_action = None
        part = self.fb_part_edit.text().strip()
        if not part:
            ui_kit.MessageBox.warning(self, "חסר שם מחיצה", "הזן שם מחיצה למחיקה")
            return
        self._request(self._plan(plan_fastboot_erase, part))

    def _fb_reboot(self, target: str):
        if not self._fb_guard():
            return
        self._retry_action = None
        name = "Fastboot: הפעלה מחדש" + (f" ({target})" if target else "")
        self._request(self._plan(
            lambda: plan_fastboot_simple(name, FastbootCommands.reboot(target), retries=0,
                                         kind="write")))

    # ------------------------------------------------------------ לשונית ניהול
    def _detect_pyenv(self, quiet: bool = False):
        """זיהוי סביבת פייתון ברקע — לא משנה שום דבר, רק מדווח."""
        from ..core import pyenv
        self._pyenv_quiet = quiet
        if not quiet:
            self.pyenv_text.setPlainText("בודק…")
            self.pyenv_status.set("בודק…")

        def work():
            try:
                bus.pyenv_report.emit(pyenv.detect())
            except Exception as e:
                self._say("error", f"זיהוי סביבת פייתון נכשל: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _set_pyenv(self, rep):
        self.pyenv_text.setPlainText(rep.summary())
        self._set_pyenv_status(rep.summary(), rep.ok)
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
        if ui_kit.MessageBox.question(
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
        if confirm and ui_kit.MessageBox.question(
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
            self._toast_result("ok", msg.splitlines()[0], msg, "פייתון מוכן")
            self._detect_pyenv()
            return
        self._say("error", f"התקנת פייתון נכשלה: {msg.splitlines()[0]}")
        self._toast("err", f"התקנת פייתון נכשלה: {msg.splitlines()[0]}",
                    [("מה לעשות", lambda: self._show_pyinstall_help(msg))])

    def _show_pyinstall_help(self, msg: str):
        """איך להתקין ידנית אחרי שההתקנה האוטומטית נכשלה (נפתח מ"מה לעשות")."""
        dlg = ui_kit.Modal(self, "ההתקנה האוטומטית לא הצליחה", icon="cross", wide=True)
        dlg.add_text(html.escape(msg).replace("\n", "<br>"), "reason")
        dlg.add_text("אפשר להתקין ידנית — 4 צעדים:", "secTitle")
        dlg.add(ui_kit.steps_list([html.escape(t) for t in (
            f"לחץ 'הורדת פייתון להתקנה' והורד את '{ui_kit.ltr('Windows installer (64-bit)')}'.",
            "פתח את הקובץ שהורד.",
            "⚠️ חשוב: בחלון הראשון, למטה, סמן את התיבה 'Add python.exe to PATH' — "
            "ורק אז לחץ 'Install Now'.",
            "בסיום — חזור לכאן ולחץ שוב על 'התקן פייתון וספריות (אוטומטי)' "
            "(הוא יתקין רק את הספריות).")]))
        dlg.add_text("או — בלי שום התקנה: 'הורדת פייתון נייד' (MTKClient Portable), "
                     "וחלץ את הקובץ ליד התוכנה.", "hint")
        dlg.add_button("הורדת פייתון להתקנה", "dl", "btnPrimary", default=True)
        dlg.add_button("הורדת פייתון נייד", "port", "btnSoft")
        dlg.add_button("סגור", "")
        key = dlg.run()
        if key == "dl":
            self._open_python_download()
        elif key == "port":
            QDesktopServices.openUrl(QUrl(_MTK_PORTABLE_URL))

    def _style_install_python(self, alert: bool):
        """כמו כל כפתורי התוכנה; מסגרת אדומה בולטת רק כשפייתון חסר (להפנות אליו)."""
        if alert:
            self.btn_install_python.setStyleSheet(
                f"QPushButton {{ border: 3px solid {theme.colors()['danger']}; border-radius: 10px; }}")
        else:
            self.btn_install_python.setStyleSheet("")

    def _open_python_download(self):
        from ..core import pyenv
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(pyenv.PYTHON_DOWNLOAD_URL))

    # ------------------------------------------------------------ לשונית לוגים
    def _tab_logs(self) -> QWidget:
        """לשונית לוג (לפי הדמו): סינון הכל / אזהרות / שגיאות, וכרטיס עם הלוג."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(14)
        self._log_entries: list = []   # (רמה, HTML, טקסט) — לסינון ולייצוא
        self._log_filter = "all"
        chips = []
        self._log_chips = {}
        self._log_chip_group = QButtonGroup(w)
        self._log_chip_group.setExclusive(True)
        for key, text in (("all", "הכל"), ("warning", "אזהרות"), ("error", "שגיאות")):
            b = QPushButton(text)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(key == "all")
            b.clicked.connect(lambda _=False, k=key: self._set_log_filter(k))
            self._log_chip_group.addButton(b)
            self._log_chips[key] = b
            chips.append(b)
        v.addWidget(ui_kit.tab_header(
            "לוג", "כל מה שהתוכנה עשתה — כולל הפקודות המדויקות והפלט שלהן.", extra=chips))
        card = QFrame()
        card.setObjectName("card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(22, 20, 22, 20)
        cv.setSpacing(14)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        # כתב ברוחב קבוע (כמו בדמו); עברית נופלת אוטומטית לגופן שתומך בה
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        _base = QApplication.instance().font().pointSizeF()
        mono.setPointSizeF(_base if _base > 0 else 9.0)
        self.log_view.setFont(mono)
        # כל שורות הלוג מימין לשמאל — גם שורות שמתחילות באנגלית (פלט mtkclient)
        _opt = self.log_view.document().defaultTextOption()
        _opt.setTextDirection(Qt.LayoutDirection.RightToLeft)
        self.log_view.document().setDefaultTextOption(_opt)
        cv.addWidget(self.log_view, 1)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        b1 = QPushButton("ייצוא לוג")
        b1.clicked.connect(self._export_log)
        b2 = QPushButton("נקה תצוגה")
        b2.clicked.connect(self._log_clear)
        b3 = QPushButton("תיקיית הלוגים")
        b3.setObjectName("btnGhost")
        b3.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.LOGS_DIR))))
        for b in (b1, b2, b3):
            btns.addWidget(b)
        btns.addStretch(1)
        cv.addLayout(btns)
        v.addWidget(card, 1)
        return w

    def _log_add(self, level: str, html: str, plain: str):
        """שורה ללוג: נשמרת (לסינון ולייצוא), ומוצגת אם היא מתאימה לסינון הנוכחי."""
        self._log_entries.append((level, html, plain))
        if self._log_filter == "all" or level == self._log_filter:
            self.log_view.append(html)

    def _set_log_filter(self, key: str):
        """סינון הלוג: הכל / אזהרות / שגיאות (שורות הלוג הקודם — רק ב"הכל")."""
        self._log_filter = key
        self._log_chips[key].setChecked(True)
        self.log_view.setUpdatesEnabled(False)
        self.log_view.clear()
        for level, html, _plain in self._log_entries:
            if key == "all" or level == key:
                self.log_view.append(html)
        self.log_view.setUpdatesEnabled(True)

    def _log_clear(self):
        """נקה תצוגה — מנקה את הלוג המוצג (הקובץ בדיסק לא נמחק)."""
        self._log_entries.clear()
        self.log_view.clear()
        self._toast("info", "תצוגת הלוג נוקתה")

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
        bus.device_info.connect(self._update_boot_chip)      # "לפי הערוץ" בלשונית Bootloader
        bus.device_info.connect(self._update_preflash)       # "לפני שצורבים" בלשונית צריבה
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
        bus.root_pipeline_step.connect(self._on_root_pipeline_step)
        bus.toast.connect(lambda p: self._toast(*p))   # הודעות בצד מ-thread רקע
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
        safe = _log_bidi(message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        self._log_add(
            level,
            f'<p dir="rtl" style="margin:0">'
            f'<span style="color:{colors["stamp"]}">[{stamp}]</span> '
            f'<span style="color:{colors.get(level, colors["info"])}">{safe}</span></p>',
            f"[{stamp}] {message}")

    def _busy_progress(self, on: bool):
        """מד התקדמות 'רץ' (marquee) כשאין אחוזים — כדי שתמיד יהיה סימן חיים."""
        if on:
            self._progress_state("run")   # פעולה התחילה — כחול
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
        self._progress_state("idle")
        self.status_label.setText("מוכן")

    def _show_battery_warning(self, note: str):
        # משהים את הזיהוי התקופתי בזמן הדיאלוג — כדי שהוא לא יקפוץ שוב מאחוריו
        self._battery_probe_paused = True
        try:
            ui_kit.MessageBox.warning(
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
        self._progress_state("run")
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
            self._progress_state("ok")
            log.info(f"job_done (thread ראשי): {name} — לפני דיאלוג הצלחה")
            self._show_success(name)
            log.info(f"job_done: {name} — אחרי דיאלוג הצלחה")
            # אחרי קריאת GPT: הצעת בדיקת בוטלאודר — סדרתית, אחרי שהדיאלוג נסגר
            if name == "קריאת GPT" and self.gpt is not None:
                self._offer_bootloader_check()
        elif cancelled:
            self.status_label.setText(f"{name}: בוטל על ידי המשתמש")
            self._progress_state("err")
            self.toasts.show("err", f"{name} — בוטל")
        else:
            self.status_label.setText(f"{name}: ❌ נכשל")
            self._progress_state("err")
            self._show_failure(name)
        if getattr(self, "_clear_timer", None):
            self._clear_timer.start()   # ינוקה אחרי 30 שניות

    def _toast(self, kind: str, text: str, actions=()):
        """הודעה בצד (אם החלון כבר נבנה)."""
        host = getattr(self, "toasts", None)
        if host is not None:
            host.show(kind, text, actions)

    def _toast_result(self, kind: str, text: str, details: str = "", title: str = ""):
        """הודעה בצד על תוצאה; אם יש פירוט ארוך יותר — כפתור "פרטים" שפותח אותו."""
        actions = []
        if details and details.strip() != text.strip():
            actions.append(("פרטים", lambda: self._show_details(title or text, details, kind)))
        self._toast(kind, text, actions)

    def _show_details(self, title: str, details: str, kind: str = "info"):
        """הפירוט המלא של תוצאה (נפתח מהכפתור "פרטים" בהודעה)."""
        icon = {"ok": "check", "err": "cross", "warn": "alert"}.get(kind, "")
        dlg = ui_kit.Modal(self, title, icon=icon)
        dlg.add_text(html.escape(details).replace("\n", "<br>"))
        dlg.add_button("סגור", "", "btnPrimary", default=True)
        dlg.run()

    def _show_success(self, name: str):
        """הצלחה — הודעה ירוקה בצד (כמו בדמו). אם יש הסבר "שימושים" — כפתור "פרטים"."""
        expl = self._success_explanation(name)
        actions = [("פרטים", lambda: self._show_success_details(name, expl))] if expl else []
        self.toasts.show("ok", f"{name} — הושלם", actions)

    def _show_success_details(self, name: str, expl: str):
        """ההסבר על פעולה שהצליחה — מה נעשה ולמה זה משמש (נפתח מהכפתור "פרטים")."""
        dlg = ui_kit.Modal(self, "הפעולה הושלמה בהצלחה",
                           f"<b>{html.escape(name)}</b> הושלמה בהצלחה.", icon="check")
        dlg.add_text(html.escape(expl).replace("\n", "<br>"))
        dlg.add_button("סגור", "", "btnPrimary", default=True)
        dlg.run()

    def _failure_info(self, name: str, job) -> dict:
        """מה להציג על כשלון, לפי סוג הכשלון — אותם הסברים כמו קודם, מסודרים כמו בדמו:
        כותרת · סיבה · מה אפשר לעשות (צעדים) · האם להציע ניסיון דרך פורט COM."""
        from ..core.fastboot_bridge import FastbootCommand
        if job is not None and getattr(job, "no_fastboot_device", False):
            return {
                "title": "אין מכשיר במצב Fastboot",
                "short": "לא נמצא מכשיר במצב Fastboot",
                "reason": "לא נמצא מכשיר מחובר במצב Fastboot "
                          f"(המתנה של עד {int(FastbootCommand.DEVICE_TIMEOUT)} שניות).",
                "todo": ["מהמכשיר הדלוק: בלשונית ADB לחץ 'עבור למצב Fastboot'.",
                         "או: כבה את המכשיר, החזק ווליום למטה + הפעלה עד שמופיע מסך Fastboot, "
                         "וחבר בכבל USB.",
                         "אם המכשיר במסך Fastboot ועדיין לא מזוהה — בדוק את הדרייבר "
                         "(בדיקת דרייבר Fastboot, בתחתית הלשונית)."],
                "com": False,
            }
        if job is not None and getattr(job, "connection_failed", False):
            todo = ["כבה את המכשיר לגמרי ונתק את הכבל.",
                    "החזק את לחצן הווליום (למעלה, למטה, או שניהם — תלוי במכשיר) "
                    "וחבר את הכבל תוך כדי.",
                    "אם המכשיר דלוק ולא מגיב — החזק את לחצן ההפעלה כ-10 שניות תוך כדי החיבור.",
                    "אם החיבור נופל באמצע פעולה: נסה כבל אחר ויציאת USB ישירה במחשב (בלי מפצל)."]
            if self._retry_action is not None:
                todo.append("לחץ 'ניסיון חוזר' — ואז חבר את המכשיר.")
            return {
                "title": "החיבור למכשיר נכשל",
                "short": "החיבור למכשיר נכשל",
                "reason": f"החיבור למכשיר נכשל {job.retries + 1} פעמים "
                          f"(עד {int(job.connect_timeout)} שניות המתנה בכל ניסיון).",
                "todo": todo,
                # חלופה ל-UsbDk: ניסיון דרך פורט COM (דרייבר VCOM) — אם עוד לא מסומן
                "com": not self.serial_check.isChecked(),
            }
        return {
            "title": "הפעולה נכשלה",
            "short": "",
            "reason": "סיבות נפוצות: המכשיר יצא ממצב BROM/Preloader, התקשורת עם המעבד נותקה, "
                      "ה-DA לא נטען, או שהמכשיר תקול.",
            "todo": ["נסו להכניס את המכשיר שוב למצב BROM — נתק וחבר אותו מחדש.",
                     "בדוק את לשונית הלוגים לפירוט מלא."],
            "com": False,
        }

    def _failure_tech_lines(self) -> list[str]:
        """הפרטים הטכניים לחלון הכשלון: השגיאה האחרונה והשורות האחרונות מהלוג."""
        lines = []
        err = getattr(self, "_last_error", "")
        if err:
            lines.append(f"שגיאה אחרונה: {err}")
        recent = [plain for level, _html, plain in getattr(self, "_log_entries", [])
                  if level in ("raw", "error", "warning")][-8:]
        return lines + recent

    def _show_failure(self, name: str):
        """כשלון — הודעה אדומה בצד (נשארת פי 2 מהצלחה, עם ✕), ובה "מה לעשות" —
        חלון הכשלון עם ההסבר המלא — ו"ניסיון חוזר"."""
        info = self._failure_info(name, job_manager.last)
        retry = self._retry_action   # נשמר עכשיו: ההודעה לא חוסמת, ועד הלחיצה זה עלול להשתנות
        tech = self._failure_tech_lines()
        actions = [("מה לעשות", lambda: self._show_failure_details(name, info, retry, tech))]
        if retry is not None:
            actions.append(("ניסיון חוזר", lambda: self._retry_now(retry)))
        text = f"{name} — נכשל" + (f": {info['short']}" if info["short"] else "")
        self.toasts.show("err", text, actions)

    def _show_failure_details(self, name: str, info: dict, retry, tech: list[str]):
        """חלון הכשלון (כמו בדמו): סיבה · מה אפשר לעשות · פרטים טכניים · כפתורים."""
        dlg = ui_kit.Modal(self, info["title"], f"<b>{html.escape(name)}</b> לא הושלמה.",
                           icon="cross", wide=True)
        dlg.add_text(html.escape(info["reason"]), "reason")
        dlg.add_text("מה אפשר לעשות", "secTitle")
        dlg.add(ui_kit.steps_list([html.escape(t) for t in info["todo"]]))
        if tech:
            dlg.add(ui_kit.collapsible("הצג פרטים טכניים", ui_kit.mono_box(tech)))
        if retry is not None:
            dlg.add_button("ניסיון חוזר", "retry", "btnPrimary", default=True)
            if info.get("com"):
                b = dlg.add_button("נסה דרך פורט COM\u200f (VCOM)\u200f", "com", "btnSoft")
                b.setToolTip("חלופה כש-UsbDk חסום (למשל Windows 11 עם בידוד ליבה): "
                             "mtkclient יתחבר דרך דרייבר ה-VCOM. דורש דרייבר MediaTek VCOM מותקן.")
        dlg.add_button("פתח לוג", "log", "btnGhost")
        dlg.add_button("סגור", "", default=retry is None)
        key = dlg.run()
        if key == "com":
            self.serial_check.setChecked(True)   # נשאר מסומן לפעולות הבאות
            key = "retry"
        if key == "retry" and retry is not None:
            self._retry_now(retry)
        elif key == "log":
            self.tabs.setCurrentWidget(self.logs_tab)

    def _set_serialport(self, on: bool):
        """מתג 'חיבור דרך פורט COM' — חל על פעולות mtkclient הבאות (לא על פעולה שרצה)."""
        from ..core.mtk_bridge import MtkCommand
        MtkCommand.use_serialport = bool(on)
        if on:
            self._say("info", "mtkclient: חיבור דרך פורט COM (דרייבר VCOM, --serialport) — "
                              "במקום USB ישיר (UsbDk).")
        else:
            self._say("info", "mtkclient: חיבור USB ישיר (UsbDk) — ברירת המחדל.")

    def _cancel_job(self):
        """עצירת הפעולה ("בטל פעולה") — חלון כמו בדמו, לפי מה שקורה עכשיו: קריאה ·
        בזמן הגיבוי (הצריבה עוד לא התחילה) · באמצע כתיבה (עם מצב הגיבוי האמיתי)."""
        if not job_manager.busy:
            return
        cur = job_manager.current
        if cur is None:
            return
        kind = cur.effective_kind
        name = html.escape(cur.name)
        part = html.escape(cur.target)
        if kind == "danger" and cur.backup_path is not None and cur.step_index <= 0:
            dlg = ui_kit.Modal(self, "לעצור את הצריבה?", f"<b>{name}</b>")
            dlg.add_text(f"הצריבה עוד לא התחילה — כרגע נשמר גיבוי של המחיצה <b>{part}</b>. "
                         "עצירה עכשיו לא משנה כלום במכשיר.", "okNote")
            dlg.add_button("עצור", "stop", "btnDanger")
            dlg.add_button("המשך", "", default=True)
        elif kind == "danger":
            dlg = ui_kit.Modal(self, "לעצור באמצע פעולת כתיבה?", f"<b>{name}</b> עדיין רצה.",
                               icon="alert", wide=True)
            flashing = bool(cur.target) and "צריבת" in cur.name
            dlg.add_text("<b>עצירה עכשיו מסוכנת.</b> "
                         + ("המחיצה נכתבת כרגע" if flashing else "הפעולה משנה כרגע את המכשיר")
                         + " — עצירה באמצע עלולה להשאיר אותה פגומה, והמכשיר עלול לא לעלות.",
                         "reason")
            if cur.backup_path is not None:
                path = html.escape(ui_kit.ltr(ui_kit.breakable_path(str(cur.backup_path))))
                dlg.add_text(f"<b>יש גיבוי תקין.</b> לפני הצריבה נשמר גיבוי של המחיצה "
                             f"<b>{part}</b> ונבדק:<br>{path}<br>"
                             "אם תעצור ומשהו ישתבש — אפשר לצרוב אותו חזרה בלשונית צריבה.", "okNote")
            elif flashing and cur.channel == "fastboot":
                dlg.add_text("✕ <b>אין גיבוי.</b> בצריבה דרך Fastboot התוכנה לא מגבה את המחיצה "
                             "אוטומטית — אם תעצור ומשהו ישתבש, אין ממה לשחזר.", "reason")
            elif cur.backup_skipped:
                dlg.add_text("✕ <b>אין גיבוי.</b> האפשרות 'גיבוי אוטומטי של המחיצה לפני צריבה' "
                             "כובתה — אם תעצור ומשהו ישתבש, אין ממה לשחזר את המחיצה.", "reason")
            dlg.add_text("מומלץ לתת לפעולה להסתיים.", "hint")
            dlg.add_button("תן לפעולה להסתיים", "", "btnPrimary", default=True)
            dlg.add_button("עצור בכל זאת", "stop", "btnDangerOutline")
        else:
            dlg = ui_kit.Modal(self, "ביטול פעולה", f"<b>{name}</b>")
            dlg.add_text("לעצור את הפעולה? זו פעולת קריאה בלבד — העצירה לא פוגעת במכשיר."
                         if kind == "read" else "לעצור את הפעולה?", "hint")
            dlg.add_button("עצור", "stop", "btnDanger")
            dlg.add_button("המשך", "", default=True)
        if dlg.run() == "stop" and job_manager.current is cur:
            job_manager.cancel_current()
            self._show_cancelling()

    def _show_cancelling(self):
        """חיווי 'מבטל…' — מד התקדמות עם מילוי אדום עדין שנע לאורך הגליל, עד סיום הביטול."""
        self.progress.setRange(0, 0)   # marquee — נע לאורך כל הגליל
        self._progress_state("err")
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
                # חיבור חדש ב-ADB: הכותרת מתעדכנת מיד אחרי 'adb devices' (מהיר),
                # והפרטים (דגם/מעבד/סוללה) מושלמים כשהקריאה המלאה מסתיימת
                if tool in ("adb", "auto") and self._last_probe_mode != "adb":
                    _adb = config.find_adb_exe()
                    if _adb and devinfo.adb_device_state(str(_adb)) == "device":
                        bus.device_info.emit(devinfo.DeviceInfo(
                            mode="adb", model="מחובר — קורא פרטים…"))
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
                    # כל הודעה מציינת במפורש את הערוץ ומה נבדק — כדי שאפשר יהיה לוודא
                    # שערוץ מפורש לא מנסה ערוצים אחרים
                    tag = f"[ערוץ {self._channel_label(tool) if tool != 'auto' else 'אוטומטי'}]"
                    checked = {"adb": "ADB בלבד", "brom": "BROM/Preloader בלבד",
                               "auto": "ADB ואז BROM/Preloader"}.get(tool, tool)
                    if mode == "adb":
                        self._say("success", f"{tag} מכשיר זוהה ב-ADB — {info.model or info.cpu}")
                        bus.toast.emit(("ok", f"מכשיר התחבר ב-ADB — {info.model or info.cpu}"))
                    elif mode == "brom":
                        self._say("warning",
                                  f"{tag} נמצא פורט BROM/Preloader"
                                  + (" (לא נמצא מכשיר ב-ADB)" if tool == "auto" else "")
                                  + ". קרא GPT כדי לזהות את המעבד (mtkclient).")
                        bus.brom_detected.emit()   # הצעת GPT ב-thread הראשי
                        bus.toast.emit(("info", "נמצא מכשיר במצב BROM/Preloader"))
                    elif tool == "adb" and self._last_probe_mode == "adb":
                        self._say("warning", f"{tag} המכשיר לא עונה ב-ADB (נותק או נעול) — "
                                             "ממשיך לחכות לו ב-ADB בלבד.")
                        bus.toast.emit(("warn", "המכשיר לא עונה ב-ADB (נותק או נעול)"))
                    else:
                        self._say("info", f"{tag} אין מכשיר מחובר (נבדק: {checked})")
                        if self._last_probe_mode in ("adb", "brom", "fastboot"):
                            bus.toast.emit(("info", "המכשיר התנתק"))
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
            if ui_kit.MessageBox.question(
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
        # מראה בולט — כדי שהדיאלוג לא ייבלע ברקע של התוכנה. הצבעים מהערכה הפעילה (theme.py)
        c = theme.colors()
        accent = c["accent"]
        bg, banner, card, fg = c["surface"], c["surface2"], c["surface2"], c["text"]
        dlg.setStyleSheet(
            f"QDialog {{ background-color: {bg}; border: 2px solid {accent}; }}"
            f"QGroupBox {{ background-color: {card}; border: 1px solid {accent};"
            f" border-radius: 14px; color: {fg}; font-size: 12pt; font-weight: 700; }}"
            # כותרת האפשרות — לבנה, גדולה ומודגשת (כמו כותרות הכרטיסים); הכחולה הקטנה לא נקראה
            f"QGroupBox::title {{ color: {fg}; }}"
            f"QLabel {{ color: {fg}; font-weight: normal; font-size: 10.5pt; }}")
        v = QVBoxLayout(dlg)
        intro = QLabel(
            "באיזה כלי ברצונך לדבר עם המכשיר? החיפוש אחרי המכשיר יתחיל אחרי שתבחר.")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            f"background-color: {c['accent_soft']}; color: {fg}; font-size: 14pt;"
            f" font-weight: bold; padding: 14px; border: 1px solid {accent};"
            f" border-radius: 12px;")
        # בלי "הילה" סביב האותיות — במסך בגודל רגיל היא טשטשה את קצוות האותיות
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
            b_pick.setObjectName("btnPrimary")   # כפתור ראשי — צבעי הערכה
            b_pick.clicked.connect(lambda _=False, t=tool: self._select_tool(t, dlg))
            b_help = QPushButton("הוראות")
            b_help.clicked.connect(lambda _=False, t=tool: self._show_mode_instructions(t))
            row.addWidget(b_pick)
            row.addWidget(b_help)
            row.addStretch(1)
            gl.addLayout(row)
            return gb

        order = [
            add_option("ADB — המכשיר דלוק",
                       "כשהמכשיר דלוק ותקין — הדרך הפשוטה: מציג דגם, מעבד ואחוז סוללה, "
                       "ומאפשר ניהול אפליקציות (התקנת כל סגנונות החבילה/הסרה), סייר קבצים "
                       "מלא, בדיקת בוטלאודר והרשאות ניהול.", "adb"),
            add_option("Fastboot — הבוטלאודר",
                       "צריבה ומחיקה של מחיצות (קובצי \u200e.img) ופעולות בוטלאודר.\n"
                       "דורש: המכשיר במצב Fastboot ודרייבר מתאים.", "fastboot"),
            add_option("mtkclient — BROM/Preloader",
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
        b_unsure = QPushButton("אני לא יודע עדיין")
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
        q = ui_kit.Modal(self, "איך להתחבר למכשיר?", icon="info", wide=True)
        q.add_text("במכשיר שלך מופעל מצב מפתחים עם ניפוי באגים ב-USB?")
        q.add_text("אם המכשיר נדלק ואפשר להפעיל את זה — זו הדרך הפשוטה "
                   f"({ui_kit.ltr('ADB')}).<br>"
                   "אם המכשיר לא נדלק, תקוע, או שאי אפשר להפעיל — נעבור ל-"
                   f"{ui_kit.ltr('mtkclient')}.", "hint")
        q.add_button("כן, מופעל", "yes", "btnPrimary", default=True)
        q.add_button("לא, אבל אפשר להפעיל", "can", "btnSoft")
        q.add_button("לא / המכשיר לא נדלק", "no", "btnSoft")
        clicked = q.run()
        if clicked == "yes":
            self._select_tool("adb", None)
        elif clicked == "can":
            self._show_mode_instructions("adb")
            self._select_tool("adb", None)
        elif clicked == "no":
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
        """חלון הוראות מפורט לכל מצב תקשורת — בעיצוב החלונות החדשים: הקדמה · צעדים ·
        הערה."""
        esc = html.escape
        intro, steps_title, steps, note, note_kind, footer = "", "", [], "", "noticeInfo", ""
        if tool == "adb":
            title = "הוראות: הכנת המכשיר ל-ADB"
            steps_title = "מה לעשות במכשיר"
            steps = [
                "הגדרות ← על הטלפון/מידע על התוכנה ← הקש 7 פעמים על 'מספר ה-Build' "
                "עד להודעה 'אתה כעת מפתח'.",
                "חזור להגדרות ← מערכת ← אפשרויות מפתחים ← הפעל "
                "'ניפוי באגים USB' (USB Debugging).",
                "חבר את המכשיר בכבל USB — במסך המכשיר תופיע בקשת אישור "
                "'אפשר ניפוי באגים USB' — אשר אותה (ניתן לסמן 'תמיד').",
                "אם נשאל לגבי מצב USB — בחר 'העברת קבצים' (MTP).",
            ]
            footer = "כשהחיבור תקין, הדגם ואחוז הסוללה יופיעו אוטומטית בכותרת למעלה."
        elif tool == "fastboot":
            title = "הוראות: כניסה למצב Fastboot"
            intro = ("מצב Fastboot רץ על הבוטלאודר — שימושי לצריבת קובצי "
                     f"{ui_kit.ltr('.img')} לפי שם מחיצה (boot, recovery, vbmeta וכדומה), "
                     "מחיקת מחיצות ופעולות בוטלאודר.")
            steps_title = "כניסה למצב"
            steps = [
                "מהמכשיר הדלוק (עם ADB): לחץ בלשונית ADB על 'עבור למצב Fastboot' — "
                "התוכנה מריצה 'adb reboot bootloader' וממתינה לזיהוי המכשיר ב-Fastboot.",
                "או ידנית: כבה את המכשיר, ואז החזק כפתור הפעלה + ווליום מטה (או שני "
                "הווליומים — תלוי דגם) עד שמופיע לוגו Fastboot.",
            ]
            footer = ("דרישות: דרייבר 'Android Bootloader Interface' (כפתורי הדרייברים "
                      "בלשונית Fastboot), ולצריבה/מחיקה — בוטלאודר פתוח.")
            note = "<b>שים לב:</b> צריבת מחיצה שגויה עלולה להמית את המכשיר. גבה קודם!"
            note_kind = "noticeDanger"
        else:
            title = f"הוראות: חיבור במצב BROM/Preloader {ui_kit.ltr('(mtkclient)')}"
            intro = ("מצב BROM הוא השכבה הנמוכה ביותר בשבב — עובד גם כשהמכשיר כבוי, "
                     "תקול או נתקע בלולאת אתחול. דרכו ניתן לקרוא GPT, לשאוב ולצרוב מחיצות "
                     "ולנהל את הבוטלאודר.")
            steps_title = "כניסה למצב BROM"
            steps = [
                "כבה את המכשיר לגמרי (או הוצא את הסוללה אם ניתן).",
                "החזק את כפתורי ווליום מעלה + ווליום מטה (או את כל הכפתורים).",
                "תוך כדי ההחזקה — חבר את כבל ה-USB.",
            ]
            note = "<b>ל-Preloader:</b> חבר USB בלי ללחוץ על כפתורים כלל."
            footer = ("הזיהוי כאן אוטומטי — ברגע שפורט MTK מופיע, תוצע לך קריאת GPT "
                      "שמזהה גם את שם המעבד.")
        dlg = ui_kit.Modal(self, title, icon="info", wide=True)
        if intro:
            dlg.add_text(intro)
        dlg.add_text(esc(steps_title), "secTitle")
        dlg.add(ui_kit.steps_list([esc(t) for t in steps]))
        if note:
            dlg.add_text(note, note_kind)
        if footer:
            dlg.add_text(esc(footer), "hint")
        dlg.add_button("סגור", "", "btnPrimary", default=True)
        dlg.run()

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
            ui_kit.MessageBox.warning(
                self, "אין adb",
                "adb.exe לא נמצא. ודא שתיקיית tools מכילה את platform-tools "
                "(או הגדר ASKATEROOV_ADB).")
            return
        self.adb_info_view.setPlainText("קורא מהמכשיר…")

        def work():
            state = devinfo.adb_device_state(str(adb))
            if state == "unauthorized":
                bus.adb_details.emit(
                    "המכשיר מחובר, אבל ניפוי הבאגים לא אושר.\n\n"
                    "אשר במסך המכשיר את הבקשה 'לאפשר ניפוי באגים USB?' ונסה שוב.", "warning")
                return
            if state == "offline":
                bus.adb_details.emit(
                    "המכשיר מחובר אבל לא מגיב ב-ADB (offline).\n\n"
                    "נתק וחבר את הכבל, ואם צריך — כבה והפעל מחדש את ניפוי הבאגים במכשיר.",
                    "warning")
                return
            details = devinfo.collect_adb_details(str(adb)) if state == "device" else {}
            if details:
                text = "\n".join(f"{k}: {v}" for k, v in details.items())
                bus.adb_details.emit(text, "success")
                # סנכרון לכותרת למעלה (דגם / מעבד / סוללה) — גם כשערוץ התקשורת לא מתעדכן לבד
                try:
                    lvl = details.get("סוללה", "").rstrip("%").strip()
                    info = devinfo.DeviceInfo(
                        mode="adb",
                        model=details.get("דגם", ""),
                        # ro.hardware הוא לרוב שם הדגם — ממנו רק שם מעבד אמיתי (MTxxxx)
                        cpu=(devinfo._norm_cpu(details["מעבד (platform)"])
                             if details.get("מעבד (platform)")
                             else devinfo._strict_cpu(details.get("חומרה", ""))),
                        battery=int(lvl) if lvl.isdigit() else None)
                    bus.device_info.emit(info)
                except Exception:
                    pass
            else:
                text = ("המכשיר לא מחובר במצב מפתחים (ניפוי באגים USB).\n\n"
                        "בדוק: המכשיר דלוק ומחובר בכבל, ניפוי באגים USB מופעל ומאושר "
                        "(ראה כפתור ההוראות בדיאלוג הפתיחה), והדרייבר מותקן.")
                bus.adb_details.emit(text, "warning")

        threading.Thread(target=work, daemon=True).start()

    def _on_adb_details(self, text: str, level: str):
        """מציג את תוצאת קריאת מידע ה-ADB (נקרא ב-thread הראשי דרך אות)."""
        self.adb_info_view.setPlainText(text)
        self._say(level, "מידע ADB נקרא" if level == "success" else "לא נמצא מכשיר ב-ADB")

    # ------------------------------------------------------------ לשונית ADB
    def _tab_adb(self) -> QWidget:
        """לשונית ADB (לפי הדמו): כותרת לשונית + כרטיסים — מידע · התקנה · אפליקציות ·
        סייר קבצים · בוטלאודר · הרשאות ניהול · דרייבר. כל הכפתורים מפעילים את אותן
        פונקציות כמו קודם; רק הסידור והמראה השתנו."""
        from PySide6.QtCore import QSize
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(14)

        b_adb_help = QPushButton("הוראות ADB")
        b_adb_help.clicked.connect(lambda: self._show_mode_instructions("adb"))
        v.addWidget(ui_kit.tab_header(
            "ADB",
            "ניהול המכשיר הדלוק: מידע, אפליקציות, קבצים ומעבר ל-Fastboot. "
            "דורש ניפוי באגים USB מאושר במכשיר.",
            "ADB", extra=(b_adb_help,)))

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # ---- מידע על המכשיר (קריאה בלבד)
        c_info = ui_kit.Card("מידע על המכשיר", "דגם, מעבד, גרסת אנדרואיד וסוללה", "info",
                             ui_kit.Pill("קריאה בלבד", "ok"))
        # תצוגה חדשה, אותו ממשק (setPlainText) — שורות "שם ← ערך", או הודעה כשאין מכשיר
        self.adb_info_view = ui_kit.InfoPanel("לחץ 'קרא מידע' כדי לקרוא את פרטי המכשיר.")
        c_info.add(self.adb_info_view)
        b_read_info = QPushButton("קרא מידע")
        b_read_info.setObjectName("btnPrimary")
        b_read_info.clicked.connect(self._read_adb_details)
        c_info.add_action(b_read_info)
        c_info.add_action(self._help_dot("adb_info"))
        grid.addWidget(c_info, 0, 0)

        # ---- התקנת אפליקציה
        c_inst = ui_kit.Card("התקנת אפליקציה",
                             "בוחרים קובץ מהמחשב — גם חבילות מפוצלות מותקנות בבת אחת",
                             "download", ui_kit.Pill("כתיבה", "warn"))
        lbl_file = QLabel("קובץ להתקנה")
        lbl_file.setObjectName("hint")
        c_inst.add(lbl_file)
        row_in = QHBoxLayout()
        row_in.setSpacing(8)
        self.adb_apk_edit = QLineEdit()
        self.adb_apk_edit.setPlaceholderText("לא נבחר קובץ")
        row_in.addWidget(self.adb_apk_edit, 1)
        b_apk_browse = QPushButton("בחר קובץ…")
        b_apk_browse.clicked.connect(self._adb_browse_apk)
        row_in.addWidget(b_apk_browse)
        c_inst.add_layout(row_in)
        # סוגי החבילות — כתובים במפורש (לבקשת המשתמש)
        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(6)
        fmt_lbl = QLabel("סוגי חבילות שאפשר להתקין:")
        fmt_lbl.setObjectName("hint")
        fmt_row.addWidget(fmt_lbl)
        for name, tip in (("APK", "קובץ אפליקציה רגיל"),
                          ("APKM", "חבילה מפוצלת (APKMirror)"),
                          ("XAPK", "חבילה מפוצלת (APKPure)"),
                          ("APKS", "חבילה מפוצלת (SAI / bundletool)")):
            fmt_row.addWidget(ui_kit.Pill(name, "info", tip))
        fmt_row.addStretch(1)
        c_inst.add_layout(fmt_row)
        split_note = QLabel("APKM, XAPK ו-APKS הן חבילות מפוצלות — התוכנה מחלצת מהן את כל "
                            "החלקים ומתקינה אותם יחד.")
        split_note.setObjectName("hint")
        split_note.setWordWrap(True)
        c_inst.add(split_note)
        self.adb_reinstall_check = QCheckBox("עדכן אם האפליקציה כבר מותקנת (שומר את הנתונים שלה)")
        self.adb_reinstall_check.setToolTip("מאפשר התקנה על גבי גרסה קיימת במקום כישלון (-r)")
        self.adb_reinstall_check.setChecked(True)
        c_inst.add(self.adb_reinstall_check)
        self.adb_downgrade_check = QCheckBox("אפשר גם גרסה ישנה יותר")
        self.adb_downgrade_check.setToolTip(
            "מאפשר התקנה של גרסה נמוכה מהמותקנת (-d, VERSION_DOWNGRADE)")
        c_inst.add(self.adb_downgrade_check)
        b_install = QPushButton("התקן")
        b_install.setObjectName("btnPrimary")
        b_install.clicked.connect(self._adb_install)
        c_inst.add_action(b_install)
        c_inst.add_action(self._help_dot("adb_install"))
        grid.addWidget(c_inst, 0, 1)

        # ---- אפליקציות (ברוחב מלא)
        c_apps = ui_kit.Card("אפליקציות",
                             "האפליקציות המותקנות במכשיר — מידע, הסרה ובחירת חבילה", "apps")
        top_apps = QHBoxLayout()
        self.adb_sys_check = QCheckBox("הצג גם אפליקציות מערכת")
        top_apps.addWidget(self.adb_sys_check)
        top_apps.addStretch(1)
        c_apps.add_layout(top_apps)
        # טבלת אפליקציות: תמונה + שם אמיתי, חבילה, גרסה, גודל
        self.adb_apps_table = QTableWidget(0, 4)
        self.adb_apps_table.setHorizontalHeaderLabels(["אפליקציה", "שם חבילה", "גרסה", "גודל"])
        hh = self.adb_apps_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        # עמודת הגודל רחבה וקבועה (על חשבון שם החבילה, שנמתחת לשארית) — כך הגודל לא נחתך
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(3, 140)
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
        # לפני הטעינה הראשונה — מצב ריק (כמו בדמו); הטבלה מוצגת כשמגיעה רשימה
        self._apps_empty = ui_kit.EmptyState("הרשימה עוד לא נטענה — לחץ על ״טען רשימה״.")
        self._apps_empty.setMinimumHeight(160)
        self._apps_stack = QStackedWidget()
        self._apps_stack.addWidget(self._apps_empty)
        self._apps_stack.addWidget(self.adb_apps_table)
        c_apps.add(self._apps_stack)
        self._apps_gen = 0
        self._apps_rows: dict = {}
        # הודעות התקנה/הסרה/טעינה — בסגנון שקט
        self.adb_pkgs_view = QTextEdit()
        self.adb_pkgs_view.setObjectName("quietBox")
        self.adb_pkgs_view.setReadOnly(True)
        self.adb_pkgs_view.setPlaceholderText(
            "הודעות: טעינת הרשימה, התקנה והסרה. לחיצה על שורה בטבלה ממלאת את שדה ההסרה.")
        self.adb_pkgs_view.setMaximumHeight(54)
        c_apps.add(self.adb_pkgs_view)
        # הסרה לפי שם חבילה
        row_un = QHBoxLayout()
        row_un.setSpacing(8)
        lbl_un = QLabel("שם חבילה להסרה:")
        lbl_un.setObjectName("hint")
        row_un.addWidget(lbl_un)
        self.adb_pkg_edit = QLineEdit()
        self.adb_pkg_edit.setPlaceholderText("למשל com.example.app")
        row_un.addWidget(self.adb_pkg_edit, 1)
        b_paste = QPushButton("הדבק")
        b_paste.setToolTip("הדבקת שם חבילה שהועתק (למשל מתפריט הלחיצה הימנית בטבלה)")
        b_paste.clicked.connect(self._adb_paste_pkg)
        row_un.addWidget(b_paste)
        c_apps.add_layout(row_un)
        b_list = QPushButton("טען רשימה")
        b_list.setObjectName("btnPrimary")
        b_list.setToolTip("רשימת האפליקציות המותקנות במכשיר")
        b_list.clicked.connect(self._adb_list_packages)
        c_apps.add_action(b_list)
        c_apps.add_action(self._help_dot("adb_list"))
        b_info = QPushButton("מידע על האפליקציה")
        b_info.setToolTip("מידע מלא על האפליקציה שנבחרה (אפשר גם בלחיצה כפולה על שורה)")
        b_info.clicked.connect(self._adb_app_info)
        c_apps.add_action(b_info)
        spacer_apps = QWidget()
        c_apps.add_action(spacer_apps, 1)
        b_uninstall = QPushButton("הסר (מסומנות / לפי שם)")
        b_uninstall.setObjectName("btnDangerOutline")
        b_uninstall.setToolTip("מסיר את כל האפליקציות שסומנו ✔ בטבלה; "
                               "אם לא סומנה אף אחת — את החבילה שבשדה")
        b_uninstall.clicked.connect(self._adb_uninstall)
        c_apps.add_action(b_uninstall)
        c_apps.add_action(self._help_dot("adb_uninstall"))
        grid.addWidget(c_apps, 1, 0, 1, 2)

        # ---- סייר קבצים (ברוחב מלא, גדול)
        c_fs = ui_kit.Card("סייר קבצים",
                           "עיון בקבצים שבמכשיר, הורדה/העלאה, מחיקה, שינוי שם ועריכת טקסט. "
                           "בלי root הגישה מוגבלת ל-/sdcard.", "folder")
        bar = QHBoxLayout()
        bar.setSpacing(8)
        b_fs_up = ui_kit.icon_button("up", "תיקייה למעלה")
        b_fs_up.clicked.connect(self._fs_up)
        self._fs_up_btn = b_fs_up
        bar.addWidget(b_fs_up)
        # הנתיב — כל חלק בו הוא כפתור (כמו בדמו); ✎ מאפשר גם להקליד נתיב
        self._fs_crumbs = QFrame()
        self._fs_crumbs.setObjectName("crumbs")
        self._fs_crumbs.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._fs_crumbs.setMinimumHeight(38)
        self._fs_crumbs_lay = QHBoxLayout(self._fs_crumbs)
        self._fs_crumbs_lay.setContentsMargins(6, 2, 6, 2)
        self._fs_crumbs_lay.setSpacing(0)
        bar.addWidget(self._fs_crumbs, 1)
        self.fs_path_edit = QLineEdit("/sdcard")
        self.fs_path_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.fs_path_edit.setToolTip("הקלד נתיב ולחץ Enter")
        self.fs_path_edit.returnPressed.connect(self._fs_path_entered)
        self.fs_path_edit.setVisible(False)
        bar.addWidget(self.fs_path_edit, 1)
        b_fs_edit = ui_kit.icon_button("edit", "הקלדת נתיב")
        b_fs_edit.clicked.connect(self._fs_toggle_path_edit)
        bar.addWidget(b_fs_edit)
        b_fs_refresh = ui_kit.icon_button("refresh", "רענן")
        b_fs_refresh.clicked.connect(self._fs_refresh)
        bar.addWidget(b_fs_refresh)
        c_fs.add_layout(bar)
        self.fs_table = QTableWidget(0, 3)
        self.fs_table.setHorizontalHeaderLabels(["שם", "גודל", "סוג"])
        fhh = self.fs_table.horizontalHeader()
        fhh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        fhh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        fhh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.fs_table.verticalHeader().setVisible(False)
        self.fs_table.verticalHeader().setDefaultSectionSize(40)
        self.fs_table.setIconSize(QSize(18, 18))
        self.fs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.fs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.fs_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.fs_table.setMinimumHeight(380)
        self.fs_table.itemDoubleClicked.connect(self._fs_double_clicked)
        self.fs_table.itemSelectionChanged.connect(self._fs_selection_changed)
        # לפני הטעינה הראשונה — מצב ריק; הטבלה מוצגת כשמגיעה רשימת קבצים
        self._fs_empty = ui_kit.EmptyState("כדי לעיין בקבצים — התחבר בערוץ ADB ולחץ על ״רענן״.")
        self._fs_empty.setMinimumHeight(380)
        self._fs_stack = QStackedWidget()
        self._fs_stack.addWidget(self._fs_empty)
        self._fs_stack.addWidget(self.fs_table)
        c_fs.add(self._fs_stack)
        for text, slot, role in (("הורד למחשב", self._fs_download, "btnPrimary"),
                                 ("העלה קובץ…", self._fs_upload, ""),
                                 ("תיקייה חדשה", self._fs_mkdir, ""),
                                 ("שנה שם", self._fs_rename, ""),
                                 ("ערוך קובץ טקסט", self._fs_edit, "")):
            b = QPushButton(text)
            if role:
                b.setObjectName(role)
            b.clicked.connect(slot)
            c_fs.add_action(b)
        self._fs_sel_label = QLabel("")
        self._fs_sel_label.setObjectName("hint")
        c_fs.add_action(self._fs_sel_label, 1)
        b_fs_del = QPushButton("מחק")
        b_fs_del.setObjectName("btnDangerOutline")
        b_fs_del.clicked.connect(self._fs_delete)
        c_fs.add_action(b_fs_del)
        self._fs_entries: list = []
        self._fs_cwd = "/sdcard"
        self._fs_update_crumbs("/sdcard")
        self._fs_update_up_button("/sdcard")
        grid.addWidget(c_fs, 2, 0, 1, 2)

        # ---- בוטלאודר ומעבר ל-Fastboot (ברוחב מלא — ארבעה כפתורים)
        c_boot = ui_kit.Card("בוטלאודר ומעבר ל-Fastboot",
                             "בדיקת מצב הנעילה, ומעבר נוח למצב Fastboot", "bolt")
        self.adb_boot_view = QTextEdit()
        self.adb_boot_view.setReadOnly(True)
        self.adb_boot_view.setMaximumHeight(95)
        self.adb_boot_view.setPlaceholderText("לחץ 'בדוק מצב בוטלאודר'.")
        c_boot.add(self.adb_boot_view)
        b_boot_read = QPushButton("בדוק מצב בוטלאודר")
        b_boot_read.clicked.connect(self._adb_boot_read)
        c_boot.add_action(b_boot_read)
        # מעבר מ-Android (ADB) למצב Fastboot — בלי לגעת בבוטלאודר ובלי למחוק נתונים
        b_boot_fb = QPushButton("עבור למצב Fastboot")
        b_boot_fb.setObjectName("btnSoft")
        b_boot_fb.setToolTip("מאתחל את המכשיר הדלוק למצב Fastboot\u200f (adb reboot bootloader)\u200f "
                             "וממתין לזיהויו ב-Fastboot. הבוטלאודר לא נפתח ולא ננעל.")
        b_boot_fb.clicked.connect(self._adb_reboot_bootloader)
        c_boot.add_action(b_boot_fb)
        c_boot.add_action(self._help_dot("adb_reboot_bl"))
        spacer_boot = QWidget()
        c_boot.add_action(spacer_boot, 1)
        b_boot_unlock = QPushButton("פתח בוטלאודר")
        b_boot_unlock.setObjectName("btnDanger")
        b_boot_unlock.clicked.connect(lambda: self._adb_boot_change(True))
        c_boot.add_action(b_boot_unlock)
        b_boot_lock = QPushButton("נעל בוטלאודר")
        b_boot_lock.setObjectName("btnDangerOutline")
        b_boot_lock.clicked.connect(lambda: self._adb_boot_change(False))
        c_boot.add_action(b_boot_lock)
        grid.addWidget(c_boot, 3, 0, 1, 2)

        # ---- הרשאות ניהול מלאות (device owner / device admin)
        c_adm = ui_kit.Card("הרשאות ניהול מלאות",
                            "למשל לאפליקציות סינון — כדי שלא יהיה אפשר להסיר אותן", "admin",
                            ui_kit.Pill("כתיבה", "warn"))
        lbl_pkg = QLabel("חבילה")
        lbl_pkg.setObjectName("hint")
        c_adm.add(lbl_pkg)
        row_adm = QHBoxLayout()
        row_adm.setSpacing(8)
        self.adb_admin_edit = QLineEdit()
        self.adb_admin_edit.setPlaceholderText("com.example.filter  (או בחר שורה בטבלה)")
        row_adm.addWidget(self.adb_admin_edit, 1)
        b_adm_paste = QPushButton("הדבק")
        b_adm_paste.clicked.connect(
            lambda: self.adb_admin_edit.setText(
                (QApplication.clipboard().text() or "").strip().splitlines()[0]
                if (QApplication.clipboard().text() or "").strip() else ""))
        row_adm.addWidget(b_adm_paste)
        c_adm.add_layout(row_adm)
        adm_note = QLabel(
            "מעניק לאפליקציה הרשאות בעלים על המכשיר (device owner) — נדרש לרוב "
            "אפליקציות סינון/בקרת-הורים כדי שלא ניתן יהיה להסירן.\n"
            "⚠️ דרישות: המכשיר חייב להיות ללא חשבונות (כולל חשבון Google) — "
            "מומלץ לבצע מיד אחרי איפוס לפני הוספת חשבונות.\n"
            "⚠️ הסרת הבעלות בהמשך עלולה לדרוש איפוס להגדרות יצרן.")
        adm_note.setWordWrap(True)
        adm_note.setObjectName("noticeWarn")
        c_adm.add(adm_note)
        b_owner = QPushButton("הענק בעלות מלאה")
        b_owner.setObjectName("btnPrimary")
        b_owner.setToolTip("device owner")
        b_owner.clicked.connect(lambda: self._adb_grant_admin(owner=True))
        c_adm.add_action(b_owner)
        b_admin = QPushButton("הפעל כמנהל-התקן")
        b_admin.setToolTip("device admin")
        b_admin.clicked.connect(lambda: self._adb_grant_admin(owner=False))
        c_adm.add_action(b_admin)
        c_adm.add_action(self._help_dot("adb_admin"))
        grid.addWidget(c_adm, 4, 0)

        # ---- דרייבר ADB
        c_drv = ui_kit.Card("דרייבר ADB",
                            "אם המכשיר לא מזוהה ב-ADB — צריך את דרייבר ה-USB של Android "
                            "(Google USB Driver)", "wrench")
        drv_box = QFrame()
        drv_box.setObjectName("kvList")
        dh = QHBoxLayout(drv_box)
        dh.setContentsMargins(16, 10, 16, 10)
        drv_name = QLabel("ממשק ADB של Android")
        drv_name.setObjectName("kvVal")
        dh.addWidget(drv_name, 1)
        self.adb_drv_pill = ui_kit.Pill("לא נבדק", "neutral")   # מתעדכן אחרי "בדיקת דרייבר ADB"
        dh.addWidget(self.adb_drv_pill)
        c_drv.add(drv_box)
        b_fix = self._fix_driver_button()
        b_fix.setText("תקן דרייבר למכשיר המחובר")
        b_fix.setObjectName("btnSoft")
        c_drv.add_action(b_fix)
        b_adb_check = QPushButton("בדיקת דרייבר ADB")
        b_adb_check.setToolTip("בדיקה קריאה-בלבד: האם דרייבר ה-USB של Google "
                               "מותקן במחשב הזה")
        b_adb_check.clicked.connect(lambda: self._check_drivers("adb"))
        c_drv.add_action(b_adb_check)
        c_drv.add_action(ui_kit.menu_button("התקנה והורדה", [
            ("התקנת דרייבר ADB (מתוך התוכנה)", lambda: self._install_android_drivers("ADB")),
            None,
            ("הורדת דרייבר ADB\u200f (Google)\u200f", lambda: QDesktopServices.openUrl(
                QUrl("https://developer.android.com/studio/run/win-usb"))),
        ]))
        grid.addWidget(c_drv, 4, 1)

        v.addLayout(grid)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------ סייר קבצים — נתיב ובחירה
    # תיקיית הבסיס של הסייר — האחסון הפנימי של המשתמש (כל השמות שלה במכשירים שונים)
    _FS_HOME = "/sdcard"
    _FS_HOME_ALIASES = ("/sdcard", "/storage/emulated/0", "/storage/self/primary", "/mnt/sdcard")

    def _fs_home_prefix(self, path: str) -> str:
        """אם הנתיב בתוך האחסון הפנימי — מחזיר את הקידומת שלו (למשל /sdcard), אחרת ''."""
        p = (path or "").rstrip("/") or "/"
        for alias in self._FS_HOME_ALIASES:
            if p == alias or p.startswith(alias + "/"):
                return alias
        return ""

    def _fs_update_crumbs(self, path: str):
        """בונה את הנתיב שאפשר ללחוץ על כל חלק בו (כמו בדמו). הבסיס הוא האחסון הפנימי
        של המשתמש; נתיב מחוץ אליו (הוקלד ידנית) מציג גם כפתור "שורש המכשיר"."""
        lay = self._fs_crumbs_lay
        while lay.count():
            item = lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        def crumb(text: str, target: str):
            b = QPushButton(text)
            b.setObjectName("crumb")
            b.clicked.connect(lambda _=False, p=target: self._fs_load(p))
            lay.addWidget(b)

        def sep(text: str = "/"):
            s = QLabel(text)
            s.setObjectName("crumbSep")
            lay.addWidget(s)

        prefix = self._fs_home_prefix(path)
        crumb("אחסון פנימי", self._FS_HOME)   # הבסיס — תמיד ראשון וניתן ללחיצה
        if prefix:
            rest = [p for p in (path or "").rstrip("/")[len(prefix):].split("/") if p]
            acc = prefix
            for part in rest:
                acc += "/" + part
                sep()
                crumb(part, acc)
        else:
            sep("|")
            crumb("/", "/")
            acc = ""
            for part in [p for p in (path or "/").split("/") if p]:
                acc += "/" + part
                sep()
                crumb(part, acc)
        lay.addStretch(1)

    def _fs_toggle_path_edit(self):
        """✎ — מעבר בין הנתיב הלחיץ לבין שדה להקלדת נתיב."""
        editing = not self.fs_path_edit.isVisible()
        self.fs_path_edit.setVisible(editing)
        self._fs_crumbs.setVisible(not editing)
        if editing:
            self.fs_path_edit.setText(self._fs_cwd)
            self.fs_path_edit.setFocus()
            self.fs_path_edit.selectAll()

    def _fs_path_entered(self):
        self._fs_load(self.fs_path_edit.text().strip() or "/sdcard")
        if self.fs_path_edit.isVisible():
            self._fs_toggle_path_edit()

    def _fs_selection_changed(self):
        rows = self.fs_table.selectionModel().selectedRows()
        r = rows[0].row() if rows else -1
        if 0 <= r < len(self._fs_entries):
            self._fs_sel_label.setText(f"נבחר: {self._fs_entries[r].name}")
        else:
            self._fs_sel_label.setText(f"{len(self._fs_entries)} פריטים")

    def _fs_apply_icons(self):
        """סמלי תיקייה / קובץ / קישור בטבלת הסייר — מצוירים, בצבעי הערכה."""
        c = theme.colors()
        icons = {"dir": ui_kit.svg_icon("folder_fill", c["accent"], 18),
                 "link": ui_kit.svg_icon("link", c["muted"], 18),
                 "file": ui_kit.svg_icon("file", c["muted"], 18)}
        for r, e in enumerate(self._fs_entries):
            item = self.fs_table.item(r, 0)
            if item is not None:
                item.setIcon(icons["dir" if e.is_dir else ("link" if e.is_link else "file")])

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
            ui_kit.MessageBox.warning(self, "לא נבחרה אפליקציה",
                                "סמן ✔ אפליקציות בטבלה (אפשר כמה), או הזן שם חבילה בשדה.")
            return
        adb = config.find_adb_exe()
        if not adb:
            ui_kit.MessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
            return
        listing = "\n".join(pkgs[:15]) + (f"\n…ועוד {len(pkgs) - 15}" if len(pkgs) > 15 else "")
        keep = ui_kit.MessageBox.question(
            self, "הסרת אפליקציות",
            f"להסיר {len(pkgs)} אפליקציות?\n\n{listing}\n\n"
            "'כן' = הסרה מלאה (כולל נתונים).\n"
            "'לא' = הסרה תוך שמירת נתונים ומטמון (-k).",
            _YES | _NO, _NO)
        if keep == _NO:
            full = ui_kit.MessageBox.question(
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
        self._progress_state("run")
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
        color = QColor(theme.colors()["muted"]) if state else None
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
        self._progress_state("ok" if ok else "err")
        self.status_label.setText(f"{title}: {'הסתיים בהצלחה' if ok else '❌ נכשל'}")
        if getattr(self, "_clear_timer", None):
            self._clear_timer.start()
        first = text.splitlines()[0] if text else ""
        self.adb_pkgs_view.setPlainText(first)
        self._toast_result("ok" if ok else "err", f"{title}: {first}" if first else title, text, title)

    def _apps_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        pkg = self._selected_app_package()
        if not pkg:
            return
        app = getattr(self, "_apps_by_pkg", {}).get(pkg)
        m = QMenu(self)
        a_copy = m.addAction("העתק שם חבילה")
        a_field = m.addAction("העבר לשדה ההסרה")
        a_info = m.addAction("מידע על האפליקציה")
        a_restore = None
        if app is not None and app.removed_for_user:
            m.addSeparator()
            a_restore = m.addAction("שחזר אפליקציה (הוסרה מהמשתמש)")
        chosen = m.exec(self.adb_apps_table.viewport().mapToGlobal(pos))
        if chosen == a_copy:
            QApplication.clipboard().setText(pkg)
            self.status_label.setText(f"הועתק: {pkg}")
            self._toast("ok", f"הועתק: {pkg}")
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
            ui_kit.MessageBox.warning(self, "קובץ חסר", "בחר קובץ APK תקין")
            return
        adb = config.find_adb_exe()
        if not adb:
            ui_kit.MessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
            return
        reinstall = self.adb_reinstall_check.isChecked()
        allow_downgrade = self.adb_downgrade_check.isChecked()
        self._say("info", f"מתקין: {apk.name}")
        self.adb_pkgs_view.setPlainText("מתקין… (התקנה עשויה להימשך עד דקה)")
        if getattr(self, "_clear_timer", None):
            self._clear_timer.stop()
        self._progress_state("run")
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
        keep = ui_kit.MessageBox.question(
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
        self._progress_state("run")
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
            ui_kit.MessageBox.warning(self, "חסר שם חבילה",
                                "הזן שם חבילה או בחר אפליקציה בטבלה.")
            return
        adb = config.find_adb_exe()
        if not adb:
            ui_kit.MessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
            return
        kind = "בעלות מלאה על המכשיר (device owner)" if owner else "מנהל-התקן (device admin)"
        warn = ("⚠️ הענקת בעלות מלאה דורשת מכשיר ללא חשבונות (כולל Google), "
                "והסרתה בהמשך עלולה לדרוש איפוס יצרן.\n\n" if owner else "")
        if ui_kit.MessageBox.question(
                self, "אישור הענקת הרשאות",
                f"להעניק ל-{pkg} {kind}?\n\n{warn}להמשיך?",
                _YES | _NO, _NO) != _YES:
            return
        self._say("info", f"מעניק {kind} ל-{pkg}")
        self._progress_state("run")
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
            ui_kit.MessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
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
            self._toast("err", f"שגיאת גישה: {err}")
            return
        self._fs_entries = entries
        self._fs_cwd = path
        self.fs_path_edit.setText(path)
        self._fs_update_crumbs(path)
        self._fs_update_up_button(path)
        self._fs_stack.setCurrentWidget(self.fs_table)
        t = self.fs_table
        t.setRowCount(0)
        for e in entries:
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, QTableWidgetItem(e.name))   # הסמל — ב-_fs_apply_icons
            t.setItem(r, 1, QTableWidgetItem(f"\u2066{e.size_str}\u2069" if e.size_str else ""))
            t.setItem(r, 2, QTableWidgetItem(
                "תיקייה" if e.is_dir else ("קישור" if e.is_link else "קובץ")))
        self._fs_apply_icons()
        self._fs_selection_changed()
        self._say("info", f"סייר: {len(entries)} פריטים ב-{path}")

    def _fs_refresh(self):
        self._fs_load(self._fs_cwd)

    def _fs_up(self):
        from ..core import adb_files
        cwd = (self._fs_cwd or "").rstrip("/") or "/"
        if cwd in self._FS_HOME_ALIASES:
            self._toast("info", "זו תיקיית הבסיס — האחסון הפנימי. אפשר לעבור לנתיב אחר "
                                "בעזרת ✎ (הקלדת נתיב).")
            return
        self._fs_load(adb_files.posix_parent(cwd))

    def _fs_update_up_button(self, path: str):
        """כפתור "תיקייה למעלה" כבוי בתיקיית הבסיס (האחסון הפנימי) ובשורש המכשיר."""
        p = (path or "").rstrip("/") or "/"
        top = p == "/" or p in self._FS_HOME_ALIASES
        self._fs_up_btn.setEnabled(not top)
        self._fs_up_btn.setToolTip("זו תיקיית הבסיס" if top else "תיקייה למעלה")

    def _fs_selected(self):
        r = self.fs_table.currentRow()
        if r < 0 or r >= len(self._fs_entries):
            ui_kit.MessageBox.information(self, "בחר פריט", "בחר קובץ או תיקייה מהרשימה.")
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
        first = text.splitlines()[0] if text else ""
        self._toast_result("ok" if ok else "err", f"{title}: {first}" if first else title, text, title)
        if ok and refresh:
            self._fs_refresh()

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
        name, ok = ui_kit.MessageBox.get_text(self, "תיקייה חדשה", "שם התיקייה:")
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
        name, ok = ui_kit.MessageBox.get_text(self, "שינוי שם", "שם חדש:", text=e.name)
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
        if ui_kit.MessageBox.warning(
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
            ui_kit.MessageBox.information(self, "עריכה", "בחר קובץ טקסט, לא תיקייה.")
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
            self._toast("err", f"עריכה — המשיכה נכשלה: {msg}")
            return
        try:
            text = Path(local).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self._toast("err", f"עריכה — לא ניתן לקרוא את הקובץ: {e}")
            return
        dlg = _TextEditDialog(self, Path(local).name, text)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            Path(local).write_text(dlg.text(), encoding="utf-8")
        except OSError as e:
            self._toast("err", f"עריכה — שמירה מקומית נכשלה: {e}")
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
            ui_kit.MessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
            return
        include_sys = self.adb_sys_check.isChecked()
        self._apps_gen += 1
        gen = self._apps_gen
        self.adb_apps_table.setRowCount(0)
        self.adb_pkgs_view.setPlainText("קורא רשימת אפליקציות…")
        self._apps_loading = True
        if getattr(self, "_clear_timer", None):
            self._clear_timer.stop()
        self._progress_state("run")
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
        self._update_idle_header()
        if tool == "none":
            self._say("info", "ערוץ תקשורת: לא נבחר — אין חיפוש מכשיר עד שתבחר ערוץ.")
            self._toast("info", "ערוץ תקשורת: לא נבחר")
            bus.device_info.emit(devinfo.DeviceInfo(mode="none"))   # איפוס הכותרת מיד
            return
        names = {"auto": "אוטומטי", "adb": "ADB", "fastboot": "Fastboot",
                 "brom": "mtkclient\u200f (BROM)\u200f"}
        self._say("info", f"ערוץ תקשורת: {names.get(tool, tool)} — הזיהוי האוטומטי "
                          "ישתמש רק בו ולא ינסה דרכים אחרות.")
        self._toast("info", f"ערוץ תקשורת: {names.get(tool, tool)}")
        self._probe_device()

    def _set_active_tool(self, tool: str):
        """קובע ערוץ (מבחירת המשתמש או נעילה אחרי זיהוי ראשון)."""
        i = self.tool_combo.findData(tool)
        if i < 0:
            return
        if tool != self._active_tool:
            self._say("info", f"🔎 ערוץ תקשורת: {self._channel_label(tool)} — "
                              "מחפש מכשיר בערוץ הזה בלבד.")
            self._toast("info", f"ערוץ תקשורת: {self._channel_label(tool)}")
        self._active_tool = tool
        self.tool_combo.blockSignals(True)
        self.tool_combo.setCurrentIndex(i)
        self.tool_combo.blockSignals(False)
        self._update_idle_header()

    def _update_idle_header(self):
        """טקסט הכותרת כשאין מכשיר: 'אין ערוץ תקשורת פעיל' / 'עדיין אין חיבור בערוץ X'."""
        tool = self._active_tool
        if tool == "none":
            text = "אין ערוץ תקשורת פעיל — בחר ערוץ"
        elif tool == "auto":
            text = "עדיין אין חיבור (ערוץ אוטומטי)"
        else:
            text = f"עדיין אין חיבור בערוץ {self._channel_label(tool)}"
        self.device_status.set_idle_text(text)
        self._update_boot_chip()   # התגית "לפי הערוץ" בלשונית Bootloader

    # ---------------------------------------------------------- בוטלאודר דרך ADB
    def _adb_boot_read(self):
        adb = config.find_adb_exe()
        if not adb:
            ui_kit.MessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
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
            ui_kit.MessageBox.warning(self, "חסר כלי",
                                "צריך גם adb.exe וגם fastboot.exe בתיקיית tools.")
            return
        st = adb_boot.read_state(str(adb))
        if unlock and st.get("oem_allowed") is False:
            ui_kit.MessageBox.warning(
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
        if ui_kit.MessageBox.warning(self, "פתיחת בוטלאודר" if unlock else "נעילת בוטלאודר",
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
            ui_kit.MessageBox.warning(self, "אין adb", "adb.exe לא נמצא בתיקיית tools.")
            return
        if not device_info.adb_devices_connected(str(adb)):
            ui_kit.MessageBox.warning(
                self, "לא נמצא מכשיר ב-ADB",
                "כדי לעבור למצב Fastboot צריך מכשיר דלוק ומחובר ב-ADB.\n\n"
                "חבר את המכשיר בכבל USB ואשר במסך המכשיר את בקשת ניפוי הבאגים.")
            return

        def build():
            job = Job("מעבר למצב Fastboot\u200f (ADB → Fastboot)\u200f", [
                Step("אתחול למצב Fastboot", adb_boot.RebootToBootloader()),
                Step("המתנה למכשיר במצב Fastboot", adb_boot.WaitForFastboot(60)),
            ], kind="write")
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
        self._apps_stack.setCurrentWidget(self.adb_apps_table)
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
        t.item(r, 3).setText(f"\u2066{format_size(app.size)}\u2069" if app.size else "")
        # מד ההתקדמות למטה מתקדם עם הטעינה
        if self.progress.maximum() != total:
            self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status_label.setText(f"טוען אפליקציות… {done}/{total} ({done * 100 // total}%)")
        if done == total:
            self.status_label.setText(f"נטענו {total} אפליקציות")
            self._progress_state("ok")
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
            ui_kit.MessageBox.information(self, "מידע על אפליקציה",
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
        dlg = ui_kit.Modal(self, f"מידע על האפליקציה — {name}", wide=True)
        if icon is not None and not icon.isNull():
            pic = QLabel()
            pic.setPixmap(icon.pixmap(64, 64))
            dlg.add(pic, 0)
        kv = ui_kit.KeyValueList(150)
        kv.set_rows([(k, ui_kit.breakable_path(str(v))) for k, v in rows if v])
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(380)
        scroll.setStyleSheet("QScrollArea { background: transparent; }"
                             " QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(kv)
        dlg.add(scroll)
        dlg.add_button("סגור", "", "btnPrimary", default=True)
        dlg.run()

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
            dlg = ui_kit.Modal(self, "המכשיר לא זוהה",
                               "לא התקבל חיבור מהמכשיר במשך דקה ורבע.", icon="alert", wide=True)
            dlg.add_text("הניסיון לקרוא את טבלת המחיצות (GPT) דרך "
                         f"{ui_kit.ltr('mtkclient')} לא הצליח. "
                         "הכי נפוץ: המכשיר לא הוכנס נכון למצב BROM/Preloader.", "reason")
            dlg.add_text("איך לחבר נכון במצב Preloader/BROM", "secTitle")
            dlg.add(ui_kit.steps_list([
                "כבה את המכשיר לגמרי (או הוצא סוללה אם אפשר).",
                "חבר כבל USB למחשב — בלי המכשיר בצד השני.",
                "לחץ והחזק את הכפתורים (Volume Down / Volume Up — אחד מהם, "
                "או שניהם יחד, לפי דגם המכשיר).",
                "תוך כדי ההחזקה חבר את קצה ה-USB למכשיר, והמשך להחזיק עוד 3–5 שניות.",
                "ברגע החיבור המכשיר מופיע בפורט לשניות בודדות — זה תקין; "
                "הפעולה תופסת אותו אוטומטית.",
            ]))
            dlg.add_text("אם זה לא עוזר: החלף כבל/פורט USB, וודא שהדרייברים מותקנים "
                         f"(לשונית {ui_kit.ltr('mtkclient')} ← דרייברים — כולל דרייבר "
                         f"{ui_kit.ltr('VCOM/Preloader')} של MediaTek).", "hint")
            dlg.add_button("נסה שוב", "retry", "btnPrimary", default=True)
            dlg.add_button("סגור", "")
            self._gpt_timeout_dialog = dlg
            key = dlg.run()
            self._gpt_timeout_dialog = None
            if key == "retry":
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
        self._update_preflash()
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
            if ui_kit.MessageBox.question(
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
        # התגיות בכרטיסי הדרייברים (מותקן / לא מותקן)
        if kind == "adb" and hasattr(self, "adb_drv_pill"):
            self.adb_drv_pill.set("מותקן במחשב" if st.ok else "לא מותקן", "ok" if st.ok else "warn")
        elif kind == "fastboot" and hasattr(self, "fb_drv_pill"):
            self.fb_drv_pill.set("מותקן במחשב" if st.ok else "לא מותקן", "ok" if st.ok else "warn")
        elif kind == "mtk" and hasattr(self, "mtk_usbdk_pill"):
            # כל דרייבר בנפרד — לפי שורות הבדיקה ("✅ UsbDk: …" / "✅ דרייבר MediaTek: …")
            for pill, key in ((self.mtk_usbdk_pill, "UsbDk:"),
                              (self.mtk_vcom_pill, "דרייבר MediaTek:")):
                ok = any(ln.startswith("✅") and key in ln for ln in st.lines)
                pill.set("מותקן במחשב" if ok else "לא מותקן", "ok" if ok else "warn")
        text = drivers.format_status(st)
        for line in text.splitlines():
            self._say("info" if st.ok else "warning", line.strip())
        kind = "ok" if st.ok and not st.hint else "warn"
        state = "הכל תקין" if kind == "ok" else ("חסר דרייבר" if not st.ok else "יש מה לתקן")
        self._toast_result(kind, f"{st.title} — {state}", text, st.title)

    def _install_usbdk(self):
        # קובץ ההתקנה מגיע עם התוכנה (tools\usbdk.msi); גיבוי: התיקייה הניידת
        msi = config.PROJECT_ROOT / "tools" / "usbdk.msi"
        if not msi.is_file():
            msi = config.PORTABLE_ROOT / "usbdk.msi"
        if not msi.is_file():
            ui_kit.MessageBox.warning(self, "חסר",
                                f"לא נמצא usbdk.msi בתיקיית tools של התוכנה:\n{config.PROJECT_ROOT / 'tools'}")
            return
        if ui_kit.MessageBox.question(self, "התקנת דרייברים",
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
        b = QPushButton("תקן דרייבר למכשיר המחובר")
        b.setToolTip("מאתר מכשיר Android/MediaTek שמחובר בלי דרייבר ומצמיד לו את הדרייבר "
                     "המתאים מהתוכנה — גם כשהמזהה שלו לא מוכר (נדרשת הרשאת מנהל)")
        b.clicked.connect(self._fix_connected_driver)
        return b

    def _fix_connected_driver(self):
        """מריץ את tools\\fix_driver.ps1 בהרשאת מנהל ומציג את התוצאה."""
        tools = config.PROJECT_ROOT / "tools"
        ps1 = tools / "fix_driver.ps1"
        if not ps1.is_file():
            ui_kit.MessageBox.warning(self, "חסר", f"לא נמצא הקובץ:\n{ps1}")
            return
        wait_s = 60   # כמה זמן לחכות לחיבור במצב BROM
        q = ui_kit.Modal(self, "תקן דרייבר למכשיר המחובר", icon="info", wide=True)
        q.add_text("התוכנה תחפש מכשיר Android/MediaTek שמחובר בלי דרייבר, "
                   "ותצמיד לו את הדרייבר המתאים "
                   f"({ui_kit.ltr('ADB')} / {ui_kit.ltr('Fastboot')} / {ui_kit.ltr('BROM')}).")
        q.add(ui_kit.steps_list([
            "<b>תקן עכשיו</b> — למכשיר שכבר מחובר (ADB / Fastboot).",
            "<b>חכה לחיבור BROM</b> — במצב BROM המכשיר מופיע רק לשניות ספורות: "
            "לחץ, אשר את חלון ההרשאה, ואז חבר את המכשיר במצב BROM — התוכנה "
            f"מחכה לו עד {wait_s} שניות ומתקנת ברגע שהוא מופיע.",
        ]))
        q.add_text("תידרש הרשאת מנהל (UAC).", "hint")
        q.add_button("תקן עכשיו", "now", "btnPrimary", default=True)
        q.add_button(f"חכה לחיבור BROM ({wait_s} שניות)", "brom", "btnSoft")
        q.add_button("ביטול", "")
        clicked = q.run()
        if clicked not in ("now", "brom"):
            return
        wait = wait_s if clicked == "brom" else 0
        import tempfile
        report = Path(tempfile.gettempdir()) / "askateroov_fix_driver.txt"
        try:
            report.unlink()
        except OSError:
            pass
        if wait:
            self._say("info", f"תיקון דרייבר BROM: אשר את חלון ההרשאה, ואז חבר את המכשיר "
                              f"במצב BROM — ממתין עד {wait} שניות…")
            self.status_label.setText(f"⏳ ממתין לחיבור במצב BROM (עד {wait} שניות)…")
        else:
            self._say("info", "מתקן דרייבר למכשיר המחובר — אשר את חלון ההרשאה…")

        def work():
            args = (f"-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"{ps1}\" "
                    f"-ToolsDir \"{tools}\" -ReportPath \"{report}\" -WaitBromSeconds {wait}")
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
        info = [r for r in rows if r[0] == "INFO"]
        lines = []
        for _st, kind, text in ok:
            lines.append(f"✅ {kind}: הותקן — {text}")
        for _st, kind, text in err:
            lines.append(f"❌ {kind}: {text}" if kind else f"❌ {text}")
        for _st, kind, text in info:
            lines.append(f"ℹ️ {kind}: {text}" if kind else f"ℹ️ {text}")
        self.status_label.setText("מוכן")
        if not ok and not err and not info:
            lines.append("לא נמצא מכשיר Android מחובר שחסר לו דרייבר.\n"
                         "אם המכשיר לא מזוהה — ודא שהוא מחובר ובמצב הנכון (ADB / Fastboot / BROM).")
        for l in lines:
            self._say("success" if l.startswith("✅")
                      else "info" if l.startswith("ℹ️") else "warning", l)
        if err:
            kind, state = "err", "נכשל"
        elif ok:
            kind, state = "ok", "הדרייבר הותקן"
        else:
            kind, state = "info", (lines[0].splitlines()[0] if lines else "")
        self._toast_result(kind, f"תקן דרייבר למכשיר המחובר — {state}", "\n".join(lines),
                           "תקן דרייבר למכשיר המחובר")

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
            ui_kit.MessageBox.warning(
                self, "חסר",
                f"לא נמצאו קובצי {title} בתיקייה:\n"
                f"{d}\n\n"
                "הורד את הדרייבר (כפתור ההורדה שליד), חלץ אותו לתיקייה הזו ונסה שוב.")
            return
        what = (f"יותקנו {len(infs)} קובצי INF דרך pnputil" if infs
                else f"יופעל קובץ ההתקנה {setups[0].name}")
        if ui_kit.MessageBox.question(self, f"התקנת {title}",
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
                          "ואחר כך בדוק עם כפתור הבדיקה שליד")

    def _open_drivers_link(self):
        QDesktopServices.openUrl(QUrl(_DRIVERS_URL))

    # ------------------------------------------------------------ Scatter
    def _gen_scatter_full(self):
        if not self.gpt:
            ui_kit.MessageBox.warning(self, "אין GPT", "קודם טען GPT בלשונית mtkclient")
            return
        chip = self.chip_edit.text().strip()
        if is_placeholder_chip(chip):
            self._say("error", "אין שם מעבד — Scatter לא נוצר")
            ui_kit.MessageBox.warning(self, "חסר שם מעבד",
                                "שם המעבד (platform) ריק או אינו אמיתי.\n\n"
                                "קרא GPT מהמכשיר (המעבד יזוהה אוטומטית), או הזן דגם ידנית "
                                "למשל MT6580.")
            return
        out = config.SCATTER_DIR / scatter_filename(chip)
        if self.gpt.cpu and self.gpt.cpu.upper() != chip.upper():
            if ui_kit.MessageBox.question(
                    self, "אי-התאמה במעבד",
                    f"המכשיר דיווח על {self.gpt.cpu}, אבל בשדה כתוב {chip}.\n"
                    "ליצור בכל זאת עם השם שבשדה?", _YES | _NO, _NO) != _YES:
                return
        # שם מכשיר (אופציונלי): אם ימולא — הסקטאר יישמר בבנק בתיקייה נפרדת לפי המכשיר,
        # כך שסקטארים מאותו מעבד למכשירים שונים לא יתנגשו (בלי מספור אוטומטי).
        device = ""
        dev, ok = ui_kit.MessageBox.get_text(
            self, "שם המכשיר (אופציונלי)",
            "הזן שם מכשיר להפקת הסקטאר (למשל Redmi_9A):\n"
            "הסקטאר יישמר בבנק בתיקייה נפרדת לפי שם זה.\n\n"
            "אפשר להשאיר ריק או ללחוץ 'דלג' — אז יישמר לפי שם המעבד.")
        if ok and dev.strip():
            device = dev.strip()
        try:
            generate_scatter(self.gpt, out, chip_name=chip, block_size=self._block_size())
        except ValueError as e:
            ui_kit.MessageBox.warning(self, "חסר שם מעבד", str(e))
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
        text = f"Scatter נוצר: {path.name}" + (" — נמצאו בעיות תקינות" if problems else "")
        self._toast_result("warn" if problems else "ok", text, msg, "Scatter נוצר")

    # ------------------------------------------------------------ שאיבה
    def _read_checked(self):
        self._retry_action = self._read_checked
        if not self._require_flashdump_channel("שאיבה"):
            return
        if not self.gpt:
            # אין GPT — שאיבה לפי שם מחיצה ידני (קריאה בטוחה, בלי סיכון למכשיר)
            if ui_kit.MessageBox.question(
                    self, "שאיבה ללא GPT",
                    "לא נטען GPT.\n\nאפשר לשאוב מחיצה גם בלי GPT — רק צריך להקליד "
                    "את שם המחיצה במדויק (למשל boot).\n(קריאה בלבד — לא מסכנת את המכשיר.)\n\n"
                    "מומלץ לטעון GPT קודם כדי לבחור מרשימה. להמשיך בכל זאת?",
                    _YES | _NO, _NO) != _YES:
                return
            name, ok = ui_kit.MessageBox.get_text(
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
            ui_kit.MessageBox.warning(self, "לא סומנו מחיצות", "סמן מחיצה אחת או יותר בעמודת ✔")
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
            ui_kit.MessageBox.warning(self, "קובץ חסר", "בחר קובץ Image תקין")
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
        if ui_kit.MessageBox.warning(
                self, "צריבה ללא GPT",
                "לא נטען GPT.\n\n⚠️ בלי GPT אין אימות גודל ואין גיבוי אוטומטי — "
                "צריבת קובץ לא מתאים עלולה לפגוע במכשיר.\n\n"
                "מומלץ לטעון GPT קודם (לשונית mtkclient). להמשיך בכל זאת?",
                _YES | _NO, _NO) != _YES:
            return
        part_name, ok = ui_kit.MessageBox.get_text(
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
            return f"{battery}%"
        if (getattr(info, "mode", "") == "fastboot"
                and getattr(info, "voltage_mv", None) is not None):
            return f"{info.voltage_mv}mV"
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
                f"color: {theme.colors()['danger']}; font-weight: bold;" if low else "")
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
        return {"adb": "ADB", "fastboot": "Fastboot", "auto": "אוטומטי",
                "brom": "mtkclient\u200f (BROM)\u200f", "none": "לא מזוהה"}.get(ch, ch)

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
            ui_kit.MessageBox.information(
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
            if ui_kit.MessageBox.question(
                    self, f"{verb} בוטלאודר",
                    f"אתה במצב ADB, שאינו מאפשר {act} של הבוטלאודר.\n\n"
                    "להעביר את המכשיר למצב Fastboot ולהמשיך?\n"
                    f"המעבר עצמו אינו משפיע על המכשיר כלל — רק ה{act} עצמה משנה "
                    "(ומוחקת את כל הנתונים).",
                    _YES | _NO, _NO) == _YES:
                self._adb_boot_change(unlock)   # מאתחל ל-Fastboot, מבצע, ומעביר ערוץ ל-Fastboot
        else:
            ui_kit.MessageBox.information(
                self, "אין ערוץ תקשורת פעיל",
                "לא זוהה מכשיר. חבר מכשיר ובחר ערוץ תקשורת.")

    def _fastboot_lock_change(self, unlock: bool):
        """פתיחה/נעילה כשהמכשיר כבר במצב Fastboot."""
        from ..core import adb_boot
        from ..core.jobs import Job, Step
        if not config.find_fastboot_exe():
            ui_kit.MessageBox.warning(self, "חסר כלי", "fastboot.exe לא נמצא בתיקיית tools.")
            return
        verb = "פתיחת" if unlock else "נעילת"
        if unlock:
            warn = ("⚠️ אזהרה חמורה: פתיחת הבוטלאודר מוחקת את כל הנתונים במכשיר!\n\n"
                    "ודא שיש לך גיבוי. להמשיך?")
        else:
            warn = ("⚠️ נעילת הבוטלאודר מוחקת גם היא את הנתונים ברוב המכשירים.\n"
                    "אם מותקנת מערכת לא מקורית — נעילה עלולה למנוע מהמכשיר לעלות!\n\nלהמשיך?")
        if ui_kit.MessageBox.warning(self, f"{verb} בוטלאודר", warn, _YES | _NO, _NO) != _YES:
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
        if ui_kit.MessageBox.question(
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

    # ------------------------------------------------------------ לוגים
    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "ייצוא לוג", str(config.LOGS_DIR / "log.txt"),
                                              "Text (*.txt)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    # כל השורות — גם כשהתצוגה מסוננת כרגע (אזהרות / שגיאות)
                    f.write("\n".join(plain for _lvl, _html, plain in self._log_entries))
                self._say("success", f"לוג יוצא אל {path}")
                self._toast("ok", f"הלוג יוצא אל {Path(path).name}")
            except OSError as e:
                self._say("error", f"כתיבת לוג נכשלה: {e}")
                self._toast("err", f"כתיבת לוג נכשלה: {e}")

    def closeEvent(self, event):
        if job_manager.busy:
            if ui_kit.MessageBox.question(self, "פעולה פעילה",
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
