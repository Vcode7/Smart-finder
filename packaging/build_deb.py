"""
Build the Smart Finder Debian package with the Python standard library only (runs on
Windows or Linux; no dpkg-deb, WSL or Docker needed).

    python packaging/build_deb.py                 # version from packaging/VERSION
    python packaging/build_deb.py --version 0.0.4

Output: dist/smartfinder_<version>_amd64.deb (a few MB: code, services, smartfinder-ctl).
Dependencies and models are downloaded on the Linux machine by `smartfinder-ctl setup`, and
later code changes arrive with `smartfinder-ctl update-code` (from GitHub), so a new .deb
is only needed when the apt dependencies or the systemd units below change.
"""
import argparse
import gzip
import hashlib
import io
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINUX = ROOT / "packaging" / "linux"
SRC_PREFIX = "usr/share/smartfinder/src"

DEPENDS = [
    "git", "ca-certificates", "curl", "xz-utils", "iproute2", "util-linux",
    "tesseract-ocr", "tesseract-ocr-eng", "tesseract-ocr-hin",
    "ffmpeg", "libgomp1", "libglib2.0-0",
]
SUGGESTS = ["libreoffice-core", "nvidia-driver"]

# packaging/linux file -> (installed path, mode)
INSTALL = {
    "smartfinder-ctl.shim": ("usr/bin/smartfinder-ctl", 0o755),
    "smartfinder-backend.service": ("usr/lib/systemd/system/smartfinder-backend.service", 0o644),
    "smartfinder-frontend.service": ("usr/lib/systemd/system/smartfinder-frontend.service", 0o644),
    "smartfinder.target": ("usr/lib/systemd/system/smartfinder.target", 0o644),
    "60-smartfinder.conf": ("usr/lib/sysctl.d/60-smartfinder.conf", 0o644),
    "backend.env.template": ("usr/share/smartfinder/backend.env.template", 0o644),
    "workspace.env.template": ("usr/share/smartfinder/workspace.env.template", 0o644),
    "smartfinder.conf.template": ("usr/share/smartfinder/smartfinder.conf.template", 0o644),
}
MAINTAINER_SCRIPTS = ["postinst", "prerm", "postrm"]

# Never bundled even if git would list them
EXCLUDE_PREFIXES = ("backend/tests/",)
# Ignored by .gitignore at some point but needed for `npm ci`
FORCE_INCLUDE = ["workspace/package-lock.json"]


def source_files() -> list:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z",
         "--", "backend", "workspace", "packaging/linux"],
        cwd=ROOT, check=True, capture_output=True,
    ).stdout.decode("utf-8")
    names = {n for n in out.split("\0") if n}
    names.update(n for n in FORCE_INCLUDE if (ROOT / n).is_file())
    return sorted(n for n in names if not n.startswith(EXCLUDE_PREFIXES) and (ROOT / n).is_file())


def needs_lf(rel: str, data: bytes) -> bool:
    return rel.startswith("packaging/linux/") or data.startswith(b"#!")


def read(rel: str) -> bytes:
    data = (ROOT / rel).read_bytes()
    return data.replace(b"\r\n", b"\n") if needs_lf(rel, data) else data


class TarBuilder:
    def __init__(self, mtime: int):
        self.buf = io.BytesIO()
        self.gz = gzip.GzipFile(fileobj=self.buf, mode="wb", mtime=mtime, compresslevel=9)
        self.tar = tarfile.open(fileobj=self.gz, mode="w", format=tarfile.GNU_FORMAT)
        self.mtime = mtime
        self.dirs = set()
        self._dir(".")

    def _info(self, name: str, mode: int) -> tarfile.TarInfo:
        info = tarfile.TarInfo(name)
        info.mode, info.mtime = mode, self.mtime
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        return info

    def _dir(self, name: str) -> None:
        if name in self.dirs:
            return
        if name != ".":
            self._dir(name.rsplit("/", 1)[0])  # "./usr/bin" -> "./usr" -> "."
        info = self._info(name if name == "." else name + "/", 0o755)
        info.type = tarfile.DIRTYPE
        self.tar.addfile(info)
        self.dirs.add(name)

    def add(self, path: str, data: bytes, mode: int) -> None:
        name = "./" + path
        self._dir(name.rsplit("/", 1)[0])
        info = self._info(name, mode)
        info.size = len(data)
        self.tar.addfile(info, io.BytesIO(data))

    def finish(self) -> bytes:
        self.tar.close()
        self.gz.close()
        return self.buf.getvalue()


