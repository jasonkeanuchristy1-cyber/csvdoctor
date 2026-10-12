"""Find problems in a parsed CSV :class:`~csvdoctor.reader.Table`."""

from __future__ import annotations

import codecs
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .reader import Table
from .textutil import (
    DEFAULT_NULL_TOKENS,
    classify,
    is_excel_error,
    looks_like_excel_sci,
    looks_like_formula,
    normalize_cell,
)

MAX_SAMPLES = 8
SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}

ENCODING_NAMES = {
    "utf-8": "UTF-8",
    "utf-8-sig": "UTF-8 (with BOM)",
    "utf-16": "UTF-16",
    "utf-16-le": "UTF-16 LE",
    "utf-16-be": "UTF-16 BE",
    "utf-32": "UTF-32",
    "cp1252": "Windows-1252",
    "latin-1": "ISO-8859-1 (Latin-1)",
}
DELIMITER_NAMES = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}


@dataclass
class Issue:
    """One problem found in a file.

    ``fix`` says how csvdoctor can resolve it: ``"auto"`` (done by
    ``csvdoctor fix``), a command line flag such as ``"--dedupe"`` (opt-in),
    or ``"manual"`` (needs a human).
    """

    code: str
    severity: str
    message: str
    rows: List[int] = field(default_factory=list)
    count: int = 0
    columns: List[str] = field(default_factory=list)
    fix: str = "manual"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Report:
    encoding: str
    bom: bool
    delimiter: str
    line_ending: str
    data_rows: int
    columns: int
    issues: List[Issue] = field(default_factory=list)

    def counts(self) -> Dict[str, int]:
        tally = {"error": 0, "warning": 0, "info": 0}
        for issue in self.issues:
            tally[issue.severity] += 1
        return tally

    def worst(self) -> Optional[str]:
        if not self.issues:
            return None
        return max((i.severity for i in self.issues), key=SEVERITY_RANK.__getitem__)

    def at_least(self, severity: str) -> List[Issue]:
        floor = SEVERITY_RANK[severity]
        return [i for i in self.issues if SEVERITY_RANK[i.severity] >= floor]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "encoding": self.encoding,
            "bom": self.bom,
            "delimiter": self.delimiter,
            "line_ending": self.line_ending,
            "data_rows": self.data_rows,
            "columns": self.columns,
            "summary": self.counts(),
            "issues": [i.to_dict() for i in self.issues],
        }


class _Bucket:
    """Counts affected cells and remembers the first few row numbers."""

    __slots__ = ("count", "rows", "row_count", "_last")

    def __init__(self) -> None:
        self.count = 0
        self.row_count = 0
        self.rows: List[int] = []
        self._last = -1

    def add(self, row_number: int) -> None:
        self.count += 1
        if row_number != self._last:  # rows are visited in ascending order
            self._last = row_number
            self.row_count += 1
            if len(self.rows) < MAX_SAMPLES:
                self.rows.append(row_number)

    def __bool__(self) -> bool:
        return self.count > 0


