# -*- coding: utf-8 -*-
"""
ניטור פורטים בזמן אמת: מזהה מכשירי MediaTek לפי VID/PID.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtSerialPort import QSerialPortInfo

from .logs import log

# VID/PID של MediaTek הידועים
MTK_VIDS = {0x0E8D}

# PID מוכרים: BROM/Preloader = 0x0003, 0x2000/0x2001 (Preloader)
MTK_MODES = {
    0x0003: "BROM / Preloader",
    0x2000: "Preloader",
    0x2001: "Preloader",
}

# פורט BROM/Preloader אמיתי של מכשיר — ה-PID האלה בלבד. שבבי Bluetooth/Wi-Fi
# מובנים של MediaTek בלוח המחשב מדווחים גם הם VID 0E8D, אבל ב-PID אחר
# (למשל 0x7961) — בלי ההבחנה הזאת התוכנה "מזהה מכשיר" שלא חובר.
PRELOADER_PIDS = {0x0003, 0x2000, 0x2001}


def is_preloader_port(vid: int, pid: int) -> bool:
    """האם זה פורט של מכשיר במצב BROM/Preloader (ולא רכיב מובנה במחשב)."""
    return vid in MTK_VIDS and (pid & 0xFFFF) in PRELOADER_PIDS


@dataclass
class PortInfo:
    port_name: str
    description: str
    vid: int
    pid: int
    mode: str

    @property
    def is_mtk(self) -> bool:
        return self.vid in MTK_VIDS


def scan_ports() -> list[PortInfo]:
    """סריקת כל פורטים עם זיהוי מצב MTK."""
    result = []
    for info in QSerialPortInfo.availablePorts():
        vid = info.vendorIdentifier() or 0
        pid = info.productIdentifier() or 0
        vid16 = vid & 0xFFFF
        pid16 = pid & 0xFFFF
        mode = MTK_MODES.get(pid16, "—" if vid16 not in MTK_VIDS else "MTK (לא מזוהה)")
        result.append(PortInfo(
            port_name=info.portName(),
            description=info.description() or "?",
            vid=vid16,
            pid=pid16,
            mode=mode if vid16 in MTK_VIDS else ("ADB/Fastboot" if is_adb_or_fastboot(vid16, pid16) else "—"),
        ))
    return result


def is_adb_or_fastboot(vid: int, pid: int) -> bool:
    """זיהוי בסיסי של ADB (18D1:4EE7/4EE8) ו-Fastboot (18D1:D00D)."""
    return vid == 0x18D1 and pid in (0x4EE7, 0x4EE8, 0xD00D)


class PortMonitor:
    """מנטר חיבורי פורטים ברקע ומודיע על שינויים."""

    def __init__(self, interval: float = 1.5):
        self.interval = interval
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last: list[PortInfo] = []
        self.on_change: Optional[Callable[[list[PortInfo]], None]] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        def run():
            while not self._stop.is_set():
                ports = scan_ports()
                if self._signature(ports) != self._signature(self._last):
                    self._last = ports
                    if self.on_change:
                        try:
                            self.on_change(ports)
                        except Exception as e:
                            log.error(f"שגיאת ניטור: {e}")
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    @staticmethod
    def _signature(ports: list[PortInfo]) -> tuple:
        return tuple(sorted((p.port_name, p.vid, p.pid) for p in ports))
