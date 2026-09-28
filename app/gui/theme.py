# -*- coding: utf-8 -*-
"""
ערכות עיצוב: "בהיר" (תכלת דיגיטלי עמוק) / "כהה". הבחירה נשמרת ב-QSettings ונטענת בהפעלה הבאה.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_SETTINGS = ("Askateroov", "Askateroov")

# צבעי שורות הלוג לכל ערכה
LOG_COLORS = {
    # ערכת הכחול העמוק — טקסט בהיר על רקע כחול כהה
    False: {"info": "#e9f1fb", "success": "#5ee08a", "warning": "#ffcf6b",
            "error": "#ff8b8b", "raw": "#a9c4e0", "stamp": "#7f97b5"},
    True: {"info": "#c9d1d9", "success": "#3fb950", "warning": "#d29922",
           "error": "#f85149", "raw": "#8b949e", "stamp": "#6e7681"},
}


def settings() -> QSettings:
    return QSettings(*_SETTINGS)


def load_dark() -> bool:
    return str(settings().value("dark_theme", "false")).lower() in ("true", "1")


def save_dark(dark: bool) -> None:
    settings().setValue("dark_theme", "true" if dark else "false")


def load_flexible_tabs() -> bool:
    """מצב 'סדר לשוניות גמיש' — כבוי כברירת מחדל, נשמר בין הפעלות."""
    return str(settings().value("flexible_tab_order", "false")).lower() in ("true", "1")


def save_flexible_tabs(on: bool) -> None:
    settings().setValue("flexible_tab_order", "true" if on else "false")


def load_tab_order() -> list[str]:
    """סדר הלשוניות שנבחר ידנית — לפי טקסט הלשונית. רשימה ריקה = אין סדר שמור."""
    val = settings().value("tab_order", [])
    if isinstance(val, str):
        return [t for t in val.split("|") if t]
    return [str(t) for t in (val or [])]


def save_tab_order(texts: list[str]) -> None:
    settings().setValue("tab_order", list(texts))


def clear_tab_order() -> None:
    """מוחק את הסדר השמור — חוזרים לסדר ברירת המחדל שבקוד."""
    settings().setValue("tab_order", [])


def _dark_palette() -> QPalette:
    p = QPalette()
    base, alt, window, text = QColor(24, 26, 31), QColor(33, 36, 43), QColor(30, 33, 39), QColor(220, 223, 228)
    disabled = QColor(120, 124, 132)
    accent = QColor(56, 132, 255)
    p.setColor(QPalette.ColorRole.Window, window)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, alt)
    p.setColor(QPalette.ColorRole.ToolTipBase, alt)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, QColor(40, 44, 52))
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.BrightText, QColor(255, 90, 90))
    p.setColor(QPalette.ColorRole.Link, accent)
    p.setColor(QPalette.ColorRole.Highlight, accent)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.PlaceholderText, disabled)
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return p


def _light_palette() -> QPalette:
    """ערכת "כחול עמוק" — במקום הלבן/התכלת הבהירה הקודמת.

    הגוון אחיד לכל המשטחים: רקע החלון, המלבנים (GroupBox), תיבות התפריטים,
    השדות והכפתורים — כולם אותו כחול עמוק, בגבהים שונים ובאיזון ביניהם.
    הטקסט בהיר, ובהדגשה — כחול דיגיטלי.
    """
    p = QPalette()
    text = QColor(233, 241, 251)     # טקסט ראשי — כמעט לבן עם נגיעת כחול
    disabled = QColor(127, 151, 181)
    accent = QColor(47, 129, 247)    # כחול דיגיטלי (הדגשה/סימון/קישור)
    p.setColor(QPalette.ColorRole.Window, QColor(15, 43, 77))       # רקע כללי — כחול עמוק
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, QColor(10, 30, 57))         # שדות קלט / טבלאות — שקוע
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(18, 50, 90))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(10, 30, 57))
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, QColor(22, 55, 95))       # כפתורים — מוארים מעט מהרקע
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.BrightText, QColor(255, 138, 128))
    p.setColor(QPalette.ColorRole.Link, accent)
    p.setColor(QPalette.ColorRole.Highlight, accent)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(6, 24, 46))
    p.setColor(QPalette.ColorRole.PlaceholderText, disabled)
    p.setColor(QPalette.ColorRole.Light, QColor(36, 80, 127))       # גווני המסגרות — כחול מדורג
    p.setColor(QPalette.ColorRole.Midlight, QColor(28, 67, 112))
    p.setColor(QPalette.ColorRole.Mid, QColor(22, 58, 95))
    p.setColor(QPalette.ColorRole.Dark, QColor(11, 35, 64))
    p.setColor(QPalette.ColorRole.Shadow, QColor(6, 22, 49))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return p


# ----------------------------------------------------------------------
# כפתורי פעולה ראשיים (לפי objectName): btnPrimary=ירוק, btnDanger=אדום, btnWarn=כתום.
# מוגדרים כאן במרכז — צבע אחיד לכל התוכנה, עם וריאציית ניגודיות קלה בין הערכות:
# בערכה הבהירה הגוונים כהים מעט יותר כדי שיבלטו על הרקע הבהיר.

_VARIANTS_DARK = {
    "btnPrimary": {"base": "#2ea44f", "hover": "#2c974b", "pressed": "#298a43",
                   "disabled": "#6b8f77", "disabled_text": "#e6e6e6"},
    "btnDanger":  {"base": "#d93a49", "hover": "#c73340", "pressed": "#b02d3a",
                   "disabled": "#8f5a60", "disabled_text": "#e6d5d7"},
    "btnWarn":    {"base": "#bf8700", "hover": "#ab7a00", "pressed": "#966c00",
                   "disabled": "#8a7a4a", "disabled_text": "#efe9d9"},
}

_VARIANTS_LIGHT = {
    "btnPrimary": {"base": "#1f8a3e", "hover": "#1c7d38", "pressed": "#186d30",
                   "disabled": "#9dbfa9", "disabled_text": "#f2f8f4"},
    "btnDanger":  {"base": "#c93343", "hover": "#b52d3b", "pressed": "#9c2532",
                   "disabled": "#c79aa0", "disabled_text": "#fdf3f4"},
    "btnWarn":    {"base": "#a86e00", "hover": "#946100", "pressed": "#7d5300",
                   "disabled": "#c4ae85", "disabled_text": "#fdf9ef"},
}


def action_buttons_qss(dark: bool) -> str:
    """עיצוב אחיד לכפתורי הפעולה הראשיים — מוחל על כל החלון ומתעדכן במעבר בהיר/כהה."""
    rules = []
    for name, c in (_VARIANTS_DARK if dark else _VARIANTS_LIGHT).items():
        rules.append(
            f"QPushButton#{name} {{ background: {c['base']}; color: white; font-weight: bold;"
            f" font-size: 13px; padding: 6px 18px; border: none; border-radius: 6px;"
            f" min-height: 27px; }}"
            f"QPushButton#{name}:hover {{ background: {c['hover']}; }}"
            f"QPushButton#{name}:pressed {{ background: {c['pressed']}; }}"
            f"QPushButton#{name}:disabled {{ background: {c['disabled']};"
            f" color: {c['disabled_text']}; }}"
        )
    return "\n".join(rules)


def soft_button_qss(dark: bool) -> str:
    """כפתורי btnSoft — כמתוחכמים מבחינת מידות אך ניטרליים: רקע = הצבע שמאחוריהם,
    רק בהיר ממנו במקצת (בהיר בערכה הבהירה, מואר בערכה הכהה)."""
    if dark:
        base, hover, pressed, border, text = ("#333a46", "#3d4554", "#2a313c",
                                              "#454e5d", "#dcdfe4")
    else:
        # ערכת הכחול העמוק — מעט בהיר מהרקע שמאחוריהם, כמו בערכה הכהה
        base, hover, pressed, border, text = ("#143459", "#1b4270", "#0f2846",
                                              "#2a5b91", "#e9f1fb")
    return (f"QPushButton#btnSoft {{ background: {base}; color: {text};"
            f" font-size: 13px; padding: 6px 18px; border: 1px solid {border};"
            f" border-radius: 6px; min-height: 27px; }}"
            f"QPushButton#btnSoft:hover {{ background: {hover}; }}"
            f"QPushButton#btnSoft:pressed {{ background: {pressed}; }}")


# הגדלת כל הכפתורים בתוכנה (גופן + אמוג'י + ריווח) — פי 1.25
BUTTON_SCALE = 1.25


def _buttons_css(app) -> str:
    """כלל אחיד לכל הכפתורים: גופן גדול ב-25% וריווח פנימי מוגדל בהתאם."""
    base = app.font().pointSizeF()
    if base <= 0:
        base = 9.0
    size = round(base * BUTTON_SCALE, 1)
    return (f" QPushButton, QToolButton {{ font-size: {size}pt;"
            f" padding: 6px 14px; min-height: 26px; }}")


_current_dark = False


def mtk_color() -> QColor:
    """צבע שורות MTK בטבלאות — לפי הערכה הפעילה (מתעדכן ב-apply_theme)."""
    return QColor("#3fb950") if _current_dark else QColor("#45d17a")


def warn_color() -> QColor:
    """צבע אזהרה בטבלאות — לפי הערכה הפעילה."""
    return QColor("#d29922") if _current_dark else QColor("#e0b341")


def apply_theme(dark: bool) -> None:
    global _current_dark
    app = QApplication.instance()
    if app is None:
        return
    _current_dark = dark
    app.setStyle("Fusion")
    tooltip = ("QToolTip { color: #dcdfe4; background: #21242b; border: 1px solid #3a3f4b; }"
               if dark else
               "QToolTip { color: #e9f1fb; background: #0a1e39; border: 1px solid #2a5b91; }")
    app.setPalette(_dark_palette() if dark else _light_palette())
    app.setStyleSheet(tooltip + _buttons_css(app) + action_buttons_qss(dark)
                     + soft_button_qss(dark))
