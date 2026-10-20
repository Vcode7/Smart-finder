"""
app/library/paths.py
~~~~~~~~~~~~~~~~~~~~
Path helpers for libraries: relative POSIX paths in the index (so a library survives
being moved or getting a new drive letter), Windows long-path handling, and the
hidden attribute for .smartfind folders.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

INDEX_DIRNAME = ".smartfind"

# Never descend into these (in addition to hidden/system folders).
DEFAULT_IGNORED_DIRS = {
    INDEX_DIRNAME, ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
    "$RECYCLE.BIN", "System Volume Information", ".Trash", ".Trashes", ".cache",
}
DEFAULT_IGNORED_FILES = ("~$*", "*.tmp", "*.temp", "*.part", "*.crdownload", "*.partial",
                         "*.smartfind-part", "Thumbs.db", "desktop.ini", ".DS_Store")

# Web-viewer graphics (flipbook exports, saved web pages): buttons, arrows and sprites
# that only add junk descriptions and image vectors to results.
_ASSET_DIR_NAMES = {"icon", "icons", "sprites", "favicon", "emoji", "emojis"}
_ICON_DIR = re.compile(r"(?:.*[_\-. ])?icons?")      # mb_icon, app-icons
_CAMEL_ICON_DIR = re.compile(r"[a-z0-9]+Icons?")     # phoneIcon
# Page thumbnails beside the full-size pages (files/thumb next to files/large)
_THUMB_DIR_NAMES = {"thumb", "thumbs", "thumbnail", "thumbnails"}
_FULL_SIZE_DIR_NAMES = {"large", "big", "full", "original", "originals"}


def to_rel(root: Path, path: Path) -> str:
    """Path relative to root, always with forward slashes."""
    return PurePosixPath(Path(path).resolve().relative_to(Path(root).resolve()).as_posix()).as_posix()


def from_rel(root: Path, rel: str) -> Path:
    return Path(root).joinpath(*PurePosixPath(rel).parts)


def long_path(p: Path) -> str:
    """Windows: prefix very long absolute paths with \\\\?\\ so file APIs accept them."""
    s = str(p)
    if sys.platform == "win32" and len(s) > 240 and not s.startswith("\\\\?\\"):
        s = "\\\\?\\" + str(Path(s).resolve())
    return s


def is_asset_dir(name: str, siblings: Optional[Iterable[str]] = None) -> bool:
    """
    A folder of web-viewer graphics (icon folders), or page thumbnails that duplicate
    a full-size sibling folder. `siblings` are the names of the folder's neighbours.
    """
    lower = name.lower()
    if lower in _ASSET_DIR_NAMES or _ICON_DIR.fullmatch(lower) or _CAMEL_ICON_DIR.fullmatch(name):
        return True
    if lower in _THUMB_DIR_NAMES and siblings is not None:
        return any(s.lower() in _FULL_SIZE_DIR_NAMES for s in siblings)
    return False


def is_hidden(entry: os.DirEntry) -> bool:
    if entry.name.startswith("."):
        return True
    if sys.platform == "win32":
        try:
            attrs = entry.stat(follow_symlinks=False).st_file_attributes
            return bool(attrs & (0x2 | 0x4))  # HIDDEN | SYSTEM
        except (OSError, AttributeError):
            return False
    return False


def hide_directory(path: Path) -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2)  # FILE_ATTRIBUTE_HIDDEN
        except Exception:
            pass


def is_network_path(path: Path) -> bool:
    """UNC paths and mapped network drives (file-system events are unreliable there)."""
    s = str(path)
    if s.startswith("\\\\"):
        return True
    if sys.platform == "win32" and len(s) >= 2 and s[1] == ":":
        try:
            import ctypes
            DRIVE_REMOTE = 4
            return ctypes.windll.kernel32.GetDriveTypeW(f"{s[0]}:\\") == DRIVE_REMOTE
        except Exception:
            return False
    return False
