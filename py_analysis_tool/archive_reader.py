"""Read packaged Python application formats.

Currently supports:
  - PyInstaller CArchive (onefile + onedir), PyInstaller >= 4.x
  - py2exe (library.zip extraction)

The PyInstaller reader is a clean-room implementation based on the
public on-disk format documented in the PyInstaller source tree.
"""
from __future__ import annotations

import io
import struct
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, Optional

from .utils import err, info, ok, safe_relpath, warn


# --- PyInstaller cookie ------------------------------------------------------
# MAGIC + package_length + toc_offset + toc_length + pyvers + pylibname
COOKIE_MAGIC = b"MEI\014\013\012\013\016"
COOKIE_FORMAT = "!8sIIII64s"
COOKIE_SIZE = struct.calcsize(COOKIE_FORMAT)


@dataclass
class ArchiveEntry:
    name: str
    offset: int
    comp_size: int
    uncomp_size: int
    comp_flag: int  # 0 = raw, 1 = zlib
    type_code: int
    type_name: str


# PyInstaller type codes (from PyInstaller/archive/writers.py)
_TYPE_MAP = {
    "s": "SCRIPT",
    "m": "MODULE",
    "M": "RUNTIME",
    "b": "BINARY",
    "B": "DATA",
    "x": "EXTENSION",
    "X": "ZIPFILE",
    "z": "PYZ",
    "Z": "PKG",
    "d": "DLL",
    "D": "DLL",
    "o": "OPTION",
    "p": "PACKAGE",
    "P": "PACKAGE_PATH",
    "r": "RUNTIME_OPTION",
}


def _read_cookie(fp: BinaryIO) -> Optional[tuple]:
    """Read the cookie at end of the PyInstaller executable."""
    fp.seek(0, io.SEEK_END)
    size = fp.tell()
    if size < COOKIE_SIZE:
        return None

    # Cookie magic can be present anywhere in the last 8 KiB (padding variance)
    fp.seek(max(0, size - 8192))
    tail = fp.read()

    idx = tail.rfind(COOKIE_MAGIC)
    if idx == -1:
        return None

    cookie_bytes = tail[idx:idx + COOKIE_SIZE]
    if len(cookie_bytes) < COOKIE_SIZE:
        return None

    magic, pkg_len, toc_off, toc_len, pyvers, pylib = struct.unpack(
        COOKIE_FORMAT, cookie_bytes
    )
    cookie_abs = size - len(tail) + idx
    toc_abs = cookie_abs - toc_len
    if toc_abs < 0:
        return None
    return toc_abs, toc_len, pyvers


def _read_toc(fp: BinaryIO, toc_abs: int, toc_len: int) -> list[ArchiveEntry]:
    fp.seek(toc_abs)
    blob = fp.read(toc_len)
    if len(blob) != toc_len:
        raise IOError("short TOC read")

    entries: list[ArchiveEntry] = []
    cursor = 0
    while cursor < len(blob):
        entry_size = struct.unpack("!i", blob[cursor:cursor + 4])[0]
        cursor += 4
        if entry_size <= 0 or cursor + entry_size > len(blob):
            break

        entry_data = blob[cursor:cursor + entry_size]
        cursor += entry_size

        entry_pos = struct.unpack("!i", entry_data[0:4])[0]
        comp_size = struct.unpack("!i", entry_data[4:8])[0]
        uncomp_size = struct.unpack("!i", entry_data[8:12])[0]
        comp_flag = entry_data[12]
        typecode = chr(entry_data[13])
        name = entry_data[14:].split(b"\x00", 1)[0].decode("utf-8", "replace")

        entries.append(ArchiveEntry(
            name=name,
            offset=entry_pos,
            comp_size=comp_size,
            uncomp_size=uncomp_size,
            comp_flag=comp_flag,
            type_code=ord(typecode) if isinstance(typecode, str) else typecode,
            type_name=_TYPE_MAP.get(typecode, "UNKNOWN"),
        ))
    return entries


def is_pyinstaller(path: Path) -> bool:
    try:
        with path.open("rb") as fp:
            return _read_cookie(fp) is not None
    except OSError:
        return False


def _entry_bytes(fp: BinaryIO, entry: ArchiveEntry) -> bytes:
    fp.seek(entry.offset)
    raw = fp.read(entry.comp_size)
    if entry.comp_flag == 1:
        return zlib.decompress(raw)
    return raw


def _iter_pyz(data: bytes) -> Iterator[tuple[str, bytes]]:
    """
    PYZ is a zlib-compressed marshalled list of (name, (typecode, offset, length)).
    Entries past the header are compressed individually.
    """
    import marshal

    inner = zlib.decompress(data)
    toc = marshal.loads(inner[8:])  # skip magic + length
    if not isinstance(toc, list):
        return

    for item in toc:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        name, payload = item
        if not isinstance(payload, tuple) or len(payload) != 3:
            continue
        typecode, offset, length = payload
        start = 8 + offset
        chunk = inner[start:start + length]
        try:
            code_bytes = zlib.decompress(chunk)
        except zlib.error:
            code_bytes = chunk
        yield name, code_bytes


def extract_pyinstaller(exe: Path, out_dir: Path) -> list[Path]:
    """Extract all embedded Python modules from a PyInstaller executable."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    with exe.open("rb") as fp:
        cookie = _read_cookie(fp)
        if not cookie:
            err(f"{exe.name}: no PyInstaller cookie found")
            return written
        toc_abs, toc_len, pyvers = cookie
        info(f"{exe.name}: PyInstaller cookie, python bytecode version {pyvers}")

        entries = _read_toc(fp, toc_abs, toc_len)
        ok(f"{exe.name}: {len(entries)} archive entries")

        for entry in entries:
            try:
                data = _entry_bytes(fp, entry)
            except Exception as e:  # noqa: BLE001
                warn(f"failed to read {entry.name}: {e}")
                continue

            if entry.type_code == ord("z"):  # PYZ
                pyz_dir = out_dir / "_pyz"
                pyz_dir.mkdir(exist_ok=True)
                for name, code_bytes in _iter_pyz(data):
                    dst = pyz_dir / (name.replace(".", "/") + ".pyc")
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(code_bytes)
                    written.append(dst)
            else:
                dst = out_dir / entry.type_name.lower() / safe_relpath(
                    Path(entry.name), Path("."))
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                written.append(dst)

    ok(f"{exe.name}: wrote {len(written)} files to {out_dir}")
    return written


# --- py2exe ------------------------------------------------------------------
def is_py2exe(path: Path) -> bool:
    try:
        with path.open("rb") as fp:
            head = fp.read(2)
        return head == b"MZ"
    except OSError:
        return False


def extract_py2exe(exe: Path, out_dir: Path) -> list[Path]:
    """
    py2exe produces a Windows PE that embeds a 'library.zip' resource
    containing all .pyc files. We scan for the zip signature.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    data = exe.read_bytes()
    sig = b"PK\x03\x04"
    idx = data.find(sig)
    if idx == -1:
        err(f"{exe.name}: no embedded ZIP found (not py2exe?)")
        return written

    try:
        with zipfile.ZipFile(io.BytesIO(data[idx:])) as zf:
            for name in zf.namelist():
                if not name.lower().endswith((".pyc", ".py", ".pyd", ".dll")):
                    continue
                dst = out_dir / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(zf.read(name))
                written.append(dst)
    except zipfile.BadZipFile as e:
        err(f"{exe.name}: corrupt embedded zip: {e}")
        return written

    ok(f"{exe.name}: extracted {len(written)} files (py2exe)")
    return written