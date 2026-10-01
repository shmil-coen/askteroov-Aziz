# -*- coding: utf-8 -*-
"""
רכיבי הממשק המשותפים לכל הלשוניות — לפי הדמו המאושר (הדמיית_ממשק_אחיד):

  tab_header   — כותרת לשונית: כותרת גדולה + משפט הסבר + תגית "פועל דרך X".
  Card         — כרטיס: סמל בריבוע צבעוני · כותרת · תיאור · תגית · תוכן · שורת פעולות.
  Pill         — תגית קטנה ("קריאה בלבד" / "כתיבה" / "מוחק נתונים" ...).
  EmptyState   — מסגרת מקווקוות עם הסבר, לפני שיש נתונים.
  KeyValueList — שורות "שם ← ערך" (למשל פרטי המכשיר).
  InfoPanel    — KeyValueList או הודעה, לפי הטקסט שמתקבל (setPlainText).
  menu_button  — כפתור עם תפריט נפתח ("התקנה והורדה ▾").
  svg_icon     — סמלים מצוירים (בדיוק כמו בדמו), בצבע שנבחר.
  ltr / breakable_path — כיווניות ושבירת שורות לטקסט באנגלית בתוך עברית.
  Toast / ToastHost — הודעות קצרות בפינה השמאלית התחתונה (הצלחה / כשלון / מידע).
  Modal        — חלון כמו בדמו: החלון הראשי מוחשך וכרטיס באמצע (אישור, כשלון, עצירה).

הצבעים מגיעים מ-theme.py: רוב הצביעה דרך QSS לפי objectName, והסמלים המצוירים
מתעדכנים בהחלפת ערכה דרך refresh_all().
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from PySide6.QtCore import QByteArray, QElapsedTimer, QEvent, QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme

# ---------------------------------------------------------------------- סמלים
# גוף ה-SVG של כל סמל (רשת 24×24, קו בלבד) — אותם סמלים כמו בדמו.
_ICONS = {
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v4h1"/>',
    "apps": ('<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/>'
             '<rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>'),
    "download": '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "bolt": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    "admin": '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0M17 11l2 2 4-4"/>',
    "wrench": ('<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4'
               'l-2.5 2.5-2.4-.6-.6-2.4z"/>'),
    "up": '<path d="M12 19V5M5 12l7-7 7 7"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16zM13 7l4 4"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "shield": '<path d="M12 2 4 6v6c0 5 3.4 8.7 8 10 4.6-1.3 8-5 8-10V6z"/>',
    "check": '<path d="M5 12.5 10 17 19 7.5"/>',
    "cross": '<path d="M6 6l12 12M18 6 6 18"/>',
    "dots": '<path d="M6 12h.01M12 12h.01M18 12h.01"/>',
    "terminal": '<path d="M4 17 10 11 4 5M12 19h8"/>',
    "plug": '<path d="M12 22v-5M9 8V2M15 8V2M18 8H6v4a6 6 0 0 0 12 0z"/>',
    "list": '<path d="M3 5h18M3 12h18M3 19h18M8 5v14"/>',
    "doc_plus": ('<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6'
                 'M12 12v6M9 15h6"/>'),
    "doc_check": '<path d="M9 11l3 3 8-8"/><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9"/>',
    "database": ('<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5'
                 'M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>'),
    "reboot": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5"/>',
    "unlock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.8-1.3"/>',
    "spark": '<path d="M12 2v6M12 22v-6M4.9 4.9l4.2 4.2M14.9 14.9l4.2 4.2M2 12h6M22 12h-6"/>',
    "scroll": '<path d="M8 3h9a2 2 0 0 1 2 2v12M8 3a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2M9 8h6M9 12h6"/>',
    "alert": '<path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    "back": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "chip": ('<rect x="5" y="5" width="14" height="14" rx="3"/>'
             '<path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>'),
    "phone": '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    "archive": '<rect x="3" y="4" width="18" height="5" rx="1.5"/><path d="M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9M10 13h4"/>',
}
_FILLED = {"folder_fill": "folder"}   # גרסה מלאה (ממולאת) של סמל


def svg_pixmap(kind: str, color: str, size: int = 18, stroke: float = 2.0) -> QPixmap:
    """מצייר סמל מהרשימה בצבע ובגודל שנבחרו (חד גם במסכים עם הגדלת תצוגה)."""
    filled = kind in _FILLED
    body = _ICONS[_FILLED.get(kind, kind)]
    if filled:
        head = f'fill="{color}" stroke="none"'
    else:
        head = (f'fill="none" stroke="{color}" stroke-width="{stroke}" '
                f'stroke-linecap="round" stroke-linejoin="round"')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {head}>{body}</svg>'
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app is not None else 1.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(dpr)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def svg_icon(kind: str, color: str, size: int = 18, stroke: float = 2.0) -> QIcon:
    return QIcon(svg_pixmap(kind, color, size, stroke))


# ---------------------------------------------------------------------- כיווניות טקסט
def ltr(text: str) -> str:
    """קטע באנגלית עם סוגריים (למשל "mtkclient (BROM)") בתוך משפט בעברית — עטוף בבידוד
    כיווניות משמאל לימין, כדי שהסוגריים לא יתהפכו. טקסט שיש בו עברית חוזר כמו שהוא."""
    if not text or any("\u0590" <= ch <= "\u05ff" for ch in text):
        return text
    return "\u2066" + text + "\u2069"


_RLM = "\u200f"   # סימן כיוון מימין לשמאל (בלתי נראה)


def rtl(text: str) -> str:
    """פסקה מימין לשמאל גם כשהטקסט מתחיל באנגלית (למשל "Fastboot: זיהוי מכשיר")."""
    return _RLM + text if text else text


_ZWSP = "\u200b"   # רווח ברוחב אפס — נקודת שבירה בלתי נראית


def breakable_path(path: str) -> str:
    """נתיב ארוך שאפשר לשבור בכל תיקייה (רווח ברוחב אפס אחרי כל מפריד) — כדי שכרטיס
    צר לא יימתח בגלל נתיב בלי רווחים. להצגה בלבד."""
    for sep in ("\\", "/"):
        path = path.replace(sep, sep + _ZWSP)
    return path


# ---------------------------------------------------------------------- תגית
class Pill(QLabel):
    """תגית קטנה: kind = ok (ירוק) · warn (כתום) · danger (אדום) · info (כחול) · neutral (אפור)."""

    def __init__(self, text: str, kind: str = "ok", tooltip: str = ""):
        super().__init__(text)
        self.setObjectName("pill")
        self.set_kind(kind)
        if tooltip:
            self.setToolTip(tooltip)

    def set_kind(self, kind: str):
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)

    def set(self, text: str, kind: str):
        self.setText(text)
        self.set_kind(kind)


# ---------------------------------------------------------------------- כותרת לשונית
def tab_header(title: str, desc: str, chip_channel: str = "",
               extra: Iterable[QWidget] = (), chip_html: str = "") -> QWidget:
    """כותרת לשונית (כמו בדמו): כותרת + הסבר מימין; כפתורי עזר ותגית ערוץ משמאל.

    chip_channel — "פועל דרך <b>X</b>"; chip_html — טקסט אחר לתגית (למשל "פעולה במחשב
    בלבד"). התגית זמינה ב-widget.chip, לעדכון בזמן ריצה."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(4, 2, 4, 2)
    lay.setSpacing(16)
    col = QVBoxLayout()
    col.setSpacing(4)
    t = QLabel(title)
    t.setObjectName("tabTitle")
    col.addWidget(t)
    if desc:
        d = QLabel(desc)
        d.setObjectName("tabDesc")
        d.setWordWrap(True)
        col.addWidget(d)
    lay.addLayout(col, 1)
    for x in extra:
        lay.addWidget(x, 0, Qt.AlignmentFlag.AlignVCenter)
    w.chip = None
    if chip_channel or chip_html:
        chip = QLabel(chip_html or f"פועל דרך <b>{ltr(chip_channel)}</b>")
        chip.setObjectName("chanChip")
        chip.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        w.chip = chip
    return w


# ---------------------------------------------------------------------- צעדים ממוספרים
def steps_list(items: Iterable[str]) -> QWidget:
    """צעדים ממוספרים (1 · 2 · 3) בעיגולים קטנים — כמו בדמו."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(9)
    for i, text in enumerate(items, 1):
        row = QHBoxLayout()
        row.setSpacing(10)
        num = QLabel(str(i))
        num.setObjectName("stepNum")
        num.setFixedSize(24, 24)
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(num, 0, Qt.AlignmentFlag.AlignTop)
        lbl = QLabel(text)
        lbl.setObjectName("stepText")
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(lbl, 1)
        v.addLayout(row)
    return w


class EmptyBox(QFrame):
    """מצב ריק עם כפתור (כמו בדמו): מסגרת מקווקוות, הסבר, וכפתור לצעד הבא."""

    def __init__(self, text: str, button: Optional[QPushButton] = None, min_height: int = 0):
        super().__init__()
        self.setObjectName("emptyBox")
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 28, 20, 28)
        v.setSpacing(12)
        v.addStretch(1)
        self.label = QLabel(text)
        self.label.setObjectName("emptyText")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.label)
        if button is not None:
            v.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addStretch(1)
        if min_height:
            self.setMinimumHeight(min_height)


# ---------------------------------------------------------------------- תיבת מצב
class StatusBox(QFrame):
    """תיבת מצב (כמו "הכל מוכן לעבודה" בדמו): עיגול סימון + כותרת + שורת משנה.
    state = ok (ירוק) · err (אדום) · idle (אפור)."""

    def __init__(self, title: str = "", sub: str = "", state: str = "idle"):
        super().__init__()
        self.setObjectName("statusBox")
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(14)
        self.mark = QLabel()
        self.mark.setObjectName("statusMark")
        self.mark.setFixedSize(34, 34)
        self.mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self.mark)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("statusTitle")
        self.title.setWordWrap(True)
        self.sub = QLabel(sub)
        self.sub.setObjectName("statusSub")
        self.sub.setWordWrap(True)
        col.addWidget(self.title)
        col.addWidget(self.sub)
        h.addLayout(col, 1)
        self.set(title, sub, state)

    def set(self, title: str, sub: str = "", state: str = "idle"):
        self.title.setText(title)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        self._state = state
        for w in (self, self.mark):
            w.setProperty("state", state)
            w.style().unpolish(w)
            w.style().polish(w)
        self.refresh_theme()

    def refresh_theme(self):
        c = theme.colors()
        kind = {"ok": "check", "err": "cross"}.get(self._state, "dots")
        self.mark.setPixmap(svg_pixmap(kind, c["bg"] if self._state in ("ok", "err") else c["muted"], 18, 2.6))


# ---------------------------------------------------------------------- רשימת בדיקה
class Checklist(QWidget):
    """רשימת בדיקה חיה (כמו "לפני שצורבים" בדמו): ✓ ירוק כשמתקיים, • אפור כשלא."""

    def __init__(self, items: Iterable[str]):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        self._marks: list[QLabel] = []
        for text in items:
            row = QHBoxLayout()
            row.setSpacing(10)
            mk = QLabel("•")
            mk.setObjectName("checkMark")
            mk.setFixedSize(22, 22)
            mk.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(mk)
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            row.addWidget(lbl, 1)
            v.addLayout(row)
            self._marks.append(mk)

    def set_states(self, states: Iterable[bool]):
        for mk, on in zip(self._marks, states):
            mk.setText("✓" if on else "•")
            mk.setProperty("on", "true" if on else "false")
            mk.style().unpolish(mk)
            mk.style().polish(mk)


# ---------------------------------------------------------------------- כרטיס
class Card(QFrame):
    """כרטיס (כמו בדמו): ראש — סמל · כותרת · תיאור · תגית; אחריו התוכן (body);
    ובתחתית — שורת פעולות (add_action). הכפתורים נוספים מימין לשמאל."""

    def __init__(self, title: str, desc: str = "", icon: str = "info",
                 pill: Optional[Pill] = None, danger: bool = False):
        super().__init__()
        self.setObjectName("card")
        self._icon_kind = icon
        self._danger = danger
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.icon = QLabel()
        self.icon.setObjectName("cardIcon")
        self.icon.setProperty("danger", "true" if danger else "false")
        self.icon.setFixedSize(36, 36)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        col.addWidget(self.title)
        self.desc = QLabel(desc)
        self.desc.setObjectName("cardDesc")
        self.desc.setWordWrap(True)
        if not desc:
            # הסתרה בלבד — "הצגה" של התווית לפני שהיא בתוך הכרטיס פותחת אותה לרגע
            # כחלון נפרד (ריצוד בשורת המשימות ובראש המסך בזמן פתיחת התוכנה)
            self.desc.hide()
        col.addWidget(self.desc)
        head.addLayout(col, 1)
        if pill is not None:
            head.addWidget(pill, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        outer.addLayout(self.body)
        outer.addStretch(1)   # שורת הפעולות תמיד בתחתית הכרטיס (כמו בדמו)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(10)
        self.actions.addStretch(1)
        outer.addLayout(self.actions)
        self.refresh_theme()

    def add(self, widget: QWidget, stretch: int = 0):
        self.body.addWidget(widget, stretch)

    def add_layout(self, layout):
        self.body.addLayout(layout)

    def expand_body(self):
        """התוכן ממלא את כל גובה הכרטיס (במקום רווח לפני שורת הפעולות) — לטבלה גדולה."""
        lay = self.layout()
        lay.setStretch(2, 0)                 # הרווח המתרחב שלפני שורת הפעולות
        lay.setStretchFactor(self.body, 1)

    def add_action(self, widget: QWidget, stretch: int = 0):
        """מוסיף לשורת הפעולות (לפני הרווח המתרחב — כך הכפתורים מתחילים מימין).
        stretch > 0 — הרכיב ממלא את השטח הפנוי (למשל שורת "נבחר: …"), והפעולות
        שאחריו נדחפות לקצה השמאלי."""
        self.actions.insertWidget(self.actions.count() - 1, widget, stretch)
        if stretch:
            self.actions.setStretch(self.actions.count() - 1, 0)

    def refresh_theme(self):
        c = theme.colors()
        self.icon.setPixmap(svg_pixmap(self._icon_kind, c["danger"] if self._danger else c["accent"], 18))


# ---------------------------------------------------------------------- מצב ריק
class EmptyState(QLabel):
    """מסגרת מקווקוות עם הסבר — מוצגת לפני שיש נתונים (כמו בדמו)."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setObjectName("emptyState")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


# ---------------------------------------------------------------------- שורות שם ← ערך
class KeyValueList(QFrame):
    """שורות "שם ← ערך" במסגרת מעוגלת עם קווים דקים ביניהן (כמו בדמו)."""

    def __init__(self, key_width: int = 130):
        super().__init__()
        self.setObjectName("kvList")
        self._key_width = key_width
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)

    def set_rows(self, rows: list[tuple[str, str]]):
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for i, (k, v) in enumerate(rows):
            if i:
                sep = QFrame()
                sep.setObjectName("kvSep")
                sep.setFixedHeight(1)
                self._lay.addWidget(sep)
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(16, 10, 16, 10)
            h.setSpacing(12)
            kl = QLabel(k)
            kl.setObjectName("kvKey")
            kl.setFixedWidth(self._key_width)
            kl.setWordWrap(True)
            vl = QLabel(v)
            vl.setObjectName("kvVal")
            vl.setWordWrap(True)
            vl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            h.addWidget(kl)
            h.addWidget(vl, 1)
            self._lay.addWidget(row)


