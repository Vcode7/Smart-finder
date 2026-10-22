"""
Add a folder as a library and index it from the command line, in the foreground, until
everything is done (text and pictures, then transcription, picture descriptions, sounds
and people). Meant for big folders on a server, run inside tmux or screen:

    venv/bin/python scripts/index_folder.py /data/archive
    venv/bin/python scripts/index_folder.py /data/archive --name "Archive" \\
        --admin-email ops@example.com --admin-name "Ops" --admin-password 'long-password'
    venv/bin/python scripts/index_folder.py /data/archive -e video           # everything but videos
    venv/bin/python scripts/index_folder.py /data/archive -i docs            # only documents
    venv/bin/python scripts/index_folder.py /data/archive -i docs,image      # documents and pictures
    venv/bin/python scripts/index_folder.py --admin-email ops@example.com   # account only

-i / --include and -e / --exclude take docs, image, video or audio (comma-separated or
repeated). The choice is saved on the library, so the backend keeps to it too (rescans,
new files); it shows as kind:... under the library's exclusions in the web app. Files of
an excluded kind that were already indexed are removed from the index (never from disk).
Running again without -i / -e keeps the saved choice; with them, it replaces it.

On a Linux install use `sudo smartfinder-ctl add-folder ...` instead: it runs this as the
Smart Finder account and stops / restarts the backend around it.

The backend must not be running: both would load the models onto the same GPU, and the
backend only picks up libraries added here when it starts. Start it afterwards and the
library is on the Libraries page, fully searchable.

Safe to stop (Ctrl-C) and run again: the folder's existing index is reused and only what
is not indexed yet is done. Files are indexed in place; nothing in the folder is changed
except the hidden .smartfind index folder.

--admin-email creates an administrator who can sign in to the web app (admins see every
library), or, for an existing account, makes it an administrator and sets the password.
The password comes from --admin-password, SMARTFINDER_ADMIN_PASSWORD, or a prompt.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import glob
import json
import os
import sys
import sysconfig
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("PYTHONUNBUFFERED", "1")

KIND_ARGS = {"docs": "document", "image": "image", "video": "video", "audio": "audio"}
KIND_ALIASES = {"doc": "docs", "document": "docs", "documents": "docs", "images": "image",
                "photo": "image", "photos": "image", "videos": "video"}
PROGRESS_INTERVAL_S = 60.0
POLL_S = 10.0
MIN_PASSWORD = 8


def _ensure_cuda_libs() -> None:
    """Linux: the CUDA libraries that come with the torch wheel must be on LD_LIBRARY_PATH
    before the process starts (smartfinder-ctl does the same for the backend)."""
    if sys.platform != "linux" or os.environ.get("_SMARTFINDER_REEXEC"):
        return
    current = os.environ.get("LD_LIBRARY_PATH", "")
    libs = sorted(glob.glob(os.path.join(sysconfig.get_paths()["purelib"], "nvidia", "*", "lib")))
    missing = [d for d in libs if d not in current.split(":")]
    if missing:
        os.environ["LD_LIBRARY_PATH"] = ":".join(missing + ([current] if current else []))
        os.environ["_SMARTFINDER_REEXEC"] = "1"
        os.execv(sys.executable, [sys.executable, *sys.argv])


def _raise_file_limit() -> None:
    """A shell (tmux) allows 1024 open files; the backend service gets 65536."""
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        want = 65536 if hard == resource.RLIM_INFINITY else min(65536, hard)
        if soft != resource.RLIM_INFINITY and soft < want:
            resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
    except Exception:
        pass   # Windows has no such limit


def _say(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _backend_running() -> bool:
    from app.core.config import settings
    host = "127.0.0.1" if settings.HOST in ("0.0.0.0", "::", "") else settings.HOST
    try:
        with urllib.request.urlopen(f"http://{host}:{settings.PORT}/health", timeout=3) as r:
            return json.loads(r.read().decode("utf-8")).get("status") == "healthy"
    except Exception:
        return False


def _check_owner() -> None:
    """Files created as another account (e.g. root) would lock the backend out."""
    from app.core.config import settings
    db = settings.resolved_db_path
    if not hasattr(os, "geteuid") or not db.exists():
        return
    owner = db.stat().st_uid
    if owner != os.geteuid():
        import pwd
        try:
            name = pwd.getpwuid(owner).pw_name
        except KeyError:
            name = str(owner)
        sys.exit(f"The database {db} belongs to '{name}'. Run this as that account "
                 f"(sudo -u {name} ...) or use: sudo smartfinder-ctl add-folder ...")


# ── account ──────────────────────────────────────────────────────────────────
def _password(args: argparse.Namespace) -> Optional[str]:
    pw = args.admin_password or os.environ.get("SMARTFINDER_ADMIN_PASSWORD")
    if pw is None and sys.stdin.isatty() and sys.stdout.isatty():
        pw = getpass.getpass(f"Password for {args.admin_email} (empty: keep the current one): ")
        if pw and pw != getpass.getpass("Repeat the password: "):
            sys.exit("The passwords do not match.")
    return pw or None


def ensure_admin(email: str, name: Optional[str], password: Optional[str]) -> None:
    from app.core.security import hash_password
    from app.database.session import db_get, db_run

    email = email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        sys.exit(f"Not an email address: {email} (accounts sign in with their email)")
    if password is not None and len(password) < MIN_PASSWORD:
        sys.exit(f"The password must have at least {MIN_PASSWORD} characters.")
    row = db_get("SELECT id, username, role FROM users WHERE email = ?", (email,))
    if row is None:
        if password is None:
            sys.exit(f"A password is needed to create {email}: --admin-password, "
                     f"SMARTFINDER_ADMIN_PASSWORD or run in a terminal to be asked.")
        db_run(
            "INSERT INTO users (id, email, username, password_hash, role) VALUES (?, ?, ?, ?, 'admin')",
            (str(uuid.uuid4()), email, (name or "").strip() or email.split("@")[0], hash_password(password)),
        )
        _say(f"Admin account created: {email}")
        return
    sets, params, changed = ["role = 'admin'"], [], []
    if row["role"] != "admin":
        changed.append("made an administrator")
    if name and name.strip() and name.strip() != row["username"]:
        sets.append("username = ?")
        params.append(name.strip())
        changed.append("name updated")
    if password is not None:
        sets.append("password_hash = ?")
        params.append(hash_password(password))
        changed.append("password updated")
    db_run(f"UPDATE users SET {', '.join(sets)}, updated_at = datetime('now') WHERE id = ?", (*params, row["id"]))
    _say(f"Admin account {email}: {', '.join(changed) or 'already an administrator, unchanged'}")


# ── file kinds ───────────────────────────────────────────────────────────────
def _kinds(values: Optional[list], flag: str) -> Optional[set]:
    """['docs,image', 'video'] -> {'document', 'image', 'video'}; None when the flag was not given."""
    if not values:
        return None
    out = set()
    for raw in (v.strip().lower() for value in values for v in value.split(",")):
        if not raw:
            continue
        key = KIND_ALIASES.get(raw, raw)
        if key not in KIND_ARGS:
            sys.exit(f"{flag}: unknown file type '{raw}' (use {', '.join(KIND_ARGS)})")
        out.add(KIND_ARGS[key])
    return out


def apply_kind_filter(lib, include: Optional[set], exclude: Optional[set]) -> None:
    from app.library.sources import FILE_KINDS, excluded_kinds, set_excluded_kinds
    if include is not None or exclude is not None:
        skip = set(FILE_KINDS) - include if include is not None else exclude
        if skip == set(FILE_KINDS):
            sys.exit("That leaves no file types to index.")
        set_excluded_kinds(lib, skip)
    skip = set(excluded_kinds(lib))
    if skip:
        names = {v: k for k, v in KIND_ARGS.items()}
        _say(f"File types: {', '.join(names[k] for k in KIND_ARGS.values() if k not in skip)} "
             f"(skipping {', '.join(names[k] for k in KIND_ARGS.values() if k in skip)})")


# ── indexing ─────────────────────────────────────────────────────────────────
def _open_library(path: str, name: Optional[str]):
    """The library for `path`: the existing one (resume) or a newly attached one."""
    from app.ingest.pipeline import recover_library
    from app.library.manager import LibraryError, get_library_manager

    manager = get_library_manager()
    manager.load_all()
    root = Path(path).expanduser()
    try:
        root = root.resolve(strict=True)
    except OSError:
        sys.exit(f"Folder not found: {path}")
    lib = next((l for l in manager.all() if l.root is not None and l.root == root), None)
    if lib is not None:
        if not lib.online:
            sys.exit(f"The library '{lib.name}' at {root} cannot be opened: {lib.error}")
        if name and name.strip() and name.strip() != lib.name:
            manager.rename(lib.id, name)
        _say(f"Continuing the library '{lib.name}' ({root})")
    else:
        try:
            lib = manager.attach(str(root), name)
        except LibraryError as e:
            sys.exit(str(e))
        recover_library(lib)
        _say(f"Added the library '{lib.name}' ({root}); index in {lib.index_dir}")
    # Only this library is worked on here; the others wait for the backend
    for other in manager.all():
        if other.id != lib.id:
            other.paused = True   # in memory only, not saved
    return manager, lib


def retry_failed(lib) -> int:
    """Files that failed in an earlier run (a crash, a full disk, no handles left) get another go."""
    n = lib.db.execute("UPDATE sources SET status = 'queued', attempts = 0, error = NULL WHERE status = 'failed'")
    n += lib.db.execute(
        "UPDATE sources SET transcript = 'pending', error = NULL WHERE status = 'indexed' AND transcript = 'failed'")
    n += lib.db.execute(
        "UPDATE sources SET image_vectors = 'pending', error = NULL WHERE status = 'indexed' AND image_vectors = 'failed'")
    return n


def _open_files() -> str:
    try:
        return f" | {len(os.listdir('/proc/self/fd'))} open files"
    except OSError:
        return ""


def _remaining(lib) -> dict:
    from app.ingest.pipeline import PASS_COLUMNS
    counts = {r["status"]: int(r["n"]) for r in lib.db.all("SELECT status, COUNT(*) AS n FROM sources GROUP BY status")}
    passes = {
        name: int(lib.db.scalar(
            f"SELECT COUNT(*) FROM sources WHERE status = 'indexed' AND {col} IN ('pending', 'running')", (), 0))
        for name, col in PASS_COLUMNS.items()
    }
    return {"counts": counts, "passes": passes}


def _progress_line(state: dict, pipeline, started: float) -> str:
    c, p = state["counts"], state["passes"]
    parts = [f"indexed {c.get('indexed', 0)}", f"queued {c.get('queued', 0) + c.get('processing', 0)}",
             f"failed {c.get('failed', 0)}"]
    parts += [f"{name} {n}" for name, n in p.items() if n]
    cur = pipeline.current
    now = f" | {cur['stage']}: {cur['file']}" if cur else ""
    return f"{', '.join(parts)} | {(time.time() - started) / 3600:.1f} h{_open_files()}{now}"


async def index(manager, lib, retry: bool = True) -> None:
    from app.ingest.pipeline import IngestionPipeline
    from app.library.scanner import scan_library

    if retry and (n := await asyncio.to_thread(retry_failed, lib)):
        _say(f"Retrying {n} files that failed earlier (--skip-failed leaves them)")

    _say("Scanning the folder...")
    report = await asyncio.to_thread(scan_library, lib)
    manager.mark_scanned(lib.id)
    _say(f"Scan: {report.scanned} files, {report.new} new, {report.changed} changed, {report.removed} removed, "
         f"{report.unsupported} unsupported ({report.seconds:.0f}s)")
    for err in report.errors[:10]:
        print(f"    {err}")

    pipeline = IngestionPipeline(manager)
    pipeline.start()
    started = last_report = time.time()
    try:
        while True:
            await asyncio.sleep(POLL_S)
            state = await asyncio.to_thread(_remaining, lib)
            c = state["counts"]
            if not c.get("queued") and not c.get("processing") and not any(state["passes"].values()):
                break
            if time.time() - last_report >= PROGRESS_INTERVAL_S:
                _say(_progress_line(state, pipeline, started))
                last_report = time.time()
    finally:
        _say("Stopping the indexer...")
        await pipeline.stop()

    from app.people.cluster import maybe_recluster
    people = await asyncio.to_thread(maybe_recluster, manager)
    if people:
        _say(f"People grouped: {people['people']} people from {people['faces']} faces")
    state = _remaining(lib)
    _say(f"Done in {(time.time() - started) / 3600:.1f} h: {state['counts'].get('indexed', 0)} files indexed, "
         f"{state['counts'].get('failed', 0)} failed")
    failed = lib.db.all("SELECT rel_path, error FROM sources WHERE status = 'failed' ORDER BY rel_path LIMIT 20")
    for r in failed:
        print(f"    FAILED {r['rel_path']}: {(r['error'] or '')[:200]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="folder to index (in place)")
    ap.add_argument("--name", help="library name shown in the app (default: the folder name)")
    ap.add_argument("--skip-failed", action="store_true",
                    help="do not retry files that failed in an earlier run (they are retried by default)")
    kinds = ap.add_mutually_exclusive_group()
    kinds.add_argument("-i", "--include", action="append", metavar="TYPE",
                       help="index only these file types: docs, image, video, audio")
    kinds.add_argument("-e", "--exclude", action="append", metavar="TYPE",
                       help="skip these file types: docs, image, video, audio")
    ap.add_argument("--admin-email", help="admin account to create or update (signs in with this email)")
    ap.add_argument("--admin-name", help="display name of the admin account")
    ap.add_argument("--admin-password", help="its password (or SMARTFINDER_ADMIN_PASSWORD, or asked)")
    args = ap.parse_args()
    if not args.path and not args.admin_email:
        ap.error("give a folder to index, --admin-email, or both")
    include, exclude = _kinds(args.include, "-i"), _kinds(args.exclude, "-e")

    _raise_file_limit()
    if args.path:
        _ensure_cuda_libs()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    from app.database.session import run_migrations
    _check_owner()
    if args.path and _backend_running():
        sys.exit("The Smart Finder backend is running. Stop it first (Linux: sudo smartfinder-ctl stop backend, "
                 "or use sudo smartfinder-ctl add-folder, which does that for you) and start it again afterwards.")
    run_migrations()
    if args.admin_email:
        ensure_admin(args.admin_email, args.admin_name, _password(args))
    if not args.path:
        return

    manager, lib = _open_library(args.path, args.name)
    try:
        apply_kind_filter(lib, include, exclude)
        asyncio.run(index(manager, lib, retry=not args.skip_failed))
    except KeyboardInterrupt:
        _say("Interrupted. Run the same command again to continue where it stopped.")
    finally:
        manager.close_all()
    _say("Start the backend to search it (Linux: sudo smartfinder-ctl start backend).")


if __name__ == "__main__":
    main()
