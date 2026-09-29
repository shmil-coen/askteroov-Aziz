# -*- coding: utf-8 -*-
"""
תיעוד/audit-trail לפעולת רוטינג — סכימת backups/ + metadata/ בדיוק כמו
שהוגדר במסמכי הארכיטקטורה (רוטינג אוטומטי במצב ברום.txt / דרך פאסטבוט.txt):

  <job_dir>/
    backups/original_boot.img  (או original_init_boot.img)
             original_vbmeta.img   (אם קיימת מחיצת vbmeta עצמאית)
             original_misc.img
    metadata/gpt_before.json
             device_info.json
             hashes.json
             operation.json   — כולל write_backend: "brom" | "fastboot"
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

from .config import WORKSPACE_DIR

ROOT_JOBS_DIR = WORKSPACE_DIR / "root_jobs"


def _json_default(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


def new_job_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = ROOT_JOBS_DIR / stamp
    (job_dir / "backups").mkdir(parents=True, exist_ok=True)
    (job_dir / "metadata").mkdir(parents=True, exist_ok=True)
    return job_dir


def write_json(job_dir: Path, name: str, data) -> Path:
    path = job_dir / "metadata" / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default),
                    encoding="utf-8")
    return path


def write_operation_json(job_dir: Path, *, architecture: str, write_backend: str,
                         target_partition: str, slot: str, magisk_version: str,
                         vbmeta_patched: bool, success: bool, notes: str = "") -> Path:
    data = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "architecture": architecture,          # "brom" / "fastboot_backend"
        "write_backend": write_backend,        # "brom" | "fastboot"
        "target_partition": target_partition,
        "slot": slot,
        "magisk_version": magisk_version,
        "vbmeta_patched": vbmeta_patched,
        "success": success,
        "notes": notes,
    }
    return write_json(job_dir, "operation.json", data)