class InfoPanel(QStackedWidget):
    """מציג טקסט "שם: ערך" כשורות מסודרות, וכל טקסט אחר (הודעה/שגיאה) כמצב ריק.

    תואם ל-QTextEdit בנקודה אחת — setPlainText(text) — כך שהקוד שמעדכן את
    התצוגה לא משתנה."""

    def __init__(self, empty_text: str):
        super().__init__()
        self._empty = EmptyState(empty_text)
        self._list = KeyValueList()
        self.addWidget(self._empty)
        self.addWidget(self._list)
        self.setCurrentWidget(self._empty)

    def setPlainText(self, text: str):
        lines = [ln for ln in (text or "").splitlines() if ln.strip()]
        rows = []
        for ln in lines:
            k, sep, v = ln.partition(": ")
            if not sep or not k.strip():
                rows = []
                break
            rows.append((k.strip(), v.strip()))
        if rows:
            self._list.set_rows(rows)
            self.setCurrentWidget(self._list)
        else:
            self._empty.setText(text or "")
            self.setCurrentWidget(self._empty)


# ---------------------------------------------------------------------- כפתור עם תפריט
def menu_button(text: str, items: list[Optional[tuple[str, Callable[[], None]]]],
                parent: Optional[QWidget] = None) -> QPushButton:
    """כפתור שקוף (ghost) שפותח תפריט; None ברשימה = קו מפריד."""
    b = QPushButton(f"{text} ▾", parent)
    b.setObjectName("btnGhost")
    m = QMenu(b)
    for it in items:
        if it is None:
            m.addSeparator()
        else:
            label, slot = it
            m.addAction(label).triggered.connect(lambda _=False, s=slot: s())
    b.setMenu(m)
    return b


