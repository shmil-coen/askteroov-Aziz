# -*- coding: utf-8 -*-
"""
ערכות עיצוב: "גרפיט רך" (ברירת מחדל) / "כחול לילה". הבחירה נשמרת ב-QSettings
ונטענת בהפעלה הבאה.

כל המראה של התוכנה מוגדר כאן, במקום אחד: צבעי הערכה (PALETTES), ה-QPalette של Qt,
וגיליון סגנון (QSS) אחד לכל היישום — כרטיסים, כפתורים לפי תפקיד, שדות, טבלאות,
לשוניות, מד התקדמות, תפריטים ופסי גלילה.

תפקידי כפתורים (לפי objectName):
  (ללא)       — משני: מסגרת בלבד. ברירת המחדל לכל כפתור.
  btnPrimary  — ראשי: מלא בצבע ההדגשה. פעולה עיקרית אחת לכל אזור.
  btnSoft     — רך: רקע בגוון ההדגשה.
  btnDanger   — אדום: פעולות מסוכנות (צריבה, פתיחת בוטלאודר).
  btnWarn     — כתום: פעולות שדורשות זהירות (מחיקה, הרשאות).
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_SETTINGS = ("Askateroov", "Askateroov")

# ----------------------------------------------------------------------
# צבעי הערכות. המפתח True = "גרפיט רך" (ברירת המחדל), False = "כחול לילה".
# (שם המפתח "dark" נשמר מהגרסאות הקודמות — כך בחירה שמורה ממשיכה לעבוד.)
PALETTES = {
    True: {   # גרפיט רך
        "name": "גרפיט רך",
        "bg": "#15171c", "bar": "#1a1d23", "surface": "#1f2229", "surface2": "#282c34",
        "border": "#30353f", "input": "#17191e",
        "text": "#e8eaef", "muted": "#a3aab6",
        "accent": "#6ea2ff", "accent_soft": "rgba(110,162,255,0.14)",
        "btn": "#2f6ee0", "btn_hover": "#3a7af0", "btn_pressed": "#2860c8", "btn_text": "#ffffff",
        "ok": "#4cc68a", "ok_soft": "rgba(76,198,138,0.13)", "warn": "#e8b04a", "warn_soft": "rgba(232,176,74,0.14)", "danger": "#e5534b", "danger_soft": "rgba(229,83,75,0.14)",
        "danger_btn": "#c8322b", "danger_hover": "#d63b33", "danger_pressed": "#b02a24",
        "warn_btn": "#a15c00", "warn_hover": "#b06600", "warn_pressed": "#8a4f00",
        "disabled": "#6b7280",
    },
    False: {  # כחול לילה
        "name": "כחול לילה",
        "bg": "#0d1829", "bar": "#101f36", "surface": "#15263f", "surface2": "#1c3150",
        "border": "#274463", "input": "#0f1d33",
        "text": "#e9f0f9", "muted": "#9fb3cd",
        "accent": "#72b0ff", "accent_soft": "rgba(114,176,255,0.15)",
        "btn": "#5ea4ff", "btn_hover": "#74b1ff", "btn_pressed": "#4a93f0", "btn_text": "#08182c",
        "ok": "#4fd092", "ok_soft": "rgba(79,208,146,0.14)", "warn": "#f0b64e", "warn_soft": "rgba(240,182,78,0.15)", "danger": "#f06a60", "danger_soft": "rgba(240,106,96,0.15)",
        "danger_btn": "#d23a31", "danger_hover": "#e0443a", "danger_pressed": "#b8302a",
        "warn_btn": "#a15c00", "warn_hover": "#b06600", "warn_pressed": "#8a4f00",
        "disabled": "#6f86a3",
    },
}

# צבעי שורות הלוג לכל ערכה (נגזרים מצבעי הערכה)
LOG_COLORS = {
    k: {"info": c["text"], "success": c["ok"], "warning": c["warn"], "error": c["danger"],
        "raw": c["muted"], "stamp": c["muted"]}
    for k, c in PALETTES.items()
}


def settings() -> QSettings:
    return QSettings(*_SETTINGS)


def load_dark() -> bool:
    # ברירת מחדל: "גרפיט רך". בחירה שהמשתמש שמר בתפריט ההגדרות — נשמרת
    return str(settings().value("dark_theme", "true")).lower() in ("true", "1")


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


# ----------------------------------------------------------------------
_current_dark = True


def colors(dark: bool | None = None) -> dict:
    """צבעי הערכה הפעילה (או של ערכה מסוימת) — לשימוש בקוד שמצייר בעצמו."""
    return PALETTES[_current_dark if dark is None else dark]


def mtk_color() -> QColor:
    """צבע שורות MTK בטבלאות — לפי הערכה הפעילה."""
    return QColor(colors()["ok"])


def warn_color() -> QColor:
    """צבע אזהרה בטבלאות — לפי הערכה הפעילה."""
    return QColor(colors()["warn"])


def progress_qss(state: str = "") -> str:
    """צבע מילוי מד ההתקדמות לפי מצב: "" רגיל · "ok" הצלחה · "cancel" ביטול/כשלון."""
    c = colors()
    if state == "ok":
        return f"QProgressBar::chunk {{ background-color: {c['ok']}; border-radius: 3px; }}"
    if state == "cancel":
        return f"QProgressBar::chunk {{ background-color: {c['danger']}; border-radius: 3px; }}"
    return ""


def _palette(c: dict) -> QPalette:
    p = QPalette()
    q = QColor
    p.setColor(QPalette.ColorRole.Window, q(c["bg"]))
    p.setColor(QPalette.ColorRole.WindowText, q(c["text"]))
    p.setColor(QPalette.ColorRole.Base, q(c["input"]))
    p.setColor(QPalette.ColorRole.AlternateBase, q(c["surface"]))
    p.setColor(QPalette.ColorRole.ToolTipBase, q(c["surface2"]))
    p.setColor(QPalette.ColorRole.ToolTipText, q(c["text"]))
    p.setColor(QPalette.ColorRole.Text, q(c["text"]))
    p.setColor(QPalette.ColorRole.Button, q(c["surface2"]))
    p.setColor(QPalette.ColorRole.ButtonText, q(c["text"]))
    p.setColor(QPalette.ColorRole.BrightText, q(c["danger"]))
    p.setColor(QPalette.ColorRole.Link, q(c["accent"]))
    p.setColor(QPalette.ColorRole.Highlight, q(c["btn"]))
    p.setColor(QPalette.ColorRole.HighlightedText, q(c["btn_text"]))
    p.setColor(QPalette.ColorRole.PlaceholderText, q(c["disabled"]))
    p.setColor(QPalette.ColorRole.Light, q(c["surface2"]))
    p.setColor(QPalette.ColorRole.Midlight, q(c["border"]))
    p.setColor(QPalette.ColorRole.Mid, q(c["border"]))
    p.setColor(QPalette.ColorRole.Dark, q(c["bar"]))
    p.setColor(QPalette.ColorRole.Shadow, q(c["bg"]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, q(c["disabled"]))
    return p


# הגדלת כל הכפתורים בתוכנה (גופן + אמוג'י + ריווח) — פי 1.25
BUTTON_SCALE = 1.25


def _qss(c: dict, btn_pt: float) -> str:
    """גיליון הסגנון של כל היישום — נבנה מצבעי הערכה."""
    return f"""
