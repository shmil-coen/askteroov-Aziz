# -*- coding: utf-8 -*-
"""
מנהל עבודות — גרסת מרכז שליטה.

עקרונות:
  * כל פעולה נבנית קודם כ"תוכנית" (Job) שלא רצה — כדי שהממשק יציג
    למשתמש את הפקודות המדויקות ויבקש אישור מפורש.
  * רק אחרי אישור: job_manager.submit(job).
  * פעולת mtk אחת בכל רגע. עבודה מרובת שלבים (גיבוי ← צריבה, מחיקת כמה
    מחיצות, שאיבת כמה מחיצות) רצה כרצף — ונעצרת בשלב הראשון שנכשל.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .checksums import file_checksum, write_checksum_file
from .config import BACKUPS_DIR, CHECKSUM_ALGO, ensure_unique_path
from .logs import log
from .mtk_bridge import MtkCommand, MtkCommands
from .safety import get_partition_warning, validate_image_size


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ---------------------------------------------------------------------- מבנה עבודה


@dataclass
class Step:
    """שלב אחד: פקודת mtk + פעולה אופציונלית אחרי הצלחה (למשל checksum)."""
    name: str
    command: MtkCommand
    after: Optional[Callable[[], None]] = None


@dataclass
class Job:
    """תוכנית עבודה: רשימת שלבים שרצים ברצף, רק אחרי אישור."""
    name: str
    steps: list[Step]
    on_done: Optional[Callable[[bool], None]] = None
    on_output: Optional[Callable[[str], None]] = None   # פלט נוסף (למשל איסוף טקסט GPT)
    notes: list[str] = field(default_factory=list)      # הערות לחלון האישור
    danger: bool = False                                # פעולה מסוכנת (צריבה/מחיקה/seccfg)
    retries: int = 0                                    # ניסיונות חוזרים בכשל (0 = בלי)
    retry_delay: float = 2.0                            # השהיה בין ניסיונות (שניות)
    reconnect_delay: float = 2.0                        # השהיה קצרה לפני ניסיון אחרי כשל חיבור
    # בעבודות עם ניסיונות חוזרים (שאיבה): כל ניסיון ממתין עד 45 שניות לחיבור המכשיר
    # ("Waiting for PreLoader VCOM"), ואם לא התחבר — נחשב "כשל בחיבור" ועובר לניסיון הבא
    connect_timeout: float = 45.0
    connection_failed: bool = False                     # הכשל הסופי היה כשל חיבור (לחלון הסיום)
    no_fastboot_device: bool = False                    # לא נמצא מכשיר במצב Fastboot (לחלון הסיום)
    status: str = "ממתין לאישור"
    ok: Optional[bool] = None
    _cancel: threading.Event = field(default_factory=threading.Event)
    _current_cmd: Optional[MtkCommand] = None

    def describe(self) -> list[str]:
        return [f"{i + 1}. {s.name}:  {s.command.describe()}"
                for i, s in enumerate(self.steps)]

    def cancel(self):
        self._cancel.set()
        if self._current_cmd is not None:
            self._current_cmd.stop()
        self.status = "מבוטל"


class JobManager:
    """מריץ עבודה אחת בכל רגע. ה-UI נרשם ל-hooks (נקראים מ-thread רקע)."""

    def __init__(self):
        self.current: Optional[Job] = None
        self.last: Optional[Job] = None
        self._lock = threading.Lock()
        # hooks ל-UI — חייבים להיות thread-safe (למשל emit של Qt Signal)
        self.on_progress: Optional[Callable[[float, str], None]] = None
        self.on_state: Optional[Callable[[str], None]] = None
        self.on_finished: Optional[Callable[[str, bool], None]] = None
        # נקרא כשכשל דורש חיבור מחדש של המכשיר (שם שלב, שניות המתנה)
        self.on_reconnect: Optional[Callable[[str, float], None]] = None

    @property
    def busy(self) -> bool:
        return self.current is not None

    def submit(self, job: Job) -> Job:
        with self._lock:
            if self.current is not None:
                raise RuntimeError("יש פעולה פעילה — המתן לסיומה או בטל אותה")
            self.current = job
        job.status = "רץ"
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def cancel_current(self) -> bool:
        job = self.current
        if job is None:
            return False
        log.warn(f"מבטל: {job.name}")
        job.cancel()
        return True

    # ------------------------------------------------------------------
    def _emit_state(self, text: str):
        if self.on_state:
            try:
                self.on_state(text)
            except Exception:
                pass

    def _wait_cancellable(self, job: "Job", seconds: float):
        """המתנה שנפסקת מיד אם המשתמש ביטל."""
        job._cancel.wait(timeout=seconds)

    def _run(self, job: Job):
        ok = True
        total = len(job.steps)
        log.info(f"▶ התחלה: {job.name} ({total} שלבים)")
        try:
            for i, step in enumerate(job.steps):
                if job._cancel.is_set():
                    ok = False
                    break
                self._emit_state(f"{job.name} — שלב {i + 1}/{total}: {step.name}")
                if self.on_progress:
                    self.on_progress(0.0, step.name)

                def out(line: str, _job=job):
                    log.raw(line)
                    if _job.on_output:
                        try:
                            _job.on_output(line)
                        except Exception:
                            pass

                def prog(pct: float, suffix: str, _i=i):
                    if self.on_progress:
                        self.on_progress(pct, f"[{_i + 1}/{total}] {suffix}")

                step_ok = False
                last_reason = ""
                attempts = job.retries + 1
                for attempt in range(1, attempts + 1):
                    if job._cancel.is_set():
                        break
                    if attempt > 1:
                        log.warn(f"ניסיון חוזר {attempt}/{attempts} עבור '{step.name}'…")
                        self._emit_state(
                            f"{job.name} — שלב {i + 1}/{total}: {step.name} "
                            f"(ניסיון {attempt}/{attempts})")
                        if self.on_progress:
                            self.on_progress(0.0, f"ניסיון {attempt}/{attempts}: {step.name}")
                        step.command.reset()          # פקודה חדשה לכל ניסיון
                    if job.retries > 0 and hasattr(step.command, "connect_timeout"):
                        step.command.connect_timeout = job.connect_timeout
                    job._current_cmd = step.command
                    rc = step.command.run_blocking(out, prog)
                    job._current_cmd = None
                    if job._cancel.is_set():
                        break
                    if rc != 0:
                        last_reason = f"קוד {rc}"
                        if getattr(step.command, "no_device", False):
                            last_reason = "לא נמצא מכשיר במצב Fastboot"
                            break   # אין טעם לנסות שוב — כבר חיכינו למכשיר
                    else:
                        if step.after:
                            try:
                                step.after()
                            except Exception as e:  # כשל בבדיקה שאחרי = כשל שלב
                                last_reason = str(e)
                                log.error(f"השלב '{step.name}' נכשל בבדיקה: {e}")
                                break  # קובץ פגום — אין טעם לחזור
                        step_ok = True
                        break
                    if attempt < attempts and not job._cancel.is_set():
                        need_rc = getattr(step.command, "needs_reconnect", False)
                        delay = job.reconnect_delay if need_rc else job.retry_delay
                        if need_rc:
                            log.warn(f"החיבור למכשיר נכשל — ניסיון {attempt + 1}/{attempts}: "
                                     f"נתק וחבר את המכשיר במצב BROM "
                                     f"(ממתין לחיבור עד {int(job.connect_timeout)} שניות)…")
                            if self.on_reconnect:
                                try:
                                    self.on_reconnect(step.name, job.connect_timeout)
                                except Exception:
                                    pass
                        else:
                            log.warn(f"השלב '{step.name}' נכשל ({last_reason}) — "
                                     "ממתין ומנסה שוב")
                        self._wait_cancellable(job, delay)
                if not step_ok:
                    job.connection_failed = bool(
                        getattr(step.command, "needs_reconnect", False))
                    job.no_fastboot_device = bool(getattr(step.command, "no_device", False))
                    if not job._cancel.is_set():
                        log.error(f"השלב '{step.name}' נכשל ({last_reason}) — הרצף נעצר")
                    ok = False
                    break
        finally:
            job.ok = ok
            job.status = "הסתיים" if ok else ("מבוטל" if job._cancel.is_set() else "נכשל")
            with self._lock:
                self.last = job
                self.current = None
            (log.success if ok else log.error)(f"■ {job.name}: {job.status}")
            if self.on_progress:
                self.on_progress(100.0 if ok else 0.0, job.status)
            self._emit_state(f"{job.name}: {job.status}")
            if job.on_done:
                try:
                    job.on_done(ok)
                except Exception as e:
                    log.error(f"שגיאה ב-callback: {e}")
            if self.on_finished:
                try:
                    self.on_finished(job.name, ok)
                except Exception:
                    pass


job_manager = JobManager()


# ---------------------------------------------------------------------- עזרים


def _checksum_after(path: Path, label: str) -> Callable[[], None]:
    """בדיקה שאחרי שאיבה: הקובץ קיים, לא ריק, ונכתב לו SHA256."""
    def after():
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"הקובץ לא נוצר או ריק: {path}")
        digest = file_checksum(path, CHECKSUM_ALGO)
        write_checksum_file(path, CHECKSUM_ALGO)
        log.success(f"{label} → {path.name}  SHA256: {digest}")
    return after


# ---------------------------------------------------------------------- תוכניות


def plan_simple(name: str, command: MtkCommand,
                on_done: Optional[Callable[[bool], None]] = None,
                on_output: Optional[Callable[[str], None]] = None) -> Job:
    return Job(name, [Step(name, command)], on_done=on_done, on_output=on_output)


def plan_read_partitions(partitions: list[str], out_dir: Path,
                         on_done: Optional[Callable[[bool], None]] = None,
                         **kw) -> Job:
    """שאיבת מחיצה אחת או כמה (ברצף) + SHA256 לכל קובץ."""
    stamp = _stamp()
    out_dir.mkdir(parents=True, exist_ok=True)
    steps = []
    for p in partitions:
        out_path = ensure_unique_path(out_dir, f"{p}_{stamp}", ".img")
        steps.append(Step(f"שאיבת {p}",
                          MtkCommands.read_partition(p, out_path, **kw),
                          _checksum_after(out_path, f"נשאב {p}")))
    title = f"שאיבת {partitions[0]}" if len(partitions) == 1 else f"שאיבת {len(partitions)} מחיצות"
    job = Job(title, steps, on_done=on_done, retries=2)
    job.notes.append(f"יעד: {out_dir}")
    job.notes.append("אם שלב נכשל — ינוסה שוב אוטומטית (עד 3 פעמים).")
    return job


def plan_read_preloader(out_dir: Path,
                        on_done: Optional[Callable[[bool], None]] = None, **kw) -> Job:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = ensure_unique_path(out_dir, f"preloader_{_stamp()}", ".bin")
    job = Job("שאיבת Preloader",
              [Step("שאיבת Preloader", MtkCommands.read_preloader(out_path, **kw),
                    _checksum_after(out_path, "Preloader נשאב"))],
              on_done=on_done, retries=2)
    job.notes.append(f"יעד: {out_path}")
    job.notes.append("אם השאיבה נכשלת — תנוסה שוב אוטומטית (עד 3 פעמים).")
    return job


def plan_read_all(out_root: Path,
                  on_done: Optional[Callable[[bool], None]] = None, **kw) -> Job:
    """שאיבת כל המחיצות לתיקייה חדשה עם חותמת זמן + SHA256 לכל קובץ."""
    out_dir = out_root / f"full_{_stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    def after():
        files = [f for f in out_dir.iterdir() if f.is_file() and f.suffix != f".{CHECKSUM_ALGO}"]
        if not files:
            raise RuntimeError("לא נוצרו קבצים בתיקיית היעד")
        for f in files:
            write_checksum_file(f, CHECKSUM_ALGO)
        log.success(f"נשאבו {len(files)} קבצים, לכל אחד נכתב SHA256")

    job = Job("שאיבת כל המחיצות",
              [Step("שאיבת כל המחיצות", MtkCommands.read_all(out_dir, **kw), after)],
              on_done=on_done, retries=2)
    job.notes.append(f"יעד: {out_dir}")
    job.notes.append("הפעולה עשויה להימשך זמן רב.")
    return job


def plan_write_partition(partition: str, image: Path, part_length: Optional[int],
                         backup_first: bool = True,
                         on_done: Optional[Callable[[bool], None]] = None,
                         **kw) -> Job:
    """
    צריבת מחיצה: אימות גודל ← (גיבוי + SHA256) ← צריבה.
    אם הגיבוי נכשל — הצריבה לא מתבצעת.
    :raises ValueError: אם ה-Image גדול מהמחיצה.
    """
    notes = []
    warning = get_partition_warning(partition)
    if warning:
        notes.append(f"⚠️ מחיצה רגישה: {warning}")
    if part_length is not None:
        ok, msg = validate_image_size(image, part_length)
        if not ok:
            raise ValueError(msg)
        notes.append(msg)
    else:
        notes.append("⚠️ גודל המחיצה לא ידוע — אין אימות גודל")

    steps = []
    if backup_first:
        backup_path = ensure_unique_path(BACKUPS_DIR, f"{partition}_{_stamp()}", ".img")
        steps.append(Step(f"גיבוי {partition}",
                          MtkCommands.read_partition(partition, backup_path, **kw),
                          _checksum_after(backup_path, f"גיבוי {partition}")))
        notes.append(f"גיבוי אל: {backup_path}")
    else:
        notes.append("⚠️ ללא גיבוי לפני צריבה!")
    steps.append(Step(f"צריבת {partition}", MtkCommands.write_partition(partition, image, **kw)))
    job = Job(f"צריבת {partition}", steps, on_done=on_done, danger=True)
    job.notes = notes
    return job


def plan_erase_partitions(partitions: list[str], title: str = "מחיקת מחיצות",
                          on_done: Optional[Callable[[bool], None]] = None, **kw) -> Job:
    """מחיקה ברצף — נעצר בכשל הראשון ומדווח תוצאה אמיתית."""
    steps = [Step(f"מחיקת {p}", MtkCommands.erase_partition(p, **kw)) for p in partitions]
    return Job(title, steps, on_done=on_done, danger=True)



# ---------------------------------------------------------------------- Fastboot


def plan_fastboot_simple(name: str, command, retries: int = 1,
                         on_done=None, on_output=None) -> Job:
    """זיהוי / getvar / reboot — קריאה בלבד, עם ניסיון חוזר קל."""
    return Job(name, [Step(name, command)], on_done=on_done,
               on_output=on_output, retries=retries)


def plan_fastboot_flash(partition: str, image: "Path", on_done=None, **kw) -> Job:
    """צריבת מחיצה ב-Fastboot — פעולה מסוכנת, ללא ניסיון חוזר אוטומטי."""
    from .fastboot_bridge import FastbootCommands
    job = Job(f"Fastboot: צריבת {partition}",
              [Step(f"flash {partition}", FastbootCommands.flash(partition, image))],
              on_done=on_done, danger=True)
    job.notes.append("צריבה דרך fastboot — דורשת בוטלאודר פתוח.")
    job.notes.append("⚠️ אם המחיצה שגויה המכשיר עלול לא לעלות. ודא שם מחיצה וקובץ נכונים.")
    return job


def plan_fastboot_erase(partition: str, on_done=None, **kw) -> Job:
    """מחיקת מחיצה ב-Fastboot — פעולה מסוכנת, ללא ניסיון חוזר אוטומטי."""
    from .fastboot_bridge import FastbootCommands
    job = Job(f"Fastboot: מחיקת {partition}",
              [Step(f"erase {partition}", FastbootCommands.erase(partition))],
              on_done=on_done, danger=True)
    job.notes.append("⚠️ מחיקת המחיצה — הנתונים בה יאבדו.")
    return job