def icon_button(kind: str, tooltip: str) -> QPushButton:
    """כפתור סמל בלבד (למשל "למעלה" / "רענן" בסייר)."""
    b = QPushButton()
    b.setObjectName("iconBtn")
    b.setToolTip(tooltip)
    b.setAccessibleName(tooltip)
    b.setProperty("iconKind", kind)
    b.setIcon(svg_icon(kind, theme.colors()["text"], 18))
    return b


def refresh_all(root: QWidget):
    """צביעה מחדש של כל הסמלים המצוירים אחרי החלפת ערכה."""
    c = theme.colors()
    for w in root.findChildren(QWidget):
        if isinstance(w, Card):
            w.refresh_theme()
        elif isinstance(w, QPushButton) and w.objectName() == "iconBtn" and w.property("iconKind"):
            w.setIcon(svg_icon(w.property("iconKind"), c["text"], 18))
        elif isinstance(w, QLabel) and w.property("helpDot"):
            w.setPixmap(svg_pixmap("info", c["muted"], 18))
        elif isinstance(w, StatusBox):
            w.refresh_theme()


# ---------------------------------------------------------------------- הודעות בצד
class Toast(QFrame):
    """הודעה קצרה בפינה (כמו בדמו): נקודה צבעונית · טקסט · כפתורי פעולה · ✕.

    kind = ok (הצלחה) · err (כשלון) · warn (אזהרה) · info (מידע). נעלמת לבד אחרי
    duration מילישניות; כשהעכבר מעליה — הספירה נעצרת עד שהוא יוצא."""

    closed = Signal(object)

    def __init__(self, parent: QWidget, kind: str, text: str,
                 actions: Iterable[tuple[str, Callable[[], None]]] = (),
                 duration: int = 4000, closable: bool = False):
        super().__init__(parent)
        self.setObjectName("toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 14, 16, 14)
        lay.setSpacing(14)
        dot = QLabel()
        dot.setObjectName("toastDot")
        dot.setProperty("kind", kind)
        dot.setFixedSize(12, 12)
        lay.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.label = QLabel(rtl(text))
        self.label.setObjectName("toastText")
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        lay.addWidget(self.label, 1)
        for label, slot in actions:
            b = QPushButton(label)
            b.setObjectName("toastBtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=slot: self._act(s))
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        if closable:
            x = QPushButton("✕")
            x.setObjectName("toastClose")
            x.setToolTip("סגור")
            x.setCursor(Qt.CursorShape.PointingHandCursor)
            x.clicked.connect(self.dismiss)
            lay.addWidget(x, 0, Qt.AlignmentFlag.AlignVCenter)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 110))
        self.setGraphicsEffect(shadow)
        self._remaining = duration
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._done = False

    def natural_width(self) -> int:
        """הרוחב שבו כל הטקסט נכנס בשורה אחת (ToastHost מגביל ל-380–540, כמו בדמו)."""
        others = self.layout().sizeHint().width() - self.label.sizeHint().width()
        return others + self.label.fontMetrics().horizontalAdvance(self.label.text()) + 4

    def start(self):
        self._clock.start()
        self._timer.start(self._remaining)

    def enterEvent(self, event):
        if self._timer.isActive():   # העכבר מעל ההודעה — עוצרים את הספירה
            self._remaining = max(800, self._remaining - self._clock.elapsed())
            self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._done and not self._timer.isActive():
            self.start()
        super().leaveEvent(event)

    def _act(self, slot: Callable[[], None]):
        """קודם סוגרים את ההודעה, ורק אחר כך מפעילים (הפעולה עלולה לפתוח חלון)."""
        self.dismiss()
        QTimer.singleShot(0, slot)

    def dismiss(self):
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self.hide()
        self.closed.emit(self)
        self.deleteLater()