QToolTip {{ color: {c['text']}; background: {c['surface2']}; border: 1px solid {c['border']};
           border-radius: 6px; padding: 6px 8px; }}

/* ---- סרגל עליון ---- */
QToolBar {{ background: {c['bar']}; border: none; border-bottom: 1px solid {c['border']};
           padding: 6px 12px; spacing: 8px; }}
QToolButton {{ color: {c['text']}; background: transparent; border: 1px solid {c['border']};
              border-radius: 10px; padding: 6px 12px; font-size: {btn_pt}pt; }}
QToolButton:hover {{ background: {c['surface2']}; }}
QToolButton:checked {{ background: {c['accent_soft']}; color: {c['accent']}; border-color: transparent; }}

/* ---- כרטיסים (QGroupBox) — כותרת בתוך הכרטיס ----
   (בממשק מימין-לשמאל Qt הופך את הצדדים: "left" כאן = צד ימין על המסך) */
QGroupBox {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 14px;
            margin-top: 0px; padding: 34px 14px 14px 14px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;
                   top: 12px; left: 16px; padding: 0; color: {c['text']}; }}

/* ---- כפתורים: ברירת המחדל = משני (מסגרת) ---- */
QPushButton {{ color: {c['text']}; background: transparent; border: 1px solid {c['border']};
              border-radius: 10px; padding: 7px 16px; min-height: 24px; font-size: {btn_pt}pt; }}
