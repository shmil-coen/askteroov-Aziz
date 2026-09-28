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


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .core.logs import log
    from .gui.main_window import MainWindow

    _install_crash_logging(log)

    app = QApplication(sys.argv)
    app.setApplicationName("Askateroov")
    app.setQuitOnLastWindowClosed(True)
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