class ToastHost(QObject):
    """ההודעות בפינה השמאלית התחתונה של החלון, מעל שורת המצב (כמו בדמו). החדשה
    למטה, והקודמות עולות מעליה. כשלון נשאר פי 2 מהצלחה, ויש בו ✕ לסגירה."""

    DURATION = {"ok": 4000, "info": 4000, "warn": 6000, "err": 8000}

    def __init__(self, window: QWidget, bottom: int = 84, left: int = 24, max_count: int = 4):
        super().__init__(window)
        self._win = window
        self._bottom = bottom
        self._left = left
        self._max = max_count
        self._toasts: list[Toast] = []
        window.installEventFilter(self)

    def show(self, kind: str, text: str,
             actions: Iterable[tuple[str, Callable[[], None]]] = (),
             closable: Optional[bool] = None) -> Toast:
        if closable is None:
            closable = kind == "err"
        t = Toast(self._win, kind, text, actions, self.DURATION.get(kind, 4000), closable)
        t.closed.connect(self._on_closed)
        self._toasts.append(t)
        while len(self._toasts) > self._max:
            self._toasts[0].dismiss()
        t.show()
        self._relayout()
        t.start()
        return t

    def _on_closed(self, t: Toast):
        if t in self._toasts:
            self._toasts.remove(t)
        self._relayout()

    def _relayout(self):
        y = self._win.height() - self._bottom
        for t in reversed(self._toasts):   # החדשה ביותר — למטה
            w = max(380, min(540, t.natural_width()))
            h = max(60, t.heightForWidth(w) if t.hasHeightForWidth() else t.sizeHint().height())
            y -= h
            t.setGeometry(self._left, y, w, h)
            t.raise_()
            y -= 10

    def eventFilter(self, obj, event):
        if obj is self._win and event.type() == QEvent.Type.Resize:
            self._relayout()
        return False