QPushButton:hover {{ background: {c['surface2']}; }}
QPushButton:pressed {{ background: {c['border']}; }}
QPushButton:disabled {{ color: {c['disabled']}; border-color: {c['surface2']}; }}
QPushButton#btnPrimary {{ background: {c['btn']}; color: {c['btn_text']}; border: none; font-weight: 600; }}
QPushButton#btnPrimary:hover {{ background: {c['btn_hover']}; }}
QPushButton#btnPrimary:pressed {{ background: {c['btn_pressed']}; }}
QPushButton#btnSoft {{ background: {c['accent_soft']}; color: {c['accent']}; border: none; font-weight: 600; }}
QPushButton#btnSoft:hover {{ background: {c['surface2']}; }}
QPushButton#btnDanger {{ background: {c['danger_btn']}; color: #ffffff; border: none; font-weight: 600; }}
QPushButton#btnDanger:hover {{ background: {c['danger_hover']}; }}
QPushButton#btnDanger:pressed {{ background: {c['danger_pressed']}; }}
QPushButton#btnWarn {{ background: {c['warn_btn']}; color: #ffffff; border: none; font-weight: 600; }}
QPushButton#btnWarn:hover {{ background: {c['warn_hover']}; }}
QPushButton#btnWarn:pressed {{ background: {c['warn_pressed']}; }}
QPushButton#btnPrimary:disabled, QPushButton#btnSoft:disabled,
QPushButton#btnDanger:disabled, QPushButton#btnWarn:disabled {{ background: {c['surface2']}; color: {c['disabled']}; }}

/* ---- שדות קלט ורשימות ---- */
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget,
QTableWidget, QTableView {{ background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']};
                           border-radius: 8px; selection-background-color: {c['btn']};
                           selection-color: {c['btn_text']}; }}
QLineEdit, QComboBox, QSpinBox {{ padding: 6px 10px; min-height: 22px; }}
QTextEdit, QPlainTextEdit {{ padding: 6px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {c['accent']}; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['border']};
                              selection-background-color: {c['accent_soft']}; selection-color: {c['text']}; outline: none; }}

/* ---- טבלאות ---- */
QTableWidget, QTableView {{ gridline-color: {c['border']}; alternate-background-color: {c['surface']};
                           selection-background-color: {c['accent_soft']}; selection-color: {c['text']}; }}
QTableWidget::item:selected, QTableView::item:selected {{ background: {c['accent_soft']}; color: {c['text']}; }}
QHeaderView::section {{ background: {c['surface2']}; color: {c['muted']}; border: none;
                       border-bottom: 1px solid {c['border']}; padding: 6px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {c['surface2']}; border: none; }}

/* ---- לשוניות ראשיות ("גלולות") ---- */
QTabWidget::pane {{ border: none; top: 6px; }}
QTabBar#mainTabBar {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 14px; }}
QTabBar::tab {{ background: transparent; color: {c['muted']}; border: none; border-radius: 10px;
               margin: 5px 2px; }}
QTabBar::tab:hover:!selected {{ background: {c['surface2']}; color: {c['text']}; }}
QTabBar::tab:selected {{ background: {c['btn']}; color: {c['btn_text']}; }}
/* בשורת הלשוניות הראשית ה"גלולה" של הלשונית הנבחרת מצוירת בקוד ונעה ביניהן (כמו בדמו) */
QTabBar#mainTabBar::tab:selected {{ background: transparent; }}

/* ---- מד התקדמות ---- */
QProgressBar {{ background: {c['surface2']}; border: none; border-radius: 6px; min-height: 12px; max-height: 12px;
               color: {c['text']}; text-align: center; font-size: 8pt; }}
