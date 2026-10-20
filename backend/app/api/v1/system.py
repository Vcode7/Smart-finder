"""
Choosing folders and files on the machine running the backend (admin only).

* pick-folder / pick-files open the native Windows dialog on this PC — useful when the
  browser runs on the same machine.
* /fs lists folders (and optionally files) for the in-app browser, which works from
  any device on the network.
"""
import asyncio
import os
import string
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import require_admin
from app.library.manager import get_library_manager
from app.library.paths import INDEX_DIRNAME, is_hidden, long_path
from app.library.sources import file_kind

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(require_admin)])

MAX_ENTRIES = 5000
_dialog_lock = threading.Lock()


def _run_dialog(kind: str) -> Any:
    """Runs a Tk file dialog on its own thread (Tk objects must stay on one thread)."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()
        root.update()
        if kind == "folder":
            return filedialog.askdirectory(parent=root, mustexist=True, title="Choose a folder to index") or None
        return list(filedialog.askopenfilenames(parent=root, title="Choose files to index") or [])
    finally:
        root.destroy()


def _dialog_available() -> bool:
    """A Tk dialog needs a desktop session; a Linux service (systemd) has none."""
    if sys.platform != "win32" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return False
    return True


async def _dialog(kind: str) -> Any:
    if not _dialog_available():
        raise HTTPException(status_code=501, detail="No desktop file dialog is available on the server")
    if not _dialog_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A file dialog is already open on the server")
    try:
        return await asyncio.to_thread(_run_dialog, kind)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not open the file dialog: {e}")
    finally:
        _dialog_lock.release()


@router.post("/pick-folder")
async def pick_folder():
    path = await _dialog("folder")
    return {"path": str(Path(path)) if path else None}


@router.post("/pick-files")
async def pick_files():
    paths = await _dialog("files")
    return {"paths": [str(Path(p)) for p in paths]}


def _roots() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if sys.platform == "win32":
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                out.append({"name": drive, "path": drive, "type": "drive"})
    else:
        out.append({"name": "/", "path": "/", "type": "drive"})
    home = Path.home()
    for label in ("Desktop", "Documents", "Pictures", "Videos", "Music", "Downloads"):
        p = home / label
        if p.is_dir():
            out.append({"name": label, "path": str(p), "type": "shortcut"})
    out.append({"name": "Home", "path": str(home), "type": "shortcut"})
    return out


def _list_dir(path: Optional[str], include_files: bool) -> Dict[str, Any]:
    if not path:
        return {"path": None, "parent": None, "entries": _roots(), "truncated": False, "libraryId": None}
    try:
        p = Path(path).expanduser().resolve(strict=True)
    except OSError:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Not a folder")
    dirs: List[Dict[str, Any]] = []
    files: List[Dict[str, Any]] = []
    truncated = False
    try:
        with os.scandir(long_path(p)) as it:
            for entry in it:
                if entry.name == INDEX_DIRNAME or is_hidden(entry):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        dirs.append({"name": entry.name, "path": str(p / entry.name), "type": "dir"})
                    elif include_files and entry.is_file(follow_symlinks=False):
                        if len(files) >= MAX_ENTRIES:
                            truncated = True
                            continue
                        files.append({"name": entry.name, "path": str(p / entry.name), "type": "file",
                                      "size": entry.stat(follow_symlinks=False).st_size,
                                      "supported": file_kind(entry.name) != "unsupported"})
                except OSError:
                    continue
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access to this folder is denied")
    dirs.sort(key=lambda e: e["name"].casefold())
    files.sort(key=lambda e: e["name"].casefold())
    lib = next((l for l in get_library_manager().all() if l.root is not None and l.contains(p)), None)
    return {
        "path": str(p),
        "parent": str(p.parent) if p.parent != p else None,
        "entries": dirs[:MAX_ENTRIES] + files,
        "truncated": truncated or len(dirs) > MAX_ENTRIES,
        "libraryId": lib.id if lib else None,
    }


@router.get("/fs")
async def browse(path: Optional[str] = Query(None), files: bool = Query(False)):
    return await asyncio.to_thread(_list_dir, path, files)
