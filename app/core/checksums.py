# -*- coding: utf-8 -*-
"""
חישובי אימות נתונים: גדלים, MD5/SHA256, והשוואות.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def file_md5(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def file_checksum(path: Path, algo: str = "sha256") -> str:
    algo = algo.lower().replace("-", "")
    if algo == "sha256":
        return file_sha256(path)
    if algo == "md5":
        return file_md5(path)
    raise ValueError(f"אלגוריתם לא נתמך: {algo}")


def write_checksum_file(path: Path, algo: str = "sha256") -> Path:
    """כותב קובץ .sha256 / .md5 לצד הקובץ המקורי."""
    digest = file_checksum(path, algo)
    out = path.with_suffix(path.suffix + f".{algo}")
    out.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return out


def verify_checksum_file(path: Path, expected: str, algo: str = "sha256") -> bool:
    return file_checksum(path, algo).lower() == expected.lower()


def format_size(n: int) -> str:
    """גודל קריא לאדם."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"