# ---------------------------------------------------------------------- חלון (כמו בדמו)
class Modal(QDialog):
    """חלון כמו בדמו: החלון הראשי מוחשך, ובאמצע כרטיס — סמל · כותרת · שורת הפעולה ·
    תוכן · כפתורים. run() מחזיר את המפתח של הכפתור שנלחץ ("" = סגירה / Esc).

    icon: "cross" (כשלון) · "alert" (אזהרה) · "check" (הצלחה) · "" (בלי סמל)."""

    def __init__(self, parent: QWidget, title: str, op_html: str = "", icon: str = "",
                 wide: bool = False):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self._key = ""
        self._default: Optional[QPushButton] = None
        self._focus: Optional[QWidget] = None   # שדה שיקבל את הפוקוס בפתיחה (למשל שדה קלט)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.card = QFrame()
        self.card.setObjectName("modal")
        self.card.setFixedWidth(620 if wide else 540)
        row.addWidget(self.card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        v = QVBoxLayout(self.card)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(16)
        head = QHBoxLayout()
        head.setSpacing(12)
        if icon:
            c = theme.colors()
            ic = QLabel()
            ic.setObjectName("modalIcon")
            ic.setProperty("kind", icon)
            ic.setFixedSize(40, 40)
            ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ic.setPixmap(svg_pixmap(icon, c["ok"] if icon == "check" else c["danger"], 20, 2.4))
            head.addWidget(ic)
        t = QLabel(rtl(title))
        t.setObjectName("modalTitle")
        t.setWordWrap(True)
        head.addWidget(t, 1)
        v.addLayout(head)
        if op_html:
            op = QLabel(rtl(op_html))
            op.setObjectName("modalOp")
            op.setTextFormat(Qt.TextFormat.RichText)
            op.setWordWrap(True)
            v.addWidget(op)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        v.addLayout(self.body)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(10)
        self.actions.addStretch(1)
        v.addLayout(self.actions)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.card.setGraphicsEffect(shadow)

    def add(self, widget: QWidget, stretch: int = 0):
        self.body.addWidget(widget, stretch)

    def add_text(self, html: str, name: str = "modalText") -> QLabel:
        """שורת טקסט בגוף החלון. name: modalText (רגיל) · hint (אפור) · reason (תיבה
        אדומה) · okNote (תיבה ירוקה) · noticeInfo / noticeDanger."""
        lbl = QLabel(rtl(html))
        lbl.setObjectName(name)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)
        return lbl

    def add_button(self, text: str, key: str, style: str = "", default: bool = False) -> QPushButton:
        """הכפתורים נוספים מימין לשמאל, מהקרוב לתוכן: קודם הפעולה ("אשר והרץ"),
        ואחריה "ביטול" — כמו בדמו."""
        b = QPushButton(text)
        if style:
            b.setObjectName(style)
        b.setAutoDefault(False)
        b.clicked.connect(lambda _=False, k=key: self._finish(k))
        self.actions.addWidget(b)
        if default:
            b.setDefault(True)
            self._default = b
        return b

    def _finish(self, key: str):
        self._key = key
        self.accept()

    def run(self) -> str:
        """מציג את החלון מעל כל החלון הראשי ומחכה לבחירה; מחזיר את מפתח הכפתור."""
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(p.window().geometry())   # השכבה הכהה מכסה את כל החלון הראשי
        self.exec()
        return self._key

    def focus_on(self, widget: QWidget):
        """השדה שיקבל את הפוקוס כשהחלון נפתח (במקום כפתור ברירת המחדל)."""
        self._focus = widget

    def showEvent(self, event):
        super().showEvent(event)
        target = self._focus or self._default
        if target is not None:
            QTimer.singleShot(0, target.setFocus)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(4, 6, 10, 158))   # הרקע המוחשך — כמו בדמו
        p.end()

    def mousePressEvent(self, event):
        # לחיצה על הרקע הכהה (מחוץ לכרטיס) = סגירה, כמו בדמו ("" — כמו ביטול)
        if not self.card.geometry().contains(event.position().toPoint()):
            self.reject()
            return
        super().mousePressEvent(event)