def _plural(n: int, singular: str, plural: Optional[str] = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _is_blank(row: List[str]) -> bool:
    return all(not cell.strip() for cell in row)


def _col_name(header: List[str], index: int) -> str:
    name = header[index].strip() if index < len(header) else ""
    return name or f"column {index + 1}"


def _tally(counter: "Counter[str]", limit: int = 4) -> str:
    parts = [f'"{value}" x{n}' for value, n in counter.most_common(limit)]
    if len(counter) > limit:
        parts.append("...")
    return ", ".join(parts)


def _shorten(value: str, limit: int = 24) -> str:
    return value if len(value) <= limit else value[: limit - 3] + "..."


def is_utf8(codec_name: str) -> bool:
    return codecs.lookup(codec_name).name in ("utf-8", "utf-8-sig")


def diagnose(table: Table, null_tokens: Iterable[str] = DEFAULT_NULL_TOKENS) -> Report:
    """Inspect ``table`` and return a :class:`Report` of everything wrong."""
    null_set = frozenset(t.lower() for t in null_tokens)
    rows = table.rows
    issues: List[Issue] = []

    header_index = next((i for i, row in enumerate(rows) if not _is_blank(row)), None)
    report = Report(
        encoding=table.encoding,
        bom=table.bom,
        delimiter=table.delimiter,
        line_ending=table.line_ending,
        data_rows=0,
        columns=0,
    )
    if header_index is None:
        issues.append(Issue("EMPTY_FILE", "error", "The file contains no data."))
        report.issues = issues
        return report

    header = rows[header_index]
    width = len(header)
    report.columns = width
    report.data_rows = sum(1 for r in rows[header_index + 1 :] if not _is_blank(r))

    # ---- file level ---------------------------------------------------------
    pretty_encoding = ENCODING_NAMES.get(table.encoding, table.encoding)
    if not is_utf8(table.encoding):
        note = (
            " (guessed: the bytes are not valid UTF-8 or Windows-1252)"
            if table.encoding == "latin-1"
            else ""
        )
        issues.append(
            Issue(
                "ENCODING",
                "warning",
                f"File is encoded as {pretty_encoding}{note}, not UTF-8. Accented "
                "characters and symbols may break in other tools.",
                fix="auto",
            )
        )
    elif table.bom:
        issues.append(
            Issue(
                "BOM",
                "info",
                "File starts with a UTF-8 byte-order mark. Some tools show it as stray "
                "characters in the first header (Excel, however, needs it to read UTF-8).",
                fix="auto",
            )
        )
    if table.delimiter != ",":
        name = DELIMITER_NAMES.get(table.delimiter, repr(table.delimiter))
        issues.append(
            Issue(
                "DELIMITER",
                "info",
                f"Fields are separated by a {name}, not a comma. Many tools assume commas.",
                fix="auto",
            )
        )
    if table.line_ending == "mixed":
        used = ", ".join(f"{n} x{c}" for n, c in table.line_endings.items() if c)
        issues.append(
            Issue(
                "LINE_ENDINGS",
                "warning",
                f"Mixed line endings ({used}).",
                fix="auto",
            )
        )
    if table.had_nul:
        issues.append(
            Issue(
                "NUL_BYTES",
                "warning",
                "File contains NUL characters (removed on read).",
                fix="auto",
            )
        )

    # ---- structure ----------------------------------------------------------
    blank_rows = [i + 1 for i, row in enumerate(rows) if _is_blank(row)]
    if blank_rows:
        issues.append(
            Issue(
                "EMPTY_ROWS",
                "warning",
                f"{_plural(len(blank_rows), 'empty row')} (blank lines or only empty cells).",
                rows=blank_rows[:MAX_SAMPLES],
                count=len(blank_rows),
                fix="auto",
            )
        )

    short_rows: List[int] = []
    long_rows: List[int] = []
    extra_data_rows: List[int] = []
    for i in range(header_index + 1, len(rows)):
        row = rows[i]
        if _is_blank(row) or len(row) == width:
            continue
        if len(row) < width:
            short_rows.append(i + 1)
        elif _is_blank(row[width:]):
            long_rows.append(i + 1)
        else:
            extra_data_rows.append(i + 1)
    ragged = sorted(short_rows + long_rows)
    if ragged:
        parts = []
        if short_rows:
            parts.append(f"{len(short_rows)} too short")
        if long_rows:
            parts.append(f"{len(long_rows)} with extra empty fields")
        issues.append(
            Issue(
                "RAGGED_ROWS",
                "error",
                f"Wrong number of fields in {_plural(len(ragged), 'row')} (the header has "
                f"{width}): {', '.join(parts)}.",
                rows=ragged[:MAX_SAMPLES],
                count=len(ragged),
                fix="auto",
            )
        )
    if extra_data_rows:
        issues.append(
            Issue(
                "EXTRA_DATA",
                "error",
                "Real data beyond the last header column in "
                f"{_plural(len(extra_data_rows), 'row')}. This usually means an unquoted "
                "delimiter inside a value (e.g. a comma in 'Smith, John').",
                rows=extra_data_rows[:MAX_SAMPLES],
                count=len(extra_data_rows),
                fix="manual",
            )
        )

    # ---- headers ------------------------------------------------------------
    empty_header_cols = [j for j, h in enumerate(header) if not h.strip()]
    if empty_header_cols:
        issues.append(
            Issue(
                "EMPTY_HEADERS",
                "warning",
                f"{_plural(len(empty_header_cols), 'column')} without a header name "
                f"(position {', '.join(str(j + 1) for j in empty_header_cols[:MAX_SAMPLES])}).",
                count=len(empty_header_cols),
                fix="auto",
            )
        )
    seen_names: Dict[str, int] = {}
    duplicate_names: List[str] = []
    for h in header:
        key = h.strip().casefold()
        if not key:
            continue
        seen_names[key] = seen_names.get(key, 0) + 1
        if seen_names[key] == 2:
            duplicate_names.append(h.strip())
    if duplicate_names:
        issues.append(
            Issue(
                "DUPLICATE_HEADERS",
                "error",
                "Duplicate column names: "
                + ", ".join(f'"{n}"' for n in duplicate_names[:MAX_SAMPLES])
                + ". Most tools silently overwrite one of the columns.",
                columns=duplicate_names,
                count=len(duplicate_names),
                fix="auto",
            )
        )

    # ---- one pass over every cell ---------------------------------------------
    whitespace, invisible, mojibake = _Bucket(), _Bucket(), _Bucket()
    mojibake_examples: List[Tuple[str, str]] = []
    excel_errors, formulas = _Bucket(), _Bucket()
    excel_error_values: "Counter[str]" = Counter()
    null_values: "Counter[str]" = Counter()
    null_bucket = _Bucket()
    sci_columns: Dict[int, _Bucket] = {}

    families: List["Counter[str]"] = [Counter() for _ in range(width)]
    family_samples: List[Dict[str, List[Tuple[int, str]]]] = [{} for _ in range(width)]
    date_formats: List["Counter[str]"] = [Counter() for _ in range(width)]
    date_samples: List[Dict[str, List[Tuple[int, str]]]] = [{} for _ in range(width)]

    for i in range(header_index, len(rows)):
        row = rows[i]
        row_number = i + 1
        is_header = i == header_index
        for j, cell in enumerate(row):
            if not cell:
                continue
            value = cell
            if not cell.isascii() or cell != cell.strip():
                value, was_trimmed, was_invisible, was_mojibake = normalize_cell(cell)
                if was_trimmed:
                    whitespace.add(row_number)
                if was_invisible:
                    invisible.add(row_number)
                if was_mojibake:
                    mojibake.add(row_number)
                    if len(mojibake_examples) < 3:
                        mojibake_examples.append((cell.strip(), value))
            if not value:
                continue
            if is_header or j >= width:
                continue

            if is_excel_error(value):
                excel_errors.add(row_number)
                excel_error_values[value.upper()] += 1
                continue
            if value.lower() in null_set:
                null_bucket.add(row_number)
                null_values[value] += 1
                continue
            if looks_like_formula(value):
                formulas.add(row_number)
                continue
            if looks_like_excel_sci(value):
                sci_columns.setdefault(j, _Bucket()).add(row_number)

            family, detail = classify(value)
            families[j][family] += 1
            samples = family_samples[j].setdefault(family, [])
            if len(samples) < 5:
                samples.append((row_number, value))
            if detail:
                date_formats[j][detail] += 1
                fmt_samples = date_samples[j].setdefault(detail, [])
                if len(fmt_samples) < 3:
                    fmt_samples.append((row_number, value))

    if whitespace:
        issues.append(
            Issue(
                "WHITESPACE",
                "warning",
                f"{_plural(whitespace.count, 'cell')} with leading or trailing whitespace "
                "(including non-breaking spaces). This breaks lookups and joins.",
                rows=whitespace.rows,
                count=whitespace.count,
                fix="auto",
            )
        )
    if invisible:
        issues.append(
            Issue(
                "INVISIBLE_CHARS",
                "warning",
                f"{_plural(invisible.count, 'cell')} with invisible characters "
                "(zero-width space, word joiner, stray BOM).",
                rows=invisible.rows,
                count=invisible.count,
                fix="auto",
            )
        )
    if mojibake:
        shown = ", ".join(f'"{_shorten(a)}" -> "{_shorten(b)}"' for a, b in mojibake_examples)
        issues.append(
            Issue(
                "MOJIBAKE",
                "warning",
                f"{_plural(mojibake.count, 'cell')} with garbled text caused by a past encoding "
                f"mix-up ({shown}).",
                rows=mojibake.rows,
                count=mojibake.count,
                fix="auto",
            )
        )

    # ---- duplicates -----------------------------------------------------------
    first_seen: Dict[Tuple[str, ...], int] = {}
    duplicate_rows: List[int] = []
    example: Optional[Tuple[int, int]] = None
    for i in range(header_index + 1, len(rows)):
        row = rows[i]
        if _is_blank(row):
            continue
        key = tuple(cell.strip() for cell in row)
        if key in first_seen:
            duplicate_rows.append(i + 1)
            if example is None:
                example = (i + 1, first_seen[key])
        else:
            first_seen[key] = i + 1
    if duplicate_rows and example:
        issues.append(
            Issue(
                "DUPLICATE_ROWS",
                "warning",
                f"Exact duplicates of earlier rows: {len(duplicate_rows)} "
                f"(e.g. row {example[0]} repeats row {example[1]}).",
                rows=duplicate_rows[:MAX_SAMPLES],
                count=len(duplicate_rows),
                fix="--dedupe",
            )
        )

    # ---- empty columns --------------------------------------------------------
    if report.data_rows:
        empty_cols = [
            j
            for j in range(width)
            if all(j >= len(r) or not r[j].strip() for r in rows[header_index + 1 :])
        ]
        if empty_cols:
            names = [_col_name(header, j) for j in empty_cols]
            issues.append(
                Issue(
                    "EMPTY_COLUMNS",
                    "warning",
                    f"{_plural(len(names), 'column')} with no data at all: "
                    + ", ".join(f'"{n}"' for n in names[:MAX_SAMPLES])
                    + ".",
                    columns=names,
                    count=len(names),
                    fix="auto",
                )
            )

    # ---- value level ------------------------------------------------------------
    if null_bucket:
        issues.append(
            Issue(
                "NULL_TOKENS",
                "info",
                "Placeholder values standing in for 'missing': "
                f"{_tally(null_values)}. Whether they should be empty depends on your data "
                "(e.g. 'NA' can be a real country code).",
                rows=null_bucket.rows,
                count=null_bucket.count,
                fix="--normalize-nulls",
            )
        )
    if excel_errors:
        issues.append(
            Issue(
                "EXCEL_ERRORS",
                "warning",
                f"Spreadsheet error values were exported as data: {_tally(excel_error_values)}.",
                rows=excel_errors.rows,
                count=excel_errors.count,
                fix="--normalize-nulls",
            )
        )
    if sci_columns:
        names = [_col_name(header, j) for j in sorted(sci_columns)]
        total = sum(b.count for b in sci_columns.values())
        first_rows = sorted(r for b in sci_columns.values() for r in b.rows)[:MAX_SAMPLES]
        issues.append(
            Issue(
                "EXCEL_SCI_NOTATION",
                "warning",
                f"{_plural(total, 'value')} in scientific notation with a large exponent "
                "(like 1.23457E+11) in "
                + ", ".join(f'"{n}"' for n in names)
                + ". Excel rounds long IDs and phone numbers when it opens a file; the lost "
                "digits cannot be recovered. Re-export that column as text from the source.",
                rows=first_rows,
                columns=names,
                count=total,
                fix="manual",
            )
        )
    if formulas:
        issues.append(
            Issue(
                "FORMULA_INJECTION",
                "warning",
                f"Cells starting with = + - or @ that a spreadsheet may run as a formula "
                f"(CSV injection): {formulas.count}.",
                rows=formulas.rows,
                count=formulas.count,
                fix="--neutralize-formulas",
            )
        )

    # ---- column types -----------------------------------------------------------
    for j in range(width):
        fam = families[j]
        total = sum(fam.values())
        if total < 5:
            continue
        dominant, dominant_count = fam.most_common(1)[0]
        if dominant not in ("number", "date") or dominant_count == total:
            continue
        if dominant_count / total < 0.8:
            continue
        minority = total - dominant_count
        odd = sorted(
            (rn, val)
            for family, samples in family_samples[j].items()
            if family != dominant
            for rn, val in samples
        )
        examples = ", ".join(f'"{_shorten(v)}"' for _, v in odd[:3])
        issues.append(
            Issue(
                "MIXED_TYPES",
                "warning",
                f'Column "{_col_name(header, j)}" is {dominant_count * 100 // total}% '
                f"{dominant}s, plus {_plural(minority, 'value')} of another kind "
                f"(e.g. {examples}).",
                rows=[rn for rn, _ in odd[:MAX_SAMPLES]],
                columns=[_col_name(header, j)],
                count=minority,
                fix="manual",
            )
        )
    for j in range(width):
        formats = date_formats[j]
        if len(formats) < 2:
            continue
        top = formats.most_common(1)[0][0]
        rows_sample = sorted(
            rn for label, items in date_samples[j].items() if label != top for rn, _ in items
        )
        listing = ", ".join(f"{label} x{n}" for label, n in formats.most_common())
        ambiguous = any("(or" in label for label in formats)
        advice = (
            " Day/month order is ambiguous (03/02/2024 is 3 Feb or 2 Mar), so csvdoctor "
            "will not guess; pick one format at the source."
            if ambiguous
            else " Pick one format at the source."
        )
        issues.append(
            Issue(
                "INCONSISTENT_DATES",
                "warning",
                f'Column "{_col_name(header, j)}" mixes date formats: {listing}.{advice}',
                rows=rows_sample[:MAX_SAMPLES],
                columns=[_col_name(header, j)],
                count=sum(formats.values()),
                fix="manual",
            )
        )

    issues.sort(key=lambda issue: -SEVERITY_RANK[issue.severity])  # stable
    report.issues = issues
    return report
