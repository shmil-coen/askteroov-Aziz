# -*- coding: utf-8 -*-
"""
לוגו התוכנה "הסקטארוב" — ווידג'ט מצויר, בסגנון הדמו: סמל שבב בקו דק עם ברק במרכזו,
בצבע ההדגשה של הערכה, ולצידו המילה "הסקטארוב" בצבע הטקסט של הערכה.
הצבעים נלקחים מ-theme.py בכל ציור — כך שהחלפת ערכה מתעדכנת מיד.
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

from . import theme

# סדר עדיפות גופנים עבריים אסתטיים; אחרון — גופן מערכת מובטח
_FONT_CANDIDATES = ("Gisha", "Aharoni", "David Libre", "Rubik", "Segoe UI")


def _logo_font() -> QFont:
    families = set(QFontDatabase.families())
    f = QFont()
    for name in _FONT_CANDIDATES:
        if name in families:
            f = QFont(name)
            break
    f.setPointSize(16)        # ~21px, כמו בדמו
    f.setBold(True)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
    return f


class LogoLabel(QLabel):
    """סמל + 'הסקטארוב' — בקצה הימני של הפס העליון (כמו בדמו)."""

    SYMBOL = 30   # גודל הסמל בפיקסלים
    GAP = 10      # רווח בין הסמל לטקסט

    def __init__(self, text: str = "הסקטארוב"):
        super().__init__(text)
        self.setFont(_logo_font())
        self.setFixedHeight(40)
        self.setFixedWidth(self.fontMetrics().horizontalAdvance(text) + self.SYMBOL + self.GAP + 8)
        self.setToolTip("הסקטארוב — ערכת ניהול מכשירי MediaTek")

    # ------------------------------------------------------------ הסמל
    def _draw_symbol(self, p: QPainter, rect: QRectF) -> None:
        """שבב בקו דק עם פינים וברק במרכזו (כמו בדמו) — בצבע ההדגשה."""
        s = rect.width() / 24.0
        ox, oy = rect.left(), rect.top()

        def pt(x: float, y: float) -> QPointF:
            return QPointF(ox + x * s, oy + y * s)

        pen = QPen(QColor(theme.colors()["accent"]), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # גוף השבב
        p.drawRoundedRect(QRectF(pt(5, 5), pt(19, 19)), 3 * s, 3 * s)
        # פינים — שניים בכל צד
        for a in (9, 15):
            p.drawLine(pt(a, 2), pt(a, 5))
            p.drawLine(pt(a, 19), pt(a, 22))
            p.drawLine(pt(2, a), pt(5, a))
            p.drawLine(pt(19, a), pt(22, a))
        # הברק במרכז — Flash
        bolt = QPainterPath(pt(12.8, 8.5))
        bolt.lineTo(pt(10.5, 12))
        bolt.lineTo(pt(13.5, 12))
        bolt.lineTo(pt(11.2, 15.5))
        p.drawPath(bolt)

    # ------------------------------------------------------------ הציור
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(self.font())
        w, h = self.width(), self.height()
        # RTL: הסמל בקצה הימני, הטקסט משמאלו
        sym = self.SYMBOL
        self._draw_symbol(p, QRectF(w - sym, (h - sym) / 2, sym, sym))
        text_rect = QRectF(0, 0, w - sym - self.GAP, h)
        p.setPen(QColor(theme.colors()["text"]))
        p.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.text())
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
