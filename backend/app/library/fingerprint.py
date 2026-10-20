"""
app/library/fingerprint.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Constant-time content fingerprint for files of any size.

BLAKE2b-128 over the file size plus the first, middle and last 1 MiB. Files up to
3 MiB are hashed completely. Good enough to recognise a renamed/moved file or a
duplicate upload; it is not a cryptographic integrity check.
"""
import hashlib
from pathlib import Path

_SAMPLE = 1024 * 1024


def file_fingerprint(path: Path) -> str:
    path = Path(path)
    size = path.stat().st_size
    h = hashlib.blake2b(digest_size=16)
    h.update(str(size).encode("ascii"))
    with open(path, "rb") as f:
        if size <= 3 * _SAMPLE:
            while True:
                block = f.read(_SAMPLE)
                if not block:
                    break
                h.update(block)
        else:
            h.update(f.read(_SAMPLE))
            f.seek(size // 2 - _SAMPLE // 2)
            h.update(f.read(_SAMPLE))
            f.seek(size - _SAMPLE)
            h.update(f.read(_SAMPLE))
    return h.hexdigest()