QProgressBar::chunk {{ background-color: {c['accent']}; border-radius: 6px; }}

/* ---- תפריטים ---- */
QMenu {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 8px 18px; border-radius: 8px; }}
QMenu::item:selected {{ background: {c['surface2']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 6px 8px; }}

/* ---- פסי גלילה דקים ---- */
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {c['border']}; border-radius: 4px; }}
QScrollBar::handle:hover {{ background: {c['disabled']}; }}
QScrollBar::handle:vertical {{ min-height: 30px; }}
QScrollBar::handle:horizontal {{ min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---- כרטיס המכשיר (כמו בדמו) ---- */
QFrame#deviceCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QFrame#vsep {{ background: {c['border']}; border: none; }}
QLabel#devIcon {{ background: {c['surface2']}; border-radius: 12px; }}
QLabel#devIcon[state="on"] {{ background: {c['ok_soft']}; }}
QLabel#devTitle {{ font-size: 13pt; font-weight: 600; }}
QLabel#devSub {{ color: {c['muted']}; font-size: 10pt; }}
QLabel#statCaption {{ color: {c['muted']}; font-size: 9pt; }}
QLabel#statValue {{ font-size: 11pt; font-weight: 600; }}
QLabel#chanLabel {{ color: {c['muted']}; font-size: 10pt; }}

/* ---- פס עליון: גרסה ---- */
QLabel#versionPill {{ color: {c['muted']}; background: {c['surface2']}; border-radius: 10px;
                     padding: 4px 10px; font-size: 9pt; }}

/* ---- שורת המצב (כמו בדמו) ---- */
QFrame#statusCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QLabel#statusDot {{ background: {c['ok']}; border-radius: 4px; }}
QLabel#statusDot[state="run"] {{ background: {c['accent']}; }}
QLabel#statusDot[state="err"] {{ background: {c['danger']}; }}
QProgressBar#statusProgress {{ min-height: 7px; max-height: 7px; border-radius: 3px; }}
QProgressBar#statusProgress::chunk {{ border-radius: 3px; }}

/* ---- כותרת לשונית (ui_kit.tab_header) ---- */
QLabel#tabTitle {{ font-size: 16pt; font-weight: 600; }}
QLabel#tabDesc {{ color: {c['muted']}; font-size: 10.5pt; }}
QLabel#chanChip {{ color: {c['muted']}; background: {c['surface']}; border: 1px solid {c['border']};
                  border-radius: 12px; padding: 5px 14px; font-size: 10pt; }}

/* ---- כרטיס (ui_kit.Card) ---- */
QFrame#card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QLabel#cardIcon {{ background: {c['accent_soft']}; border-radius: 10px; }}
QLabel#cardIcon[danger="true"] {{ background: {c['danger_soft']}; }}
QLabel#cardTitle {{ font-size: 13pt; font-weight: 600; }}
QLabel#cardDesc {{ color: {c['muted']}; font-size: 10pt; }}

/* ---- תגיות (ui_kit.Pill) ---- */
QLabel#pill {{ border-radius: 8px; padding: 3px 10px; font-size: 9pt; font-weight: 500; }}
QLabel#pill[kind="ok"] {{ color: {c['ok']}; background: {c['ok_soft']}; }}
QLabel#pill[kind="warn"] {{ color: {c['warn']}; background: {c['warn_soft']}; }}
QLabel#pill[kind="danger"] {{ color: {c['danger']}; background: {c['danger_soft']}; }}
QLabel#pill[kind="info"] {{ color: {c['accent']}; background: {c['accent_soft']}; font-weight: 600; }}
QLabel#pill[kind="neutral"] {{ color: {c['muted']}; background: {c['surface2']}; }}

/* ---- מצב ריק ושורות שם/ערך ---- */
QLabel#emptyState {{ color: {c['muted']}; border: 1px dashed {c['border']}; border-radius: 14px;
                    padding: 28px 20px; font-size: 10.5pt; }}
QFrame#kvList {{ background: transparent; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#kvSep {{ background: {c['border']}; border: none; }}
QLabel#kvKey {{ color: {c['muted']}; font-size: 10pt; }}
QLabel#kvVal {{ font-size: 10.5pt; }}

