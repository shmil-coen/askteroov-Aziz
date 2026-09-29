# -*- coding: utf-8 -*-
"""
הסקטארוב — מרכז שליטה (ללא פעולות אוטומטיות).
כל פעולה מול המכשיר מוצגת בחלון 'אישור פעולה' ורצה רק אחרי אישור המשתמש.
"""
from __future__ import annotations

import faulthandler
import sys
import traceback


def _install_crash_logging(log) -> None:
    """לוכד קריסות לא צפויות אל קובץ הלוג (במקום שייעלמו ל-stderr של הקונסול).

    - faulthandler: קריסות ברמת C (segfault) נכתבות לקובץ crash_*.
    - sys.excepthook: חריגות פייתון שלא נתפסו (למשל בתוך slot של Qt) נרשמות ללוג.
    """
    try:
        crash_path = log.log_file.with_name("crash_" + log.log_file.name)
        _fh = open(crash_path, "w", encoding="utf-8")
        faulthandler.enable(file=_fh)
    except Exception:
        pass

    _orig = sys.excepthook

    def _hook(exc_type, exc, tb):
        try:
            log.error("קריסה/חריגה לא צפויה:\n"
                      + "".join(traceback.format_exception(exc_type, exc, tb)))
            log.flush()
        except Exception:
            pass
        try:
            _orig(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = _hook


def _set_windows_dpi_awareness() -> None:
    """מצהיר ל-Windows שהתהליך מודע בעצמו על הגדלת תצוגה (DPI) של כל מסך —
    לפני שנוצר חלון ראשון כלשהו.  בלעדי זה, במערכות עם הגדלת תצוגה
    (נפוץ במסכי מחשב נייד), Windows עלול למתוח (bitmap scaling) את חלון
    האפליקציה מבלי לשאול אותה — ואז חלק מהחלון נשפך מעבר לגבול המסך ונחתך
    (התסמן: צד ימין חתוך בגרסה הארוזה).

    זה בא כביטוי נוסף למניפסט שיש ב-Askateroov.spec (dpiAwareness) —
    אם המניפסט כבר הגדיר את זה, הקריאה כאן תיכשל בשקט ולא מזיקה.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def _set_windows_app_id() -> None:
    """מזהה יישום ל-Windows — כדי ששורת המשימות תציג את סמל התוכנה
    (ולא תקבץ את החלון תחת הסמל של פייתון / סמל ריק)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Askateroov.App")
    except Exception:
        pass


def _install_app_icon(app) -> None:
    """סמל התוכנה לכל החלונות (שורת המשימות, פינת החלון) — מתוך tools\\app_icon.ico."""
    from pathlib import Path
    from PySide6.QtGui import QIcon
    from .core import config
    for cand in (config.PROJECT_ROOT / "tools" / "app_icon.ico",
                 Path(getattr(sys, "_MEIPASS", "")) / "tools" / "app_icon.ico"):
        if cand.is_file():
            app.setWindowIcon(QIcon(str(cand)))
            return


def _install_qt_hebrew(app) -> None:
    """תרגום עברי לטקסטים המובנים של Qt ('הצג פרטים...', כן/לא/ביטול,
    חלונות בחירת קבצים, תפריט העתק/הדבק) — בלעדיו הם מוצגים באנגלית."""
    from pathlib import Path
    from PySide6.QtCore import QLibraryInfo, QTranslator
    tr = QTranslator(app)
    for folder in (QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
                   str(Path(getattr(sys, "_MEIPASS", "")) / "PySide6" / "translations")):
        if folder and tr.load("qtbase_he", folder):
            app.installTranslator(tr)
            return


def main() -> int:
    _set_windows_dpi_awareness()   # לפני יצירת QApplication/כל חלון
    _set_windows_app_id()          # לפני יצירת חלון — סמל נכון בשורת המשימות

    from PySide6.QtWidgets import QApplication

    from .core.logs import log
    from .gui.main_window import MainWindow

    _install_crash_logging(log)

    app = QApplication(sys.argv)
    app.setApplicationName("Askateroov")
    app.setQuitOnLastWindowClosed(True)
    _install_app_icon(app)
    _install_qt_hebrew(app)
    # כיוון מימין לשמאל לכל היישום – גם לטקסט של כפתורים ודיאלוגים
    from PySide6.QtCore import Qt
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    from .gui import theme
    theme.apply_theme(theme.load_dark())

    log.info("הפעלת הסקטארוב (מרכז שליטה)")
    win = MainWindow()   # הלוגו מוצג במרכז החלון (נבנה בתוך MainWindow)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