def ar_archive(members: list, mtime: int) -> bytes:
    out = io.BytesIO()
    out.write(b"!<arch>\n")
    for name, data in members:
        header = f"{name:<16}{mtime:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n"
        out.write(header.encode("ascii"))
        out.write(data)
        if len(data) % 2:
            out.write(b"\n")
    return out.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default=(ROOT / "packaging" / "VERSION").read_text().strip())
    ap.add_argument("--out", default=str(ROOT / "dist"))
    args = ap.parse_args()

    t0 = time.time()
    mtime = int(time.time())
    data_tar = TarBuilder(mtime)
    md5sums = []
    installed_bytes = 0

    def add(path: str, data: bytes, mode: int) -> None:
        nonlocal installed_bytes
        data_tar.add(path, data, mode)
        md5sums.append(f"{hashlib.md5(data).hexdigest()}  {path}")
        installed_bytes += len(data)

    files = source_files()
    if not any(f.startswith("packaging/linux/smartfinder-ctl") for f in files):
        sys.exit("packaging/linux/smartfinder-ctl is missing")
    for rel in files:
        data = read(rel)
        executable = data.startswith(b"#!") or rel == "packaging/linux/smartfinder-ctl"
        add(f"{SRC_PREFIX}/{rel}", data, 0o755 if executable else 0o644)
    for src, (dest, mode) in INSTALL.items():
        add(dest, read(f"packaging/linux/{src}"), mode)

    control = "\n".join([
        "Package: smartfinder",
        f"Version: {args.version}",
        "Architecture: amd64",
        "Maintainer: Vcode7 <vikaskag7@gmail.com>",
        f"Installed-Size: {installed_bytes // 1024 + 1}",
        f"Depends: {', '.join(DEPENDS)}",
        f"Suggests: {', '.join(SUGGESTS)}",
        "Section: utils",
        "Priority: optional",
        "Homepage: https://github.com/Vcode7/Smart-finder",
        "Description: Smart Finder - private AI search for your own files",
        " Indexes folders in place (documents, photos, videos, audio) and searches them",
        " by words, meaning, pictures, faces and sounds. After installing, run",
        " 'sudo smartfinder-ctl setup' to download the Python/Node packages and AI models",
        " and start the services; 'smartfinder-ctl update-code' pulls new code from GitHub.",
        "",
    ])
    control_tar = TarBuilder(mtime)
    control_tar.add("control", control.encode("utf-8"), 0o644)
    control_tar.add("md5sums", ("\n".join(md5sums) + "\n").encode("utf-8"), 0o644)
    for script in MAINTAINER_SCRIPTS:
        control_tar.add(script, read(f"packaging/linux/{script}"), 0o755)

    deb = ar_archive([
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", control_tar.finish()),
        ("data.tar.gz", data_tar.finish()),
    ], mtime)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"smartfinder_{args.version}_amd64.deb"
    out.write_bytes(deb)
    print(f"{out}  ({len(deb) / 1e6:.1f} MB, {len(files)} source files, {time.time() - t0:.1f}s)")
    print("Install on Linux:  sudo apt install ./" + out.name + "  &&  sudo smartfinder-ctl setup")
    return 0


if __name__ == "__main__":
    sys.exit(main())
