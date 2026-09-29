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

הצבעים מגיעים מ-theme.py: רוב הצביעה דרך QSS לפי objectName, והסמלים המצוירים
מתעדכנים בהחלפת ערכה דרך refresh_all().
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
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
               extra: Iterable[QWidget] = ()) -> QWidget:
    """כותרת לשונית (כמו בדמו): כותרת + הסבר מימין; כפתורי עזר ותגית ערוץ משמאל."""
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
    if chip_channel:
        chip = QLabel(f"פועל דרך <b>{chip_channel}</b>")
        chip.setObjectName("chanChip")
        chip.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
    return w


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
        self.desc.setVisible(bool(desc))
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
