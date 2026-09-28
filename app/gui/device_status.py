# -*- coding: utf-8 -*-
"""
ווידג'ט סטטוס מכשיר לפינה העליונה: דגם / מעבד + אייקון סוללה עם אחוז.
מתעדכן חי לפי מצב החיבור (ADB / Fastboot / BROM).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class BatteryIcon(QWidget):
    """אייקון סוללה קטן שמתמלא לפי אחוז; אפור כשאין נתון."""

    def __init__(self):
        super().__init__()
        self.level: int | None = None
        self.low = False
        self.setFixedSize(46, 22)

    def set_level(self, level: int | None, low: bool = False):
        self.level = level
        self.low = bool(low)
        self.setToolTip("אין נתון סוללה" if level is None else f"סוללה {level}%")
        self.update()

    def _color(self) -> QColor:
        if self.low:
            return QColor("#f85149")   # אדום — סוללה נמוכה
        if self.level is None:
            return QColor("#8b949e")
        if self.level <= 15:
            return QColor("#f85149")   # אדום
        if self.level <= 35:
            return QColor("#d29922")   # כתום
        return QColor("#3fb950")       # ירוק

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        body = QRectF(1, 3, w - 8, h - 6)     # גוף הסוללה
        cap = QRectF(w - 6, h / 2 - 4, 4, 8)  # הראש הקטן
        border = QColor("#6e7681")
        p.setPen(QPen(border, 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(body, 3, 3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(border))
        p.drawRoundedRect(cap, 1, 1)
        # מילוי לפי אחוז
        if self.level is None and self.low:
            # אין אחוז אבל ידוע שהסוללה נמוכה (לפי מתח) — ממלאים באדום
            p.setBrush(QBrush(self._color()))
            p.drawRoundedRect(body.adjusted(2, 2, -2, -2), 2, 2)
        elif self.level is not None and self.level > 0:
            inner = body.adjusted(2, 2, -2, -2)
            fill_w = inner.width() * (self.level / 100.0)
            fill = QRectF(inner.x(), inner.y(), fill_w, inner.height())
            p.setBrush(QBrush(self._color()))
            p.drawRoundedRect(fill, 2, 2)
        # טקסט אחוז / ?
        p.setPen(QColor("#e6edf3") if (self.level is not None or self.low) else QColor("#8b949e"))
        f = p.font()
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        txt = ("!" if self.low else "?") if self.level is None else f"{self.level}%"
        p.drawText(body.translated(0, -2), Qt.AlignmentFlag.AlignCenter, txt)
        p.end()


class DeviceStatusWidget(QWidget):
    """דגם/מעבד + אייקון סוללה, לפינה העליונה של החלון.

    header_refresh: אות שנפלט אחרי עדכון מידע חדש — מאפשר לבעלים של הווידג'ט
    (החלון הראשי) לסנכרן נתונים משלימים בכותרת (למשל אחוז סוללה) גם מזרימות
    שלא מדווחות סוללה בעצמן.
    """

    header_refresh = Signal()

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(8)
        # הטקסט כשאין מכשיר — נקבע לפי ערוץ התקשורת ('אין ערוץ תקשורת פעיל' וכו')
        self._idle_text = "אין מכשיר מחובר"
        self._idle = True
        self.text = QLabel(self._idle_text)
        self.battery = BatteryIcon()
        lay.addWidget(self.text)
        lay.addWidget(self.battery)

    def set_idle_text(self, text: str):
        """קובע מה מוצג כשאין מכשיר; אם כרגע אין מכשיר — מתעדכן מיד."""
        self._idle_text = text or "אין מכשיר מחובר"
        if self._idle:
            self.text.setText(self._idle_text)

    def set_info(self, info):
        """info: DeviceInfo (מ-core.device_info)."""
        try:
            if info is None or getattr(info, "mode", "none") == "none":
                self._idle = True
                self.text.setText(self._idle_text)
                self.battery.set_level(None)
                self.battery.setVisible(False)
                self.setToolTip("")
                return
            self._idle = False
            parts = []
            if getattr(info, "model", ""):
                parts.append(info.model)
            if getattr(info, "cpu", ""):
                parts.append(info.cpu)
            parts.append(f"[{info.mode_label}]")
            # אם אין אחוז אך יש מתח סוללה (Fastboot) — מציגים אותו בטקסט
            if getattr(info, "battery", None) is None and getattr(info, "extra", ""):
                parts.append(info.extra)
            self.text.setText("  ·  ".join(parts))
            self.battery.setVisible(True)   # הווידג'ט חוזר גם אחרי "אין מכשיר"
            low = info.battery_too_low() if hasattr(info, "battery_too_low") else False
            self.battery.set_level(getattr(info, "battery", None), low=low)
            tip = info.mode_label
            if getattr(info, "extra", ""):
                tip += "  |  " + info.extra
            if getattr(info, "battery", None) is None:
                tip += "  |  אין נתון סוללה במצב זה"
            self.setToolTip(tip)
        finally:
            # בכל מקרה (כולל "אין מכשיר") — הבעלים מסנכרן את הסוללה בכותרת
            self.header_refresh.emit()
