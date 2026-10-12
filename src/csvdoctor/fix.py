"""Repair a parsed CSV :class:`~csvdoctor.reader.Table` and write it back out.

Principles:

* Never drop data silently. Removing rows (duplicates) or blanking values
  ("N/A") only happens when explicitly requested.
* Anything that cannot be repaired safely (for example rows with real data in
  extra fields) is left untouched and reported in ``FixResult.unresolved``.
"""

from __future__ import annotations

import codecs
import csv
import io
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Set, Tuple

from .diagnose import DELIMITER_NAMES, ENCODING_NAMES, is_utf8
from .reader import Table, read_table
from .textutil import (
    DEFAULT_NULL_TOKENS,
    is_excel_error,
    looks_like_formula,
    normalize_cell,
)


@dataclass
class FixResult:
    rows: List[List[str]]
    actions: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)


@dataclass
class Repaired:
    """Output of :func:`repair`: the new file bytes and what was done."""

    data: bytes
    actions: List[str]
    unresolved: List[str]
    table: Table


def _plural(n: int, singular: str, plural: Optional[str] = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def fix_table(
    table: Table,
    *,
    dedupe: bool = False,
    normalize_nulls: bool = False,
    null_tokens: Iterable[str] = DEFAULT_NULL_TOKENS,
    neutralize_formulas: bool = False,
) -> FixResult:
    """Return cleaned rows for ``table`` (the input table is not modified)."""
    null_set = frozenset(t.lower() for t in null_tokens)
    actions: List[str] = []
    unresolved: List[str] = []

    rows = [list(row) for row in table.rows]

    # 1. Clean every cell: whitespace, invisible characters, mojibake.
    trimmed = invisible = mojibake = 0
    for row in rows:
        for j, cell in enumerate(row):
            if cell:
                row[j], was_trimmed, was_invisible, was_mojibake = normalize_cell(cell)
                trimmed += was_trimmed
                invisible += was_invisible
                mojibake += was_mojibake
    if trimmed:
        actions.append(f"Trimmed whitespace in {_plural(trimmed, 'cell')}")
    if invisible:
        actions.append(f"Removed invisible characters from {_plural(invisible, 'cell')}")
    if mojibake:
        actions.append(f"Repaired garbled text in {_plural(mojibake, 'cell')}")

    # 2. Drop empty rows, remembering each survivor's original row number.
    kept: List[Tuple[int, List[str]]] = [
        (i + 1, row) for i, row in enumerate(rows) if any(row)
    ]
    dropped_blank = len(rows) - len(kept)
    if dropped_blank:
        actions.append(f"Removed {_plural(dropped_blank, 'empty row')}")
    if not kept:
        return FixResult([], actions + ["File has no data"], unresolved)

    header = kept[0][1]
    body = kept[1:]
    width = len(header)

    # 3. Ragged rows: pad short ones, trim empty extras, flag real extras.
    padded = trimmed_long = 0
    for row_number, row in body:
        if len(row) < width:
            row.extend([""] * (width - len(row)))
            padded += 1
        elif len(row) > width:
            if not any(row[width:]):
                del row[width:]
                trimmed_long += 1
            else:
                unresolved.append(
                    f"Row {row_number} has extra data beyond the {width} header columns "
                    "(probably an unquoted delimiter in a value); left as is"
                )
    if padded:
        actions.append(f"Padded {_plural(padded, 'short row')} with empty fields")
    if trimmed_long:
        actions.append(f"Trimmed empty extra fields from {_plural(trimmed_long, 'row')}")

    # 4. Drop columns that are empty in every data row. This runs before the opt-in
    #    value rewrites below, so a column of "N/A" is never mistaken for an empty one.
    if body:
        drop: Set[int] = {
            j for j in range(width) if all(j >= len(row) or not row[j] for _, row in body)
        }
        if drop:
            names = [header[j] or f"column {j + 1}" for j in sorted(drop)]
            for row in [header] + [r for _, r in body]:
                row[:] = [c for k, c in enumerate(row) if k not in drop]
            width -= len(drop)
            actions.append(
                f"Dropped {_plural(len(drop), 'empty column')}: "
                + ", ".join(f'"{n}"' for n in names)
            )

    # 5. Opt-in: placeholder values -> empty; neutralise formulas.
    if normalize_nulls:
        blanked = 0
        for _, row in body:
            for j, cell in enumerate(row[:width]):
                if cell and (is_excel_error(cell) or cell.lower() in null_set):
                    row[j] = ""
                    blanked += 1
        if blanked:
            actions.append(f"Emptied {_plural(blanked, 'placeholder value')} (N/A, #REF!, ...)")
    if neutralize_formulas:
        neutralized = 0
        for _, row in body:
            for j, cell in enumerate(row[:width]):
                if cell and looks_like_formula(cell):
                    row[j] = "'" + cell
                    neutralized += 1
        if neutralized:
            actions.append(
                f"Prefixed {_plural(neutralized, 'formula-like cell')} with an apostrophe"
            )

    # 6. Headers: fill blanks, de-duplicate.
    filled = 0
    for j in range(width):
        if not header[j]:
            header[j] = f"column_{j + 1}"
            filled += 1
    if filled:
        actions.append(f"Named {_plural(filled, 'unnamed column')} (column_N)")
    taken = {h.casefold() for h in header}
    used: Set[str] = set()
    renamed = []
    for j in range(width):
        name = header[j]
        if name.casefold() in used:
            n = 2
            while f"{name}_{n}".casefold() in taken or f"{name}_{n}".casefold() in used:
                n += 1
            new_name = f"{name}_{n}"
            renamed.append(f'"{name}" -> "{new_name}"')
            header[j] = new_name
            name = new_name
        used.add(name.casefold())
    if renamed:
        actions.append("Renamed duplicate columns: " + ", ".join(renamed))

    # 7. Opt-in: exact duplicate rows.
    if dedupe:
        seen: Set[Tuple[str, ...]] = set()
        unique: List[Tuple[int, List[str]]] = []
        for row_number, row in body:
            key = tuple(row)
            if key in seen:
                continue
            seen.add(key)
            unique.append((row_number, row))
        removed = len(body) - len(unique)
        if removed:
            actions.append(f"Removed {_plural(removed, 'duplicate row')}")
        body = unique

    return FixResult([header] + [row for _, row in body], actions, unresolved)


def render_csv(
    rows: List[List[str]], delimiter: str = ",", bom: bool = False, crlf: bool = False
) -> bytes:
    """Serialise rows as UTF-8 CSV (minimal quoting, LF line endings by default)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(
        buffer,
        delimiter=delimiter,
        lineterminator="\r\n" if crlf else "\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writerows(rows)
    data = buffer.getvalue().encode("utf-8")
    return codecs.BOM_UTF8 + data if bom else data


def repair(
    raw: bytes,
    *,
    encoding: Optional[str] = None,
    delimiter: Optional[str] = None,
    out_delimiter: str = ",",
    bom: bool = False,
    crlf: bool = False,
    dedupe: bool = False,
    normalize_nulls: bool = False,
    neutralize_formulas: bool = False,
) -> Repaired:
    """Read ``raw``, fix it, and return clean UTF-8 bytes plus a change log."""
    table = read_table(raw, encoding=encoding, delimiter=delimiter)
    result = fix_table(
        table,
        dedupe=dedupe,
        normalize_nulls=normalize_nulls,
        neutralize_formulas=neutralize_formulas,
    )
    actions: List[str] = []
    if not is_utf8(table.encoding):
        source = ENCODING_NAMES.get(table.encoding, table.encoding)
        actions.append(f"Re-encoded from {source} to UTF-8")
    if table.delimiter != out_delimiter:
        before = DELIMITER_NAMES.get(table.delimiter, repr(table.delimiter))
        after = DELIMITER_NAMES.get(out_delimiter, repr(out_delimiter))
        actions.append(f"Changed delimiter from {before} to {after}")
    if table.line_ending == "mixed":
        actions.append("Normalised mixed line endings")
    if table.had_nul:
        actions.append("Removed NUL characters")
    actions.extend(result.actions)
    return Repaired(
        data=render_csv(result.rows, out_delimiter, bom=bom, crlf=crlf),
        actions=actions,
        unresolved=result.unresolved,
        table=table,
    )
