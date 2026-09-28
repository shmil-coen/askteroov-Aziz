# -*- coding: utf-8 -*-
"""רץ בדיקות פשוט (ללא pytest) — מריץ כל פונקציה שמתחילה ב-test_."""
from __future__ import annotations

import importlib.util
import inspect
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


class _MonkeyPatch:
    """תשלום מינימלי ל-monkeypatch של pytest (setattr + שחזור)."""

    def __init__(self):
        self._undo: list[tuple] = []

    def setattr(self, obj, name, value):
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo.clear()


def load_test_module():
    spec = importlib.util.spec_from_file_location("test_core", HERE / "test_core.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    mod = load_test_module()
    tests = [
        (name, fn) for name, fn in inspect.getmembers(mod, inspect.isfunction)
        if name.startswith("test_")
    ]
    tmp = Path(tempfile.mkdtemp(prefix="askateroov_tests_"))
    passed = 0
    failed: list[str] = []
    try:
        for name, fn in tests:
            mp = None
            try:
                params = inspect.signature(fn).parameters
                kwargs = {}
                if "tmp_path" in params:
                    kwargs["tmp_path"] = tmp / name
                    kwargs["tmp_path"].mkdir(exist_ok=True)
                if "monkeypatch" in params:
                    mp = _MonkeyPatch()
                    kwargs["monkeypatch"] = mp
                fn(**kwargs)
                print(f"  PASS  {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {name}: {type(e).__name__}: {e}")
                failed.append(name)
            finally:
                if mp is not None:
                    mp.undo()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{passed} עברו, {len(failed)} נכשלו")
    if failed:
        print("נכשלו:", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
