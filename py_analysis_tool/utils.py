"""Shared helpers: logging, path handling, magic number parsing."""
from __future__ import annotations

import logging
import os
import struct
from pathlib import Path
from typing import Optional

from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

LOG = logging.getLogger("py-analysis")


def setup_logging(verbose: bool, logfile: Optional[Path] = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if logfile:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(logfile, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


def info(msg: str) -> None:
    LOG.info(f"{Fore.CYAN}[*]{Style.RESET_ALL} {msg}")


def ok(msg: str) -> None:
    LOG.info(f"{Fore.GREEN}[+]{Style.RESET_ALL} {msg}")


def warn(msg: str) -> None:
    LOG.warning(f"{Fore.YELLOW}[!]{Style.RESET_ALL} {msg}")


def err(msg: str) -> None:
    LOG.error(f"{Fore.RED}[-]{Style.RESET_ALL} {msg}")


# --- Python .pyc magic number table -----------------------------------------
# Format: magic (uint16 LE) -> (major, minor)
# Reference: CPython source Lib/importlib/_bootstrap_external.py
MAGIC_TO_VERSION: dict[int, tuple[int, int]] = {
    3379: (3, 6),
    3394: (3, 7),
    3413: (3, 8),
    3425: (3, 9),
    3439: (3, 10),
    3495: (3, 11),
    3531: (3, 12),
    3571: (3, 13),
    3605: (3, 14),
}


def read_pyc_header(path: Path) -> Optional[tuple[int, int, int]]:
    """
    Parse a .pyc header.
    Returns (magic, major, minor) or None if not a valid pyc.
    """
    try:
        with path.open("rb") as f:
            header = f.read(4)
    except OSError:
        return None
    if len(header) < 4:
        return None
    magic = struct.unpack("<H", header[:2])[0]
    version = MAGIC_TO_VERSION.get(magic)
    if version is None:
        return (magic, 0, 0)
    return (magic, version[0], version[1])


def safe_relpath(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def cache_dir() -> Path:
    """Return a per-user cache dir for downloaded binaries."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    d = base / "py-analysis-tool"
    d.mkdir(parents=True, exist_ok=True)
    return d