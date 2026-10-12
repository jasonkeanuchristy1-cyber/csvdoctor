"""Read raw CSV bytes into a :class:`Table`, detecting encoding and dialect.

Real-world CSV files rarely announce how they were written. Excel in many
locales writes ``;``-delimited Windows-1252 files, databases export UTF-16,
and web tools add byte-order marks. This module works out which one it is.
"""

from __future__ import annotations

import codecs
import csv
import io
import itertools
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:  # CSV fields can legitimately be huge (embedded text, JSON, ...)
    csv.field_size_limit(2**31 - 1)
except OverflowError:  # pragma: no cover - platform dependent
    csv.field_size_limit(2**30)

CANDIDATE_DELIMITERS = (",", ";", "\t", "|")
QUOTECHAR = '"'


class CsvDoctorError(Exception):
    """Raised when a file cannot be read at all."""


@dataclass
class Table:
    """A parsed CSV file plus what we learned about how it was written."""

    rows: List[List[str]]
    encoding: str
    bom: bool
    delimiter: str
    line_endings: Dict[str, int] = field(default_factory=dict)
    had_nul: bool = False

    @property
    def line_ending(self) -> str:
        """Human readable record terminator: LF, CRLF, CR, mixed or none."""
        used = [name for name, count in self.line_endings.items() if count]
        if not used:
            return "none"
        if len(used) > 1:
            return "mixed"
        return used[0]


# --- encoding ---------------------------------------------------------------

# Order matters: the UTF-32 LE BOM starts with the UTF-16 LE BOM.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def detect_encoding(raw: bytes) -> Tuple[str, bool]:
    """Guess the encoding of ``raw``. Returns ``(codec_name, has_bom)``."""
    for bom, name in _BOMS:
        if raw.startswith(bom):
            return name, True

    # UTF-16 without a BOM: plenty of NUL bytes, all on one parity.
    sample = raw[:4096]
    if b"\x00" in sample:
        half = max(len(sample) // 2, 1)
        even_nuls = sample[0::2].count(0)
        odd_nuls = sample[1::2].count(0)
        if odd_nuls > 0.3 * half and even_nuls < 0.05 * half:
            return "utf-16-le", False
        if even_nuls > 0.3 * half and odd_nuls < 0.05 * half:
            return "utf-16-be", False

    try:
        raw.decode("utf-8")
        return "utf-8", False
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("cp1252")
        return "cp1252", False
    except UnicodeDecodeError:
        pass
    return "latin-1", False  # decodes any byte sequence


def decode(raw: bytes, encoding: Optional[str] = None) -> Tuple[str, str, bool]:
    """Decode ``raw``. Returns ``(text, codec_name, has_bom)``."""
    detected, bom = detect_encoding(raw)
    name = encoding or detected
    if encoding and bom and codecs.lookup(encoding).name == "utf-8":
        name = "utf-8-sig"
    try:
        return raw.decode(name), name, bom
    except (UnicodeDecodeError, LookupError) as exc:
        raise CsvDoctorError(f"Cannot decode file as {name}: {exc}") from exc


# --- dialect ----------------------------------------------------------------


def detect_delimiter(text: str, sample_chars: int = 200_000, sample_rows: int = 200) -> str:
    """Pick the delimiter that splits the first rows most consistently."""
    sample = text[:sample_chars]
    best, best_score = ",", 0.0
    for delimiter in CANDIDATE_DELIMITERS:
        reader = csv.reader(io.StringIO(sample, newline=""), delimiter=delimiter)
        try:
            rows = list(itertools.islice(reader, sample_rows))
        except csv.Error:
            continue
        counts = [len(row) for row in rows if row]
        if not counts:
            continue
        # Most common field count; on a tie prefer the wider split.
        freq, width = max((n, w) for w, n in Counter(counts).items())
        if width < 2:
            continue
        score = freq / len(counts)
        if score > best_score:  # strict: ties go to the earlier candidate
            best, best_score = delimiter, score
    return best


_LINE_END_RE = re.compile(r'"|\r\n|\r|\n')


def count_line_endings(text: str) -> Dict[str, int]:
    """Count record terminators, ignoring newlines inside quoted fields."""
    names = {"\r\n": "CRLF", "\n": "LF", "\r": "CR"}
    counts = {"LF": 0, "CRLF": 0, "CR": 0}
    in_quotes = False
    for match in _LINE_END_RE.finditer(text):
        token = match.group()
        if token == QUOTECHAR:
            in_quotes = not in_quotes
        elif not in_quotes:
            counts[names[token]] += 1
    return counts


# --- public entry point -----------------------------------------------------


def read_table(
    raw: bytes, encoding: Optional[str] = None, delimiter: Optional[str] = None
) -> Table:
    """Parse ``raw`` CSV bytes, detecting encoding and delimiter if not given."""
    text, name, bom = decode(raw, encoding)
    had_nul = "\x00" in text
    if had_nul:
        text = text.replace("\x00", "")
    chosen = delimiter or detect_delimiter(text)
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=chosen))
    except csv.Error as exc:
        raise CsvDoctorError(f"Cannot parse file as CSV: {exc}") from exc
    return Table(
        rows=rows,
        encoding=name,
        bom=bom,
        delimiter=chosen,
        line_endings=count_line_endings(text),
        had_nul=had_nul,
    )