def commands_box(rows: Iterable[tuple[str, str]]) -> QFrame:
    """תיבת הפקודות (כמו בדמו): לכל שלב — השם בעברית, ומתחתיו הפקודה בכתב קבוע
    (משמאל לימין, ונשברת בכל תיקייה כדי לא לחרוג מהחלון)."""
    box = QFrame()
    box.setObjectName("cmds")
    v = QVBoxLayout(box)
    v.setContentsMargins(14, 12, 14, 12)
    v.setSpacing(3)
    for i, (step, cmd) in enumerate(rows, 1):
        if i > 1:
            v.addSpacing(8)
        s = QLabel(rtl(f"{i}. {step}"))
        s.setObjectName("cmdStep")
        s.setTextFormat(Qt.TextFormat.PlainText)
        s.setWordWrap(True)
        v.addWidget(s)
        c = QLabel(breakable_path(cmd))
        c.setObjectName("cmdText")
        c.setTextFormat(Qt.TextFormat.PlainText)
        c.setWordWrap(True)
        c.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        c.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)
        c.setToolTip(cmd)
        v.addWidget(c)
    return box


def mono_box(lines: Iterable[str]) -> QFrame:
    """תיבה כהה בכתב קבוע (למשל "פרטים טכניים" בחלון הכשלון)."""
    box = QFrame()
    box.setObjectName("cmds")
    v = QVBoxLayout(box)
    v.setContentsMargins(14, 12, 14, 12)
    lbl = QLabel(breakable_path("\n".join(lines)))
    lbl.setObjectName("cmdText")
    lbl.setTextFormat(Qt.TextFormat.PlainText)   # פלט כמו "< waiting for any device >" — כמו שהוא
    lbl.setWordWrap(True)
    lbl.setLayoutDirection(Qt.LayoutDirection.LeftToRight)   # כמו בדמו: משמאל לימין, מיושר לשמאל
    lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)
    v.addWidget(lbl)
    return box