/* ---- כפתורים נוספים: שקוף · מסגרת אדומה · סמל בלבד ---- */
QPushButton#btnGhost {{ background: transparent; border: none; color: {c['muted']}; padding: 7px 10px; }}
QPushButton#btnGhost:hover {{ color: {c['text']}; background: transparent; }}
QPushButton#btnGhost::menu-indicator {{ image: none; width: 0px; }}
QPushButton#btnDangerOutline {{ background: transparent; color: {c['danger']}; border: 1px solid {c['danger']}; }}
QPushButton#btnDangerOutline:hover {{ background: {c['danger_soft']}; }}
QPushButton#iconBtn {{ padding: 0px; min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; }}

/* ---- תיבות הודעה ---- */
QTextEdit#quietBox {{ background: transparent; border: none; color: {c['muted']}; padding: 0px; }}
QLabel#noticeWarn {{ background: {c['warn_soft']}; border-radius: 12px; padding: 12px 14px; }}
QLabel#noticeInfo {{ background: {c['accent_soft']}; border-radius: 12px; padding: 12px 14px; }}
QLabel#noticeDanger {{ background: {c['danger_soft']}; border-radius: 12px; padding: 12px 14px; }}

/* ---- צעדים ממוספרים · מצב ריק עם כפתור · תיבת מצב · רשימת בדיקה ---- */
QLabel#stepNum {{ background: {c['accent_soft']}; color: {c['accent']}; border-radius: 11px;
                 font-size: 9pt; font-weight: 600; }}
QLabel#stepText {{ font-size: 10.5pt; }}
QFrame#emptyBox {{ border: 1px dashed {c['border']}; border-radius: 14px; background: transparent; }}
QLabel#emptyText {{ color: {c['muted']}; font-size: 10.5pt; }}
QFrame#statusBox {{ background: {c['surface2']}; border-radius: 12px; }}
QFrame#statusBox[state="ok"] {{ background: {c['ok_soft']}; }}
QFrame#statusBox[state="err"] {{ background: {c['danger_soft']}; }}
QLabel#statusMark {{ background: {c['border']}; border-radius: 16px; }}
QLabel#statusMark[state="ok"] {{ background: {c['ok']}; }}
QLabel#statusMark[state="err"] {{ background: {c['danger']}; }}
QLabel#statusTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#statusSub {{ color: {c['muted']}; font-size: 10pt; }}
QLabel#checkMark {{ background: {c['surface2']}; color: {c['muted']}; border-radius: 10px; font-size: 9pt; }}
QLabel#checkMark[on="true"] {{ background: {c['ok_soft']}; color: {c['ok']}; font-weight: 600; }}

/* ---- כפתורי סינון (לוג) ---- */
QPushButton#chip {{ border: 1px solid {c['border']}; border-radius: 12px; padding: 4px 12px;
                   min-height: 0px; background: transparent; color: {c['muted']}; }}
QPushButton#chip:checked {{ background: {c['accent_soft']}; color: {c['accent']}; border-color: transparent; font-weight: 600; }}

/* ---- הודעות בצד (ui_kit.Toast) ---- */
QFrame#toast {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 14px; }}
QLabel#toastText {{ font-size: 13pt; font-weight: 500; }}
QLabel#toastDot {{ background: {c['accent']}; border-radius: 6px; }}
QLabel#toastDot[kind="ok"] {{ background: {c['ok']}; }}
QLabel#toastDot[kind="warn"] {{ background: {c['warn']}; }}
QLabel#toastDot[kind="err"] {{ background: {c['danger']}; }}
QPushButton#toastBtn {{ background: {c['accent_soft']}; color: {c['accent']}; border: none; border-radius: 9px;
                       padding: 5px 12px; min-height: 0px; font-size: 10.5pt; font-weight: 600; }}
QPushButton#toastBtn:hover {{ background: {c['surface2']}; }}
QPushButton#toastClose {{ background: transparent; border: none; color: {c['muted']}; padding: 2px 6px;
                         min-height: 0px; font-size: 12pt; }}
