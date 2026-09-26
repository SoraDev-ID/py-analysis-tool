"""Generate a self-contained HTML report of the analysis run."""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class FileReport:
    input_path: str
    kind: str                      # "pyc" | "pyinstaller" | "py2exe"
    python_version: str = "unknown"
    obfuscation: str = ""
    engine: str = ""
    status: str = ""               # "ok" | "partial" | "failed"
    outputs: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class RunReport:
    started: datetime
    finished: datetime = field(default_factory=datetime.now)
    files: list[FileReport] = field(default_factory=list)


_HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>py-analysis-tool report</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:2rem}}
h1{{margin-top:0}}
.meta{{color:#8b949e;font-size:.9rem;margin-bottom:1.5rem}}
table{{width:100%;border-collapse:collapse;font-size:.9rem}}
th,td{{text-align:left;padding:.55rem .7rem;border-bottom:1px solid #21262d;vertical-align:top}}
th{{background:#161b22;color:#8b949e;font-weight:600}}
tr:hover td{{background:#161b22}}
.ok{{color:#3fb950}} .partial{{color:#d29922}} .failed{{color:#f85149}}
code{{background:#161b22;padding:.1rem .35rem;border-radius:4px;font-size:.85em}}
</style></head>
<body>
<h1>py-analysis-tool &mdash; analysis report</h1>
<div class="meta">Started {started} &middot; Finished {finished} &middot; {count} file(s)</div>
<table>
<thead><tr>
<th>#</th><th>Input</th><th>Kind</th><th>Py version</th>
<th>Engine</th><th>Status</th><th>Notes</th><th>Outputs</th>
</tr></thead>
<tbody>
{rows}
</tbody></table>
</body></html>
"""


def _status_class(status: str) -> str:
    return status if status in ("ok", "partial", "failed") else "partial"


def _row(i: int, r: FileReport) -> str:
    outputs = "<br>".join(f"<code>{html.escape(o)}</code>" for o in r.outputs) or "&mdash;"
    note = html.escape(r.note) or "&mdash;"
    obf = f"<br><small>obfuscation: {html.escape(r.obfuscation)}</small>" if r.obfuscation else ""
    return (
        f"<tr>"
        f"<td>{i}</td>"
        f"<td><code>{html.escape(r.input_path)}</code>{obf}</td>"
        f"<td>{html.escape(r.kind)}</td>"
        f"<td>{html.escape(r.python_version)}</td>"
        f"<td>{html.escape(r.engine) or '&mdash;'}</td>"
        f"<td class='{_status_class(r.status)}'>{html.escape(r.status)}</td>"
        f"<td>{note}</td>"
        f"<td>{outputs}</td>"
        f"</tr>"
    )


def write_report(run: RunReport, path: Path) -> Path:
    rows = "\n".join(_row(i + 1, r) for i, r in enumerate(run.files))
    html_text = _HTML_TEMPLATE.format(
        started=run.started.strftime("%Y-%m-%d %H:%M:%S"),
        finished=run.finished.strftime("%Y-%m-%d %H:%M:%S"),
        count=len(run.files),
        rows=rows,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")
    return path