class Swatch(QWidget):
    """דוגמת צבעים בפסים (לכרטיס בחירת ערכת צבע) — הצבע הראשון מימין, כמו בדמו."""

    def __init__(self, colors: Iterable[str], height: int = 38):
        super().__init__()
        self._colors = list(colors)
        self.setFixedHeight(height)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        p.setClipPath(path)
        n = max(1, len(self._colors))
        w = self.width() / n
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        for i, color in enumerate(self._colors):
            x = self.width() - (i + 1) * w if rtl else i * w
            p.fillRect(QRectF(x, 0, w + 1, self.height()), QColor(color))
        p.end()


class ThemeCard(QFrame):
    """כרטיס בחירת ערכת צבע (כמו בדמו): דוגמת צבעים + שם; הנבחר — מסגרת בצבע ההדגשה."""

    clicked = Signal()

    def __init__(self, name: str, colors: Iterable[str], selected: bool = False):
        super().__init__()
        self.setObjectName("themeCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)
        v.addWidget(Swatch(colors))
        self.name = QLabel(name)
        self.name.setObjectName("themeName")
        v.addWidget(self.name)
        self.set_selected(selected)

    def set_selected(self, on: bool):
        for w in (self, self.name):
            w.setProperty("selected", "true" if on else "false")
            w.style().unpolish(w)
            w.style().polish(w)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def collapsible(title: str, content: QWidget) -> QWidget:
    """כותרת שנפתחת בלחיצה (כמו "הצג פרטים טכניים" בדמו): ▸ סגור · ▾ פתוח."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(8)
    b = QPushButton(f"▸ {title}")
    b.setObjectName("linkBtn")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    v.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)   # בממשק מימין לשמאל — בצד ימין
    content.hide()
    v.addWidget(content)

    def toggle():
        show = not content.isVisible()
        content.setVisible(show)
        b.setText(f"{'▾' if show else '▸'} {title}")

    b.clicked.connect(toggle)
    return w
