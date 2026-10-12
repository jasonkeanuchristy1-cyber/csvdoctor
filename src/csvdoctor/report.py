"""Human-readable rendering of a :class:`~csvdoctor.diagnose.Report`."""

from __future__ import annotations

from typing import List

from .diagnose import DELIMITER_NAMES, ENCODING_NAMES, Issue, Report

_COLORS = {"error": "31", "warning": "33", "info": "36", "dim": "2", "bold": "1", "ok": "32"}
_LABELS = {"error": "ERROR  ", "warning": "WARNING", "info": "INFO   "}


def _paint(text: str, style: str, color: bool) -> str:
    return f"\033[{_COLORS[style]}m{text}\033[0m" if color else text


def _fix_hint(issue: Issue) -> str:
    if issue.fix == "auto":
        return "fixed by `csvdoctor fix`"
    if issue.fix == "manual":
        return "needs manual review"
    return f"fix with `csvdoctor fix {issue.fix}`"


def _rows_hint(issue: Issue) -> str:
    if not issue.rows:
        return ""
    shown = ", ".join(str(r) for r in issue.rows)
    extra = issue.count - len(issue.rows)
    if issue.code in {"EMPTY_ROWS", "RAGGED_ROWS", "EXTRA_DATA", "DUPLICATE_ROWS"} and extra > 0:
        shown += f" (+{extra} more)"
    elif issue.count > len(issue.rows) and issue.code not in {"MIXED_TYPES", "INCONSISTENT_DATES"}:
        shown += ", ..."
    return f"rows: {shown}"


def format_issue(issue: Issue, color: bool = False) -> List[str]:
    label = _paint(_LABELS[issue.severity], issue.severity, color)
    lines = [f"  {label} {_paint(issue.code, 'bold', color)}  {issue.message}"]
    indent = " " * 12
    rows = _rows_hint(issue)
    if rows:
        lines.append(_paint(f"{indent}{rows}", "dim", color))
    lines.append(_paint(f"{indent}-> {_fix_hint(issue)}", "dim", color))
    return lines


def format_report(path: str, report: Report, color: bool = False) -> str:
    encoding = ENCODING_NAMES.get(report.encoding, report.encoding)
    delimiter = DELIMITER_NAMES.get(report.delimiter, repr(report.delimiter))
    lines = [
        _paint(path, "bold", color),
        f"  Encoding ........ {encoding}",
        f"  Delimiter ....... {delimiter}",
        f"  Line endings .... {report.line_ending}",
        f"  Size ............ {report.data_rows} data rows x {report.columns} columns",
        "",
    ]
    if not report.issues:
        lines.append(_paint("  No problems found.", "ok", color))
        return "\n".join(lines)

    counts = report.counts()
    summary = ", ".join(
        f"{counts[sev]} {sev if sev == 'info' or counts[sev] == 1 else sev + 's'}"
        for sev in ("error", "warning", "info")
        if counts[sev]
    )
    total = len(report.issues)
    lines.append(f"  Found {total} {'issue' if total == 1 else 'issues'} ({summary})")
    lines.append("")
    for issue in report.issues:
        lines.extend(format_issue(issue, color))
        lines.append("")
    return "\n".join(lines).rstrip()
