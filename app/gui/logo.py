# -*- coding: utf-8 -*-
"""
לוגו התוכנה "הסקטארוב" — ווידג'ט מצויר: סמל שבב MediaTek עם ברק (Flash) מצויר
בהתאמה אישית, לצד המילה "הסקטארוב" בגרדיאנט בהיר (סגנון כותרות AI — לא כהה).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QRectF
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QLabel, QWidget

# סדר עדיפות גופנים עבריים אסתטיים; אחרון — גופן מערכת מובטח
_FONT_CANDIDATES = ("Gisha", "Aharoni", "David Libre", "Rubik", "Segoe UI")


def _logo_font() -> QFont:
    families = set(QFontDatabase.families())
    for name in _FONT_CANDIDATES:
        if name in families:
            f = QFont(name)
            f.setPointSize(18)
            f.setBold(True)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
            return f
    f = QFont()
    f.setPointSize(18)
    f.setBold(True)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
    return f


class LogoLabel(QLabel):
    """סמל + 'הסקטארוב' — ציור מלא בהתאמה אישית."""

    def __init__(self, text: str = "הסקטארוב"):
        super().__init__(text)
        self.setFont(_logo_font())
        self.setFixedHeight(40)
        self.setMinimumWidth(200)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setToolTip("הסקטארוב — ערכת ניהול מכשירי MediaTek")

    # ------------------------------------------------------------ הסמל
    def _draw_symbol(self, p: QPainter, rect: QRectF) -> None:
        """שבב עם פינים וברק במרכזו — סמל התוכנה (ניהול שבבי MediaTek)."""
        # פיני השבב
        p.setPen(QPen(QColor("#7dd3fc"), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        pin_len = rect.width() * 0.14
        gap = rect.width() * 0.30
        for i in range(3):
            x = rect.left() + rect.width() * (0.25 + 0.25 * i)
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.top() + pin_len))
            p.drawLine(QPointF(x, rect.bottom()), QPointF(x, rect.bottom() - pin_len))
        for i in range(2):
            y = rect.top() + rect.height() * (0.35 + 0.30 * i)
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.left() + pin_len, y))
            p.drawLine(QPointF(rect.right(), y), QPointF(rect.right() - pin_len, y))
        # גוף השבב — מסגרת כפולה
        body = rect.adjusted(gap * 0.55, gap * 0.55, -gap * 0.55, -gap * 0.55)
        grad = QLinearGradient(body.topLeft(), body.bottomRight())
        grad.setColorAt(0.0, QColor(56, 189, 248, 60))
        grad.setColorAt(1.0, QColor(129, 140, 248, 60))
        p.setBrush(grad)
        p.setPen(QPen(QColor("#38bdf8"), 2))
        p.drawRoundedRect(body, 6, 6)
        p.setPen(QPen(QColor(125, 211, 252, 120), 1))
        p.drawRoundedRect(body.adjusted(3, 3, -3, -3), 4, 4)
        # הברק במרכז השבב — Flash
        cx, cy = body.center().x(), body.center().y()
        s = body.width() * 0.30
        bolt = QPainterPath()
        bolt.moveTo(cx + s * 0.25, cy - s * 0.9)
        bolt.lineTo(cx - s * 0.45, cy + s * 0.1)
        bolt.lineTo(cx - s * 0.02, cy + s * 0.1)
        bolt.lineTo(cx - s * 0.25, cy + s * 0.9)
        bolt.lineTo(cx + s * 0.45, cy - s * 0.12)
        bolt.lineTo(cx + s * 0.02, cy - s * 0.12)
        bolt.closeSubpath()
        bolt_grad = QLinearGradient(0, cy - s, 0, cy + s)
        bolt_grad.setColorAt(0.0, QColor("#fde68a"))
        bolt_grad.setColorAt(1.0, QColor("#f59e0b"))
        p.setBrush(bolt_grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(bolt)

    # ------------------------------------------------------------ הציור
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(self.font())
        w, h = self.width(), self.height()

        # RTL: הסמל בקצה הימני, הטקסט משמאלו — במרכז השטח הנותר
        fm = p.fontMetrics()
        text_w = fm.horizontalAdvance(self.text())
        sym = 26
        margin = 4
        sym_rect = QRectF(w - margin - sym, (h - sym) / 2, sym, sym)
        self._draw_symbol(p, sym_rect)

        # הטקסט: צל עדין + גרדיאנט בהיר (כסף → תכלת → לילך)
        text_rect = QRectF(margin, 0, w - margin * 2 - sym - 10, h)
        p.setPen(QColor(15, 23, 42, 140))
        p.drawText(text_rect.translated(0, 2), Qt.AlignmentFlag.AlignCenter, self.text())
        tg = QLinearGradient(0, 0, 0, h)
        tg.setColorAt(0.0, QColor("#f8fafc"))
        tg.setColorAt(0.5, QColor("#bae6fd"))
        tg.setColorAt(1.0, QColor("#c4b5fd"))
        p.setPen(QPen(QBrush(tg), 1))   # גרדיאנט לטקסט — דרך QPen+QBrush
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


class BankGlyph(QWidget):
    """סמל בנק הסקטארים: שכבות ארכיון עם שבב קטן — ציור מותאם."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(24, 24)
        self.setToolTip("בנק הסקטארים — ארכיון קובצי Scatter לפי מעבד/מכשיר")

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QColor("#38bdf8"))
        grad.setColorAt(1.0, QColor("#818cf8"))
        # שלוש שכבות ארכיון
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            y = h * (0.14 + 0.24 * i)
            layer = QRectF(w * 0.10, y, w * 0.80, h * 0.16)
            p.setBrush(QColor(56, 189, 248, 90 + 55 * i))
            p.drawRoundedRect(layer, 2.5, 2.5)
            p.setPen(QPen(grad, 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(layer, 2.5, 2.5)
            p.setPen(Qt.PenStyle.NoPen)
        # שבב קטן בפינה
        chip = QRectF(w * 0.62, h * 0.66, w * 0.30, h * 0.30)
        p.setBrush(QColor("#fde68a"))
        p.setPen(QPen(QColor("#f59e0b"), 1.2))
        p.drawRoundedRect(chip, 2, 2)
        p.end()
