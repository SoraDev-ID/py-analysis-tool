"""Read .pyc files: detect version, extract code object metadata."""
from __future__ import annotations

import importlib.util
import marshal
import struct
from dataclasses import dataclass, field
from pathlib import Path
from types import CodeType
from typing import Optional

from .utils import read_pyc_header, warn


@dataclass
class PycInfo:
    path: Path
    magic: int
    python_major: int
    python_minor: int
    code: Optional[CodeType] = None
    error: Optional[str] = None
    embedded_strings: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)

    @property
    def python_version(self) -> str:
        if self.python_major == 0:
            return "unknown"
        return f"{self.python_major}.{self.python_minor}"

    @property
    def is_valid(self) -> bool:
        return self.code is not None


# Header sizes by Python version.
# 3.0-3.6: 12 bytes (magic + mtime + size)
# 3.7+:    16 bytes (magic + flags + mtime + size)
_HEADER_SIZE_LEGACY = 12
_HEADER_SIZE_MODERN = 16


def _header_size(major: int, minor: int) -> int:
    if (major, minor) >= (3, 7):
        return _HEADER_SIZE_MODERN
    return _HEADER_SIZE_LEGACY


def load_pyc(path: Path) -> PycInfo:
    """Load a .pyc and produce PycInfo, attempting marshal of the code object."""
    hdr = read_pyc_header(path)
    if hdr is None:
        return PycInfo(path=path, magic=0, python_major=0, python_minor=0,
                       error="not a valid .pyc file")
    magic, major, minor = hdr
    info = PycInfo(path=path, magic=magic, python_major=major, python_minor=minor)

    try:
        raw = path.read_bytes()
    except OSError as e:
        info.error = f"read error: {e}"
        return info

    header_sz = _header_size(major, minor)
    body = raw[header_sz:]

    # Reject if the .pyc targets a newer interpreter than the running one
    current = (importlib.util.MAGIC_NUMBER[0] | (importlib.util.MAGIC_NUMBER[1] << 8))
    if magic > current:
        info.error = (
            f"pyc targets Python {major}.{minor} but interpreter is "
            f"{struct.unpack('<H', importlib.util.MAGIC_NUMBER[:2])[0]}"
        )
        return info

    try:
        code = marshal.loads(body)
        if isinstance(code, CodeType):
            info.code = code
        else:
            info.error = "marshal payload is not a code object"
    except Exception as e:  # noqa: BLE001
        info.error = f"marshal failed: {e}"
        return info

    _collect_metadata(info)
    return info


def _collect_metadata(info: PycInfo) -> None:
    if info.code is None:
        return
    names: set[str] = set()
    strings: set[str] = set()

    def walk(co: CodeType) -> None:
        for n in co.co_names:
            names.add(n)
        for c in co.co_consts:
            if isinstance(c, str):
                strings.add(c)
            elif isinstance(c, CodeType):
                walk(c)

    try:
        walk(info.code)
    except Exception as e:  # noqa: BLE001
        warn(f"metadata walk failed on {info.path.name}: {e}")
    info.names = sorted(names)
    info.embedded_strings = sorted(s for s in strings if 3 <= len(s) <= 200)


def detect_obfuscation(path: Path) -> Optional[str]:
    """
    Heuristic scan for common obfuscator markers.
    Returns a marker string or None.
    """
    try:
        head = path.read_bytes()[:4096]
    except OSError:
        return None

    markers = {
        b"pyarmor": "pyarmor",
        b"pytransform": "pyarmor",
        b"__pyarmor__": "pyarmor",
        b"pyobfuscate": "pyobfuscate",
        b"Opy": "Opy obfuscator",
    }
    for marker, name in markers.items():
        if marker in head:
            return name
    return None


def export_code_bytes(code: CodeType) -> bytes:
    """Re-serialize a code object to raw marshal bytes (for inspection)."""
    return marshal.dumps(code)