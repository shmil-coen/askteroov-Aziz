# -*- coding: utf-8 -*-
"""
כרטיס מצב המכשיר (מעל הלשוניות): סמל מצב + כותרת ושורת משנה, וסוללה מצוירת.
מתעדכן חי לפי מצב החיבור (ADB / Fastboot / BROM). העיצוב לפי הדמו — צבעי הערכה
נלקחים מ-theme.py בכל ציור, כך שהחלפת ערכה מתעדכנת מיד.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme


class BatteryIcon(QWidget):
    """סוללה קטנה בסגנון הדמו: מסגרת דקה ומילוי לפי אחוז (בלי טקסט בפנים —
    המספר מוצג לידה). ירוק / כתום / אדום לפי רמת הטעינה; אדום מלא כשידוע רק
    שהסוללה נמוכה (לפי מתח ב-Fastboot)."""

    def __init__(self):
        super().__init__()
        self.level: int | None = None
        self.low = False
        self.setFixedSize(34, 14)

    def set_level(self, level: int | None, low: bool = False):
        self.level = level
        self.low = bool(low)
        self.setToolTip("אין נתון סוללה" if level is None else f"סוללה {level}%")
        self.update()

    def _color(self) -> QColor:
        c = theme.colors()
        if self.low:
            return QColor(c["danger"])
        if self.level is None:
            return QColor(c["muted"])
        if self.level <= 15:
            return QColor(c["danger"])
        if self.level <= 35:
            return QColor(c["warn"])
        return QColor(c["ok"])

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(0.75, 0.75, self.width() - 1.5, self.height() - 1.5)
        p.setPen(QPen(QColor(theme.colors()["muted"]), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(body, 4, 4)
        inner = body.adjusted(2.25, 2.25, -2.25, -2.25)
        if self.level is None and self.low:
            frac = 1.0
        elif self.level is not None:
            frac = max(0.0, min(1.0, self.level / 100.0))
        else:
            frac = 0.0
        if frac > 0:
            w = inner.width() * frac
            # מימין לשמאל (כמו בדמו): המילוי מתחיל מהקצה הימני
            fill = QRectF(inner.right() - w, inner.y(), w, inner.height())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(self._color()))
            p.drawRoundedRect(fill, 2, 2)
        p.end()


def _phone_pixmap(color: str, size: int = 22) -> QPixmap:
    """סמל טלפון בקו דק (כמו בדמו) — לעיגול המצב שבכרטיס."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    s = size / 24.0
    p.drawRoundedRect(QRectF(6 * s, 2 * s, 12 * s, 20 * s), 2.5 * s, 2.5 * s)
    p.drawLine(int(11 * s), int(18 * s), int(13 * s), int(18 * s))
    p.end()
    return pm


class DeviceStatusWidget(QWidget):
    """סמל מצב + כותרת ושורת משנה (החלק הימני של כרטיס המכשיר).

    הסוללה המצוירת (self.battery) שייכת לווידג'ט הזה, אבל החלון הראשי ממקם אותה
    בנתון "סוללה" שבכרטיס.

    header_refresh: אות שנפלט אחרי עדכון מידע חדש — מאפשר לבעלים של הווידג'ט
    (החלון הראשי) לסנכרן נתונים משלימים בכרטיס (למשל אחוז סוללה) גם מזרימות
    שלא מדווחות סוללה בעצמן.
    """

    header_refresh = Signal()

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.icon = QLabel()
        self.icon.setObjectName("devIcon")
        self.icon.setFixedSize(44, 44)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        # הטקסט כשאין מכשיר — נקבע לפי ערוץ התקשורת ('אין ערוץ תקשורת פעיל' וכו')
        self._idle_text = "אין מכשיר מחובר"
        self._idle = True
        self.text = QLabel()
        self.text.setObjectName("devTitle")
        self.sub = QLabel()
        self.sub.setObjectName("devSub")
        col.addWidget(self.text)
        col.addWidget(self.sub)
        lay.addLayout(col, 1)
        self.battery = BatteryIcon()      # ממוקם בכרטיס על ידי החלון הראשי
        self.battery.setVisible(False)
        self._on = False
        self._show_idle()

    # ------------------------------------------------------------ עזרים
    def _set_state(self, on: bool):
        """עיגול המצב: ירוק כשמכשיר מחובר, אפור כשלא."""
        self._on = on
        c = theme.colors()
        self.icon.setPixmap(_phone_pixmap(c["ok"] if on else c["muted"]))
        self.icon.setProperty("state", "on" if on else "off")
        self.icon.style().unpolish(self.icon)
        self.icon.style().polish(self.icon)

    def refresh_theme(self):
        """צביעה מחדש אחרי החלפת ערכה."""
        self._set_state(self._on)
        self.battery.update()

    def _show_idle(self):
        # "אין ערוץ תקשורת פעיל — בחר ערוץ" → כותרת + שורת משנה (אותו טקסט, בשתי שורות)
        title, _, sub = self._idle_text.partition(" — ")
        self.text.setText(title)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        self._set_state(False)

    # ------------------------------------------------------------ API
    def set_idle_text(self, text: str):
        """קובע מה מוצג כשאין מכשיר; אם כרגע אין מכשיר — מתעדכן מיד."""
        self._idle_text = text or "אין מכשיר מחובר"
        if self._idle:
            self._show_idle()

    def set_info(self, info):
        """info: DeviceInfo (מ-core.device_info)."""
        try:
            if info is None or getattr(info, "mode", "none") == "none":
                self._idle = True
                self._show_idle()
                self.battery.set_level(None)
                self.battery.setVisible(False)
                self.setToolTip("")
                return
            self._idle = False
            self.text.setText(getattr(info, "model", "") or "מכשיר מחובר")
            # מתח הסוללה (Fastboot) מוצג בנתון "סוללה" שבכרטיס — לא כאן (וגם בבועת העזרה)
            self.sub.setText(f"ערוץ {info.mode_label}")
            self.sub.setVisible(True)
            self._set_state(True)
            low = info.battery_too_low() if hasattr(info, "battery_too_low") else False
            level = getattr(info, "battery", None)
            self.battery.set_level(level, low=low)
            # הסוללה המצוירת — רק כשיש אחוז (או כשידוע שהיא נמוכה); אחרת רק הטקסט
            self.battery.setVisible(level is not None or low)
            tip = info.mode_label
            if getattr(info, "extra", ""):
                tip += "  |  " + info.extra
            if level is None:
                tip += "  |  אין נתון סוללה במצב זה"
            self.setToolTip(tip)
        finally:
            # בכל מקרה (כולל "אין מכשיר") — הבעלים מסנכרן את הסוללה בכרטיס
            self.header_refresh.emit()
