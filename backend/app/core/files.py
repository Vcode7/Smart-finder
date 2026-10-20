"""
app/core/files.py
~~~~~~~~~~~~~~~~~
Filename sanitization and path-containment helpers.

Client-supplied names (upload filenames, relative paths) must never be joined to
a storage directory without passing through these helpers: Starlette hands the
raw multipart filename through unchanged, so "../../x.py" or "C:/x.bat" would
otherwise escape the target folder.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Union

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_MAX_NAME_LENGTH = 200


def sanitize_filename(name: str, default: str = "file") -> str:
    """Reduce a client-supplied name to a safe single path component."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = unicodedata.normalize("NFC", base)
    base = _ILLEGAL_CHARS.sub("_", base).strip().rstrip(". ")
    if not base or set(base) <= {"."}:
        base = default

    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    if stem.upper() in _WINDOWS_RESERVED or base.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"

    if len(stem) + len(ext) + 1 > _MAX_NAME_LENGTH:
        keep = max(1, _MAX_NAME_LENGTH - len(ext) - 1)
        stem = stem[:keep]
    return f"{stem}.{ext}" if ext else stem


def sanitize_relative_path(rel: str) -> Path:
    """Sanitize every component of a client-supplied relative path ("a/b/c.txt")."""
    parts = [p for p in re.split(r"[\\/]+", rel or "") if p not in ("", ".", "..")]
    clean = [sanitize_filename(p) for p in parts]
    return Path(*clean) if clean else Path(sanitize_filename(""))


def is_within(path: Union[str, Path], root: Union[str, Path]) -> bool:
    """True when `path` resolves to a location inside `root` (or is `root`)."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


def safe_join(root: Union[str, Path], *parts: Union[str, Path]) -> Path:
    """Join parts onto root and refuse any result that escapes root."""
    root_path = Path(root).resolve()
    candidate = root_path.joinpath(*parts).resolve()
    if not is_within(candidate, root_path):
        raise ValueError(f"Path escapes its root directory: {candidate}")
    return candidate


def unique_path(directory: Path, filename: str) -> Path:
    """Return directory/filename, adding ' (1)', ' (2)', ... if that name is taken."""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    counter = 1
    while True:
        name = f"{stem} ({counter}).{ext}" if ext else f"{stem} ({counter})"
        candidate = directory / name
        if not candidate.exists():
            return candidate
        counter += 1
