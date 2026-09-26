"""Wrapper around pycdc / pycdas (Decompyle++).

pycdc is a C++ decompiler that supports Python bytecode up to 3.13.
We locate the binaries in a few standard places, auto-build them if
a source tree is present, and optionally download prebuilt binaries
from a GitHub release.

Locations checked, in order:
  1. $PYCDC_DIR env var
  2. per-user cache dir (~/.cache/py-analysis-tool/pycdc/)
  3. <repo_root>/third_party/pycdc/build[/Release|RelWithDebInfo|Debug]/
  4. <repo_root>/third_party/pycdc/
  5. <repo_root>/bin/
  6. PATH lookup
"""
from __future__ import annotations

import io
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .utils import cache_dir, info, ok, warn


REPO_ROOT = Path(__file__).resolve().parent.parent
PYCDC_SRC_DIR = REPO_ROOT / "third_party" / "pycdc"

_WIN = sys.platform.startswith("win")
_EXE = ".exe" if _WIN else ""

# Configure this to your own release if you fork and publish binaries.
# Expected asset name pattern is defined below.
PYCDC_RELEASE_URL = os.environ.get(
    "PYCDC_RELEASE_URL",
    "",  # leave empty to disable auto-download by default
)


@dataclass
class PycdcPaths:
    decompiler: Optional[Path]  # pycdc
    disassembler: Optional[Path]  # pycdas

    @property
    def available(self) -> bool:
        return self.decompiler is not None or self.disassembler is not None


def _cache_bin_dir() -> Path:
    d = cache_dir() / "pycdc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _candidates(name: str) -> list[Path]:
    filename = name + _EXE
    out: list[Path] = []

    env_dir = os.environ.get("PYCDC_DIR")
    if env_dir:
        out.append(Path(env_dir) / filename)

    out.append(_cache_bin_dir() / filename)

    out.extend([
        PYCDC_SRC_DIR / "build" / filename,
        PYCDC_SRC_DIR / "build" / "Release" / filename,
        PYCDC_SRC_DIR / "build" / "RelWithDebInfo" / filename,
        PYCDC_SRC_DIR / "build" / "Debug" / filename,
        PYCDC_SRC_DIR / filename,
        PYCDC_SRC_DIR / "bin" / filename,
        REPO_ROOT / "bin" / filename,
        REPO_ROOT / "third_party" / "bin" / filename,
    ])

    on_path = shutil.which(name)
    if on_path:
        out.append(Path(on_path))
    return out


def _resolve(name: str) -> Optional[Path]:
    for c in _candidates(name):
        if c.is_file():
            return c
    return None


def find_pycdc() -> PycdcPaths:
    return PycdcPaths(
        decompiler=_resolve("pycdc"),
        disassembler=_resolve("pycdas"),
    )


def _have_cmake() -> bool:
    return shutil.which("cmake") is not None


def ensure_built(auto_build: bool = False) -> PycdcPaths:
    """
    Return available pycdc paths. If not found and auto_build is set,
    try to build from the checked-out source tree.
    """
    paths = find_pycdc()
    if paths.available:
        return paths

    if not auto_build:
        warn("pycdc/pycdas not found on system (auto-build disabled)")
        return paths

    if not PYCDC_SRC_DIR.is_dir():
        warn(f"pycdc source not present at {PYCDC_SRC_DIR}")
        return paths

    if not _have_cmake():
        warn("cmake not in PATH; cannot auto-build pycdc")
        return paths

    info("building pycdc via cmake...")
    build_dir = PYCDC_SRC_DIR / "build"
    build_dir.mkdir(exist_ok=True)

    try:
        subprocess.run(
            ["cmake", "-S", str(PYCDC_SRC_DIR), "-B", str(build_dir),
             "-DCMAKE_BUILD_TYPE=Release"],
            check=True,
        )
        # MSVC generator defaults to Debug unless --config given
        build_cmd = ["cmake", "--build", str(build_dir), "--config", "Release"]
        subprocess.run(build_cmd, check=True)
    except subprocess.CalledProcessError as e:
        warn(f"pycdc build failed: {e}")
        return find_pycdc()

    ok("pycdc built")
    return find_pycdc()


