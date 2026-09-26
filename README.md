[![test](https://github.com/SoraDev-ID/py-analysis-tool/actions/workflows/test.yml/badge.svg)](https://github.com/SoraDev-ID/py-analysis-tool/actions/workflows/test.yml)
[![build-pycdc](https://github.com/SoraDev-ID/py-analysis-tool/actions/workflows/build-pycdc.yml/badge.svg)](https://github.com/SoraDev-ID/py-analysis-tool/actions/workflows/build-pycdc.yml)

# py-analysis-tool

Educational toolkit for inspecting Python bytecode and packaged application formats.

## Use cases
- Learn how the CPython interpreter stores compiled code
- Recover source from legacy projects where only `.pyc` remains
- Audit packaged Python applications for internal review

## Install

```bash
git clone https://github.com/SoraDev-ID/py-analysis-tool.git
cd py-analysis-tool
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```

### Optional: build pycdc (native decompiler)

On Windows, one-shot:

```bat
build_all.bat
```

Or just pycdc:

```bat
scripts\build_pycdc.bat
```

## Prebuilt pycdc (no compiler needed)

Download a prebuilt pycdc binary from GitHub Releases instead of building from source:

```bash
python -m py_analysis_tool.main --fetch-pycdc sample.pyc -o out
```

## Usage

```bash
# Inspect a single .pyc
python -m py_analysis_tool.main sample.pyc -o out/

# Extract + inspect a packaged executable
python -m py_analysis_tool.main app.exe -o out/

# Recursive, verbose, HTML report
python -m py_analysis_tool.main ./dist --recursive --verbose --report report.html
```

## CLI flags

| Flag | Description |
|------|-------------|
| `-o, --output` | Output directory (default `./out`) |
| `-r, --recursive` | Walk directories recursively |
| `-v, --verbose` | Verbose logging |
| `--engine` | Force engine: `auto`, `pycdc`, `uncompyle6`, `decompyle3`, `dis` |
| `--keep-pyc` | Keep intermediate `.pyc` files |
| `--report` | Emit HTML report at given path |
| `--auto-build-pycdc` | Build pycdc from source on first run if missing |
| `--fetch-pycdc` | Download prebuilt pycdc from GitHub Releases |

## Engines

| Engine | Range | Notes |
|--------|-------|-------|
| pycdc  | 3.6 – 3.13 | Native C++ decompiler, preferred |
| decompyle3 | 3.7 – 3.8 | Pure Python |
| uncompyle6 | 2.7 – 3.8 | Pure Python |
| dis    | any   | Disassembly only (fallback) |

## License
MIT