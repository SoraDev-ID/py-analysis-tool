"""Recover Python source from .pyc files using external engines.

Engine order (when --engine=auto):
  1. pycdc         (native, supports 3.6 - 3.13)
  2. decompyle3    (3.7 - 3.8)
  3. uncompyle6    (2.7 - 3.8)
  4. dis           (any version, disassembly only)
"""
from __future__ import annotations

import dis
import io
import marshal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import pycdc_wrapper
from .utils import warn


@dataclass
class RecoveryResult:
    source_path: Optional[Path]
    dis_path: Optional[Path]
    engine: str
    success: bool
    message: str = ""


def _has_uncompyle6() -> bool:
    try:
        import uncompyle6  # noqa: F401
        return True
    except ImportError:
        return False


def _has_decompyle3() -> bool:
    try:
        import decompyle3  # noqa: F401
        return True
    except ImportError:
        return False


def _has_pycdc() -> bool:
    return pycdc_wrapper.find_pycdc().available


def _run_uncompyle6(pyc: Path) -> Optional[str]:
    from uncompyle6 import decompile_file
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        decompile_file(str(pyc), buf)
    except Exception as e:  # noqa: BLE001
        sys.stdout = old
        raise e
    finally:
        sys.stdout = old
    text = buf.getvalue()
    return text if text.strip() else None


def _run_decompyle3(pyc: Path) -> Optional[str]:
    from decompyle3 import decompile_file
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        decompile_file(str(pyc), buf)
    except Exception as e:  # noqa: BLE001
        sys.stdout = old
        raise e
    finally:
        sys.stdout = old
    text = buf.getvalue()
    return text if text.strip() else None


def _run_dis(pyc: Path) -> str:
    raw = pyc.read_bytes()
    code = None
    for offset in (16, 12):
        if len(raw) <= offset:
            continue
        try:
            code = marshal.loads(raw[offset:])
            break
        except Exception:  # noqa: BLE001
            continue
    if code is None:
        return f"# disassembly failed for {pyc.name}\n"

    buf = io.StringIO()
    buf.write(f"# disassembly of {pyc.name}\n")
    buf.write(f"# python {sys.version.split()[0]}\n\n")
    try:
        dis.dis(code, file=buf)
    except Exception as e:  # noqa: BLE001
        buf.write(f"# dis error: {e}\n")
    return buf.getvalue()


def recover(pyc_path: Path, out_dir: Path, engine: str = "auto",
            auto_build_pycdc: bool = False) -> RecoveryResult:
    """Attempt to recover source; always emit a dis fallback."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pyc_path.stem
    py_out = out_dir / f"{stem}.py"
    dis_out = out_dir / f"{stem}.dis.txt"

    if auto_build_pycdc and not _has_pycdc():
        pycdc_wrapper.ensure_built(auto_build=True)

    engines_order: list[str]
    if engine == "auto":
        engines_order = []
        if _has_pycdc():
            engines_order.append("pycdc")
        if _has_decompyle3():
            engines_order.append("decompyle3")
        if _has_uncompyle6():
            engines_order.append("uncompyle6")
    elif engine in ("pycdc", "uncompyle6", "decompyle3"):
        engines_order = [engine]
    elif engine == "dis":
        engines_order = []
    else:
        warn(f"unknown engine '{engine}', falling back to auto")
        return recover(pyc_path, out_dir, "auto",
                       auto_build_pycdc=auto_build_pycdc)

    for name in engines_order:
        try:
            if name == "pycdc":
                text = pycdc_wrapper.decompile(pyc_path)
            elif name == "decompyle3":
                text = _run_decompyle3(pyc_path)
            elif name == "uncompyle6":
                text = _run_uncompyle6(pyc_path)
            else:
                continue
            if text:
                py_out.write_text(text, encoding="utf-8")
                dis_text = pycdc_wrapper.disassemble(pyc_path) or _run_dis(pyc_path)
                dis_out.write_text(dis_text, encoding="utf-8")
                return RecoveryResult(py_out, dis_out, name, True)
        except Exception as e:  # noqa: BLE001
            warn(f"{name} failed on {pyc_path.name}: {e}")

    dis_text = pycdc_wrapper.disassemble(pyc_path) or _run_dis(pyc_path)
    dis_out.write_text(dis_text, encoding="utf-8")
    return RecoveryResult(None, dis_out, "dis", False,
                          "all decompilers failed; disassembly written")