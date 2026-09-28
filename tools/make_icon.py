# -*- coding: utf-8 -*-
"""
מחולל אייקון התוכנה — משחזר את סמל הלוגו מ-app/gui/logo.py:

  * רקע מעוגל בכחול עמוק (גרדיאנט) — כמו ערכת העיצוב של התוכנה
  * שבב עם פינים בגווני תכלת/אינדיגו (#38bdf8 → #818cf8)
  * ברק (Flash) זהוב-ענבר במרכזו (#fde68a → #f59e0b)

הפקה: tools/app_icon.ico (PNG בגדלים 16–256) — לקומפילציה עם --icon.
רץ עם הפייתון הניידת: python tools/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QRectF
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

OUT = Path(__file__).resolve().parent / "app_icon.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw_icon_pixmap(size: int) -> QPixmap:
    """מצייר את הסמל בגודל נתון — אותם צבעים ופרופורציות כמו הלוגו בתוכנה."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    w = float(size)
    # ---- רקע מעוגל: גרדיאנט כחול עמוק (מעט בהיר מהרקע של התוכנה, לבלוט בשורת המשימות)
    bg = QLinearGradient(0.0, 0.0, w, w)
    bg.setColorAt(0.0, QColor("#16375f"))
    bg.setColorAt(1.0, QColor("#0a1e39"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(QRectF(0, 0, w, w), w * 0.18, w * 0.18)

    # ---- מרחב השבב (רווח מהקצוות)
    pad = w * 0.16
    rect = QRectF(pad, pad, w - pad * 2, w - pad * 2)

    # ---- פיני השבב (3 מלמעלה/מלמטה, 2 מהצדדים — כמו בלוגו)
    p.setPen(QPen(QColor("#7dd3fc"), max(1.0, w * 0.012)))
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

    # ---- גוף השבב: מילוי גרדיאנט + מסגרת כפולה
    body = rect.adjusted(gap * 0.55, gap * 0.55, -gap * 0.55, -gap * 0.55)
    grad = QLinearGradient(body.topLeft(), body.bottomRight())
    grad.setColorAt(0.0, QColor(56, 189, 248, 90))
    grad.setColorAt(1.0, QColor(129, 140, 248, 90))
    p.setBrush(grad)
    p.setPen(QPen(QColor("#38bdf8"), max(1.2, w * 0.016)))
    p.drawRoundedRect(body, w * 0.04, w * 0.04)
    p.setPen(QPen(QColor(125, 211, 252, 120), max(1.0, w * 0.008)))
    p.drawRoundedRect(body.adjusted(w * 0.012, w * 0.012, -w * 0.012, -w * 0.012),
                      w * 0.03, w * 0.03)

    # ---- הברק במרכז (Flash) — אותן נקודות ציון כמו בלוגו
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

    p.end()
    return pm


def _write_ico(path: Path, entries: list[tuple[int, bytes]]) -> None:
    """כתיבת קובץ ICO מכולה פשוטה: כותרת + רשומה לכל גודל + נתוני PNG.

    פורמט ICO עם PNG בפנים — נתמך ב-Windows Vista ומעלה (כולל סייר, שורת משימות
    וקיצורי דרך), ו-PyInstaller מעביר את הקובץ כמות שהוא לתוך ה-exe.
    """
    import struct
    count = len(entries)
    header = struct.pack("<HHH", 0, 1, count)          # ICONDIR: reserved, type=icon, count
    offset = 6 + 16 * count                             # אחרי הכותרת והרשומות
    body = bytearray()
    directory = bytearray()
    for size, png in entries:
        b = size if size < 256 else 0                   # 256 מסומן כ-0 בשדה בן הבייט
        directory += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(png), offset)
        body += png
        offset += len(png)
    path.write_bytes(header + bytes(directory) + bytes(body))


def main() -> int:
    app = QApplication.instance() or QApplication([])
    entries: list[tuple[int, bytes]] = []
    for s in SIZES:
        pm = draw_icon_pixmap(s)
        png = bytes(pm.saveToData("PNG")) if hasattr(pm, "saveToData") else None
        if png is None:
            import tempfile, os
            tmp = Path(tempfile.gettempdir()) / f"askt_icon_{s}.png"
            pm.save(str(tmp), "PNG")
            png = tmp.read_bytes()
            tmp.unlink()
        entries.append((s, png))
    _write_ico(OUT, entries)
    print(f"created: {OUT}")
    print(f"sizes: {', '.join(str(s) for s in SIZES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
