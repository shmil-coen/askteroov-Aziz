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
