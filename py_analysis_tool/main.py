"""CLI entry point for py-analysis-tool."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from . import __version__
from . import pycdc_wrapper
from .archive_reader import extract_py2exe, extract_pyinstaller, is_pyinstaller
from .pyc_reader import detect_obfuscation, load_pyc
from .recovery_engine import recover
from .report import FileReport, RunReport, write_report
from .utils import ensure_dir, err, info, ok, safe_relpath, setup_logging, warn


def _collect_inputs(inputs: list[Path], recursive: bool) -> list[Path]:
    out: list[Path] = []
    for p in inputs:
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            out.extend(f for f in it if f.is_file())
        else:
            warn(f"skipping missing path: {p}")
    return out


def _classify(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".pyc":
        return "pyc"
    if suf == ".py":
        return "source"
    if suf in (".exe", ".bin"):
        if is_pyinstaller(path):
            return "pyinstaller"
        return "py2exe"
    if suf == ".pyz":
        return "pyz"
    return "unknown"


def _handle_pyc(
    pyc: Path,
    out_dir: Path,
    engine: str,
    auto_build_pycdc: bool = False,
) -> FileReport:
    rep = FileReport(input_path=str(pyc), kind="pyc")
    info(f"reading {pyc.name}")
    info_obj = load_pyc(pyc)

    obf = detect_obfuscation(pyc)
    if obf:
        rep.obfuscation = obf
        warn(f"{pyc.name}: obfuscation detected ({obf})")

    if not info_obj.is_valid:
        rep.status = "failed"
        rep.note = info_obj.error or "invalid pyc"
        err(f"{pyc.name}: {rep.note}")
        return rep

    rep.python_version = info_obj.python_version

    dest = ensure_dir(out_dir / pyc.stem)
    res = recover(pyc, dest, engine=engine, auto_build_pycdc=auto_build_pycdc)
    rep.engine = res.engine
    if res.success and res.source_path:
        rep.status = "ok"
        rep.outputs = [safe_relpath(res.source_path, out_dir)]
    else:
        rep.status = "partial"
        rep.note = res.message
    if res.dis_path:
        rep.outputs.append(safe_relpath(res.dis_path, out_dir))
    return rep


def _handle_pyinstaller(
    exe: Path,
    out_dir: Path,
    engine: str,
    keep_pyc: bool,
    auto_build_pycdc: bool = False,
) -> list[FileReport]:
    reports: list[FileReport] = []
    dest = ensure_dir(out_dir / exe.stem)
    info(f"{exe.name}: PyInstaller archive")
    try:
        extracted = extract_pyinstaller(exe, dest)
    except Exception as e:  # noqa: BLE001
        err(f"{exe.name}: extraction failed: {e}")
        return [FileReport(input_path=str(exe), kind="pyinstaller",
                           status="failed", note=str(e))]

    root_rep = FileReport(input_path=str(exe), kind="pyinstaller", status="ok")
    root_rep.outputs.append(safe_relpath(dest, out_dir))
    reports.append(root_rep)

    pycs = [p for p in extracted if p.suffix == ".pyc"]
    if not pycs:
        warn(f"{exe.name}: no .pyc files extracted")
        return reports

    info(f"{exe.name}: recovering source from {len(pycs)} modules")
    for pyc in tqdm(pycs, desc="recover", unit="file", leave=False):
        r = _handle_pyc(pyc, dest / "_recovered", engine, auto_build_pycdc)
        r.input_path = safe_relpath(pyc, dest)
        reports.append(r)
        if not keep_pyc:
            try:
                pyc.unlink()
            except OSError:
                pass
    return reports


def _handle_py2exe(
    exe: Path,
    out_dir: Path,
    engine: str,
    keep_pyc: bool,
    auto_build_pycdc: bool = False,
) -> list[FileReport]:
    reports: list[FileReport] = []
    dest = ensure_dir(out_dir / exe.stem)
    info(f"{exe.name}: py2exe-style archive")
    try:
        extracted = extract_py2exe(exe, dest)
    except Exception as e:  # noqa: BLE001
        err(f"{exe.name}: extraction failed: {e}")
        return [FileReport(input_path=str(exe), kind="py2exe",
                           status="failed", note=str(e))]

    root_rep = FileReport(input_path=str(exe), kind="py2exe",
                          status="ok" if extracted else "partial",
                          note="" if extracted else "no embedded zip found")
    root_rep.outputs.append(safe_relpath(dest, out_dir))
    reports.append(root_rep)

    for pyc in extracted:
        if pyc.suffix != ".pyc":
            continue
        r = _handle_pyc(pyc, dest / "_recovered", engine, auto_build_pycdc)
        r.input_path = safe_relpath(pyc, dest)
        reports.append(r)
        if not keep_pyc:
            try:
                pyc.unlink()
            except OSError:
                pass
    return reports


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="py-analysis",
        description="Inspect Python bytecode and packaged application formats.",
    )
    p.add_argument("inputs", nargs="+", type=Path)
    p.add_argument("-o", "--output", type=Path, default=Path("out"))
    p.add_argument("-r", "--recursive", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--log", type=Path, default=None)
    p.add_argument("--engine", default="auto",
                   choices=["auto", "pycdc", "uncompyle6", "decompyle3", "dis"])
    p.add_argument("--keep-pyc", action="store_true")
    p.add_argument("--report", type=Path, default=None)
    p.add_argument("--auto-build-pycdc", action="store_true",
                   help="build pycdc from source on first run if missing")
    p.add_argument("--fetch-pycdc", action="store_true",
                   help="download prebuilt pycdc from PYCDC_RELEASE_URL")
    p.add_argument("--version", action="version",
                   version=f"py-analysis-tool {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose, args.log)

    # Ensure pycdc is available before doing any work
    if args.fetch_pycdc:
        pycdc_wrapper.fetch_prebuilt()
    if args.auto_build_pycdc:
        pycdc_wrapper.ensure_built(auto_build=True)

    run = RunReport(started=datetime.now())
    out_dir = ensure_dir(args.output)

    inputs = _collect_inputs(args.inputs, args.recursive)
    if not inputs:
        err("no input files found")
        return 1

    ok(f"analyzing {len(inputs)} file(s) -> {out_dir}")

    for path in tqdm(inputs, desc="input", unit="file"):
        kind = _classify(path)
        try:
            if kind == "pyc":
                run.files.append(_handle_pyc(
                    path, out_dir, args.engine, args.auto_build_pycdc))
            elif kind == "pyinstaller":
                run.files.extend(_handle_pyinstaller(
                    path, out_dir, args.engine, args.keep_pyc,
                    args.auto_build_pycdc))
            elif kind == "py2exe":
                run.files.extend(_handle_py2exe(
                    path, out_dir, args.engine, args.keep_pyc,
                    args.auto_build_pycdc))
            elif kind == "source":
                info(f"{path.name}: plain source, skipping")
            else:
                warn(f"{path.name}: unsupported format, skipping")
        except Exception as e:  # noqa: BLE001
            err(f"{path.name}: unexpected error: {e}")
            run.files.append(FileReport(
                input_path=str(path), kind=kind, status="failed", note=str(e)))

    run.finished = datetime.now()

    if args.report:
        rp = write_report(run, args.report)
        ok(f"report written: {rp}")

    ok_done = sum(1 for r in run.files if r.status == "ok")
    partial = sum(1 for r in run.files if r.status == "partial")
    failed = sum(1 for r in run.files if r.status == "failed")
    ok(f"done: {ok_done} ok, {partial} partial, {failed} failed")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())