QPushButton#toastClose:hover {{ color: {c['text']}; background: transparent; }}

/* ---- חלון (ui_kit.Modal) — כרטיס באמצע, כמו בדמו ---- */
QFrame#modal {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 18px; }}
QLabel#modalTitle {{ font-size: 15pt; font-weight: 600; }}
QLabel#modalOp {{ font-size: 11.5pt; }}
QLabel#modalText {{ font-size: 10.5pt; }}
QLabel#modalIcon {{ background: {c['danger_soft']}; border-radius: 19px; }}
QLabel#modalIcon[kind="check"] {{ background: {c['ok_soft']}; }}
QFrame#cmds {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QLabel#cmdStep {{ color: {c['muted']}; font-size: 9.5pt; }}
QLabel#cmdText {{ font-family: Consolas, 'Cascadia Mono', monospace; font-size: 10pt; }}
QLabel#reason {{ background: {c['danger_soft']}; border-radius: 12px; padding: 12px 14px; font-size: 10.5pt; }}
QLabel#okNote {{ background: {c['ok_soft']}; border-radius: 12px; padding: 12px 14px; font-size: 10.5pt; }}
QLabel#secTitle {{ font-size: 10.5pt; font-weight: 600; }}
QPushButton#linkBtn {{ background: transparent; border: none; color: {c['accent']}; padding: 2px 0px;
                      min-height: 0px; font-size: 10.5pt; }}
QPushButton#linkBtn:hover {{ background: transparent; text-decoration: underline; }}

/* ---- חלון ההגדרות (כמו בדמו) ---- */
QFrame#settingsPanel {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QLabel#setTitle {{ font-size: 13.5pt; font-weight: 700; }}
QLabel#setLabel {{ font-size: 11pt; font-weight: 600; }}
QFrame#themeCard {{ border: 2px solid {c['border']}; border-radius: 12px; background: transparent; }}
QFrame#themeCard[selected="true"] {{ border-color: {c['accent']}; }}
QLabel#themeName {{ font-size: 10.5pt; }}
QLabel#themeName[selected="true"] {{ font-weight: 600; }}

/* ---- בנק הסקטארים: רשימת הקבוצות ---- */
QPushButton#bankGroup {{ border: none; border-radius: 10px; background: transparent; min-height: 0px;
                        padding: 0px; text-align: right; }}
QPushButton#bankGroup:hover {{ background: {c['surface2']}; }}
QPushButton#bankGroup:checked {{ background: {c['accent_soft']}; }}
QLabel#bankGroupName {{ font-size: 10.5pt; }}
QLabel#bankGroupName[selected="true"] {{ color: {c['accent']}; font-weight: 600; }}
QLabel#countBadge {{ color: {c['muted']}; background: {c['surface2']}; border-radius: 9px;
                    padding: 1px 8px; font-size: 9pt; }}

/* ---- תצוגה מקדימה של קובץ (Scatter) ---- */
QPlainTextEdit#preview {{ font-family: Consolas, 'Cascadia Mono', monospace; }}

/* ---- סייר קבצים: נתיב שאפשר ללחוץ על כל חלק בו ---- */
QFrame#crumbs {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QPushButton#crumb {{ border: none; background: transparent; padding: 3px 8px; border-radius: 7px; min-height: 0px; }}
QPushButton#crumb:hover {{ background: {c['surface2']}; }}
QLabel#crumbSep {{ color: {c['muted']}; }}

/* ---- תוויות מיוחדות (לפי objectName) ---- */
QLabel#noteInfo {{ background: {c['accent_soft']}; border: 1px solid {c['accent']}; border-radius: 10px; padding: 10px; }}
QLabel#hint {{ color: {c['muted']}; }}
QLabel#hintWarn {{ color: {c['warn']}; }}
"""


def apply_theme(dark: bool) -> None:
    global _current_dark
    app = QApplication.instance()
    if app is None:
        return
    _current_dark = dark
    c = colors(dark)
    app.setStyle("Fusion")
    app.setPalette(_palette(c))
    base = app.font().pointSizeF()
    if base <= 0:
        base = 9.0
    app.setStyleSheet(_qss(c, round(base * BUTTON_SCALE, 1)))