# --- Prebuilt download -------------------------------------------------------
def _platform_tag() -> Optional[str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        if machine in ("amd64", "x86_64"):
            return "windows-x64"
    elif system == "linux":
        if machine in ("x86_64", "amd64"):
            return "linux-x64"
    elif system == "darwin":
        if machine in ("arm64", "aarch64"):
            return "macos-arm64"
        if machine in ("x86_64", "amd64"):
            return "macos-x64"
    return None


def fetch_prebuilt(url: Optional[str] = None, force: bool = False) -> PycdcPaths:
    """
    Download prebuilt pycdc binaries from a GitHub release zip/tarball.

    Set PYCDC_RELEASE_URL env var (or pass url=) to a URL that points
    to an archive containing pycdc(.exe) and pycdas(.exe) at its root.
    """
    paths = find_pycdc()
    if paths.available and not force:
        return paths

    url = url or PYCDC_RELEASE_URL
    if not url:
        warn("no PYCDC_RELEASE_URL configured; cannot fetch prebuilt pycdc")
        return paths

    tag = _platform_tag()
    if not tag:
        warn(f"unsupported platform for prebuilt fetch: "
             f"{platform.system()}/{platform.machine()}")
        return paths

    try:
        import requests
    except ImportError:
        warn("requests not installed; run: pip install requests")
        return paths

    # URL template: {url} may contain {tag}; otherwise append.
    if "{tag}" in url:
        full_url = url.format(tag=tag)
    else:
        full_url = url

    info(f"fetching prebuilt pycdc: {full_url}")
    try:
        r = requests.get(full_url, timeout=120, stream=True)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        warn(f"download failed: {e}")
        return paths

    data = r.content
    dest = _cache_bin_dir()

    try:
        if full_url.endswith(".zip") or data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                _extract_bins_from_zip(zf, dest)
        elif full_url.endswith((".tar.gz", ".tgz")):
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                _extract_bins_from_tar(tf, dest)
        else:
            warn("unknown archive format; expected .zip or .tar.gz")
            return paths
    except Exception as e:  # noqa: BLE001
        warn(f"extract failed: {e}")
        return paths

    _chmod_exec(dest)
    ok(f"pycdc installed to {dest}")
    return find_pycdc()


def _extract_bins_from_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    wanted = {"pycdc", "pycdc.exe", "pycdas", "pycdas.exe"}
    for member in zf.namelist():
        base = Path(member).name
        if base in wanted:
            (dest / base).write_bytes(zf.read(member))


def _extract_bins_from_tar(tf: tarfile.TarFile, dest: Path) -> None:
    wanted = {"pycdc", "pycdc.exe", "pycdas", "pycdas.exe"}
    for member in tf.getmembers():
        base = Path(member.name).name
        if base in wanted and member.isfile():
            f = tf.extractfile(member)
            if f:
                (dest / base).write_bytes(f.read())


def _chmod_exec(d: Path) -> None:
    if _WIN:
        return
    for f in d.iterdir():
        if f.is_file():
            f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# --- Runtime invocation ------------------------------------------------------
def decompile(pyc_path: Path, timeout: int = 60) -> Optional[str]:
    paths = find_pycdc()
    if not paths.decompiler:
        return None

    try:
        proc = subprocess.run(
            [str(paths.decompiler), str(pyc_path)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        warn(f"pycdc timeout on {pyc_path.name}")
        return None
    except OSError as e:
        warn(f"pycdc exec failed: {e}")
        return None

    if proc.returncode != 0 and not proc.stdout:
        return None
    return proc.stdout or None


def disassemble(pyc_path: Path, timeout: int = 60) -> Optional[str]:
    paths = find_pycdc()
    if not paths.disassembler:
        return None

    try:
        proc = subprocess.run(
            [str(paths.disassembler), str(pyc_path)],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return proc.stdout or None