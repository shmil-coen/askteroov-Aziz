# -*- coding: utf-8 -*-
"""
סמלים מצוירים (QPainter) — לכפתורי השאיבה והצריבה וללשוניות שלהן.

אימוג'י לא מתאים כאן: צבעי האימוג'י נקבעים על ידי גופן המערכת ולא ניתנים לשליטה.
ציור מקומי מבטיח את אותה התוצאה בכל מחשב. הצבע מועבר בפרמטר color — החלון הראשי
מעביר את צבעי ערכת העיצוב הפעילה (theme.py); צבעי ברירת המחדל כאן רק לגיבוי.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_GREEN = "#53b64e"    # הירוק של החצים (כמו בדגמים שהוגדרו)
_GREEN_EDGE = "#3d8f3b"
_GREY = "#8c959f"     # אפור ניטרלי לסמל ההגדרות — קריא בערכה בהירה ובכהה כאחת
_ACCENT = "#2f81f7"   # כחול ההדגשה של התוכנה — לסמל המידע העגול


def _base(size: int) -> tuple[QPixmap, QPainter]:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pm, p


def down_arrow_icon(size: int = 64, color: str = _GREEN) -> QIcon:
    """חץ יורד ישר למטה — גב מלבני + ראש משולש (לשונית/כפתור צריבה)."""
    pm, p = _base(size)
    w = float(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(color)))
    # גב החץ
    stem_w = w * 0.30
    p.drawRect(QRectF((w - stem_w) / 2, w * 0.06, stem_w, w * 0.40))
    # ראש החץ
    head = QPainterPath()
    head.moveTo(w * 0.06, w * 0.40)
    head.lineTo(w * 0.94, w * 0.40)
    head.lineTo(w * 0.50, w * 0.94)
    head.closeSubpath()
    p.drawPath(head)
    p.end()
    return QIcon(pm)


def curved_left_arrow_icon(size: int = 64, color: str = _GREEN) -> QIcon:
    """חץ מתעגל שמאלה (בסגנון חץ-תשובה) — לשונית/כפתור שאיבה."""
    pm, p = _base(size)
    w = float(size)
    # זנב מעוקל: מתחתית-ימין מתעגל כלפי מרכז-שמאל
    path = QPainterPath()
    path.moveTo(w * 0.88, w * 0.82)
    path.cubicTo(w * 0.90, w * 0.36, w * 0.64, w * 0.16, w * 0.36, w * 0.30)
    pen = QPen(QColor(color))
    pen.setWidthF(w * 0.20)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    # ראש החץ — משולש בקצה השמאלי, מצביע שמאלה
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(color)))
    head = QPainterPath()
    head.moveTo(w * 0.02, w * 0.30)
    head.lineTo(w * 0.42, w * 0.08)
    head.lineTo(w * 0.42, w * 0.52)
    head.closeSubpath()
    p.drawPath(head)
    p.end()
    return QIcon(pm)


def round_info_pixmap(size: int = 24, color: str = _ACCENT) -> QPixmap:
    """עיגול מידע מצויר (במקום האימוג'י ℹ️) — עגול, אחיד וקריא בכל ערכה."""
    pm, p = _base(size)
    w = float(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(color)))
    p.drawEllipse(QRectF(w * 0.03, w * 0.03, w * 0.94, w * 0.94))
    # האות i: נקודה עגולה למעלה וגוף מעוגל מתחת — בלבן לקריאוּת
    p.setBrush(QBrush(QColor("#ffffff")))
    dot = w * 0.15
    p.drawEllipse(QRectF(w / 2 - dot / 2, w * 0.21, dot, dot))
    stem_w = w * 0.14
    p.drawRoundedRect(QRectF(w / 2 - stem_w / 2, w * 0.44, stem_w, w * 0.35),
                      stem_w / 2, stem_w / 2)
    p.end()
    return pm


def gear_icon(size: int = 64, color: str = _GREY) -> QIcon:
    """גלגל שיניים — כפתור ההגדרות בפס העליון (סמל בלבד, בלי טקסט).

    שמונה שיניים סביב גוף עגול וחור שקוף במרכז — מצויר מקומית כדי שיהיה
    באותו צבע בשתי הערכות (אימוג'י צבעו נקבע על ידי גופן המערכת).
    """
    pm, p = _base(size)
    w = float(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(color)))
    # שיניים — מלבנים סביב המרכז, מסובבים 45° זה מזה
    p.save()
    p.translate(w / 2, w / 2)
    tooth_w, tooth_h = w * 0.17, w * 0.30
    for i in range(8):
        p.rotate(i * 45.0)
        p.drawRect(QRectF(-tooth_w / 2, -w * 0.45, tooth_w, tooth_h))
    p.restore()
    # גוף הגלגל
    p.drawEllipse(QRectF(w * 0.17, w * 0.17, w * 0.66, w * 0.66))
    # חור מרכזי — ניקוב שקוף
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.drawEllipse(QRectF(w * 0.38, w * 0.38, w * 0.24, w * 0.24))
    p.end()
    return QIcon(pm)


def globe_icon(size: int = 64, color: str = _ACCENT) -> QIcon:
    """כדור אינטרנט בקווים (כמו סמל דפדפן) — לכפתורי ההורדה הקטנים.

    עיגול חיצוני, קו משווה, שני קווי רוחב, קו אורך מרכזי ואליפסת קו אורך —
    מצויר מקומית כדי שייראה זהה בכל מחשב ובשתי הערכות.
    """
    pm, p = _base(size)
    w = float(size)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.5, w * 0.075))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = w * 0.08
    r = QRectF(m, m, w - 2 * m, w - 2 * m)
    p.drawEllipse(r)                                                  # מתאר הכדור
    p.drawEllipse(QRectF(w * 0.30, m, w * 0.40, w - 2 * m))          # קו אורך (אליפסה)
    p.drawLine(int(w / 2), int(m), int(w / 2), int(w - m))           # קו אורך מרכזי
    p.drawLine(int(m), int(w / 2), int(w - m), int(w / 2))           # קו המשווה
    p.drawLine(int(w * 0.17), int(w * 0.30), int(w * 0.83), int(w * 0.30))  # קו רוחב עליון
    p.drawLine(int(w * 0.17), int(w * 0.70), int(w * 0.83), int(w * 0.70))  # קו רוחב תחתון
    p.end()
    return QIcon(pm)
