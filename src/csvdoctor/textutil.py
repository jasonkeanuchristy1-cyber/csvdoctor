"""Small text helpers shared by the diagnosing and fixing code."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional, Tuple

# Zero-width space, word joiner and BOM/zero-width no-break space.
# (ZWJ and ZWNJ are deliberately NOT here: they are meaningful in emoji and
# in several scripts, and removing them would corrupt real text.)
_INVISIBLE_RE = re.compile("[\u200b\u2060\ufeff]")


def has_invisible(text: str) -> bool:
    return _INVISIBLE_RE.search(text) is not None


def strip_invisible(text: str) -> str:
    return _INVISIBLE_RE.sub("", text)


# --- placeholder / error values ---------------------------------------------

EXCEL_ERRORS = frozenset(
    {"#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#NULL!", "#NUM!", "#N/A", "#SPILL!", "#CALC!"}
)

# Matched case-insensitively. Note that "NA" is a real value in some data
# sets (Namibia's country code, "not applicable" categories), which is why
# normalising these is always opt-in.
DEFAULT_NULL_TOKENS = frozenset({"n/a", "na", "null", "nil", "none", "nan", "missing", "-", "--"})


def is_excel_error(value: str) -> bool:
    return value[:1] == "#" and value.upper() in EXCEL_ERRORS


# Excel turns long numbers (IDs, phone numbers, card numbers) into 1.23457E+11
# when it opens a file, and the lost digits are gone for good.
_SCI_RE = re.compile(r"^[+-]?\d(\.\d+)?[eE]\+(1[1-9]|[2-9]\d)$")


def looks_like_excel_sci(value: str) -> bool:
    if not value[-1:].isdigit() or ("E" not in value and "e" not in value):
        return False
    return _SCI_RE.match(value) is not None


# CSV/formula injection: cells that a spreadsheet may execute as a formula.
_FORMULA_STARTS = ("=", "@", "+", "-")
FORMULA_RE = re.compile(r"""^(=|@|[+\-][A-Za-z(@|\\'"=\[])""")


def looks_like_formula(value: str) -> bool:
    return value[:1] in _FORMULA_STARTS and FORMULA_RE.match(value) is not None


# --- mojibake ----------------------------------------------------------------


def _repair_once(text: str) -> Optional[str]:
    for codec in ("cp1252", "latin-1"):
        try:
            repaired = text.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired != text:
            return repaired
    return None


def repair_mojibake(text: str) -> Optional[str]:
    """Undo "UTF-8 decoded as Windows-1252/Latin-1" damage (e.g. 'CafÃ©').

    Returns the repaired string, or None if the text does not look damaged.
    The round trip must succeed exactly, so correct text is left alone. Text
    that was mangled more than once is repaired repeatedly.
    """
    if text.isascii():
        return None
    result = text
    for _ in range(3):
        step = _repair_once(result)
        if step is None:
            break
        result = step
    return result if result != text else None


def normalize_cell(text: str) -> Tuple[str, bool, bool, bool]:
    """Clean one cell until it stops changing.

    Returns ``(cleaned, trimmed, removed_invisible, repaired_mojibake)``.
    Trimming can make mojibake repairable and repairing mojibake can reveal
    spaces or zero-width characters, so the steps repeat until stable. That
    makes the whole operation idempotent: cleaning clean text changes nothing.
    """
    if text.isascii() and text == text.strip():
        return text, False, False, False  # fast path: nothing to do
    trimmed = invisible = mojibake = False
    for _ in range(4):
        before = text
        if has_invisible(text):
            text = strip_invisible(text)
            invisible = True
        stripped = text.strip()
        if stripped != text:
            text = stripped
            trimmed = True
        if not text.isascii():
            repaired = repair_mojibake(text)
            if repaired is not None:
                text = repaired
                mojibake = True
        if text == before:
            break
    return text, trimmed, invisible, mojibake


# --- value classification ----------------------------------------------------

_NUMBER_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")
_BOOLS = frozenset({"true", "false", "yes", "no"})

_NUMERIC_DATES = (
    (
        "YYYY-MM-DD",
        re.compile(
            r"^\d{4}-\d{1,2}-\d{1,2}"
            r"([T ]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
        ),
    ),
    ("YYYY/MM/DD", re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")),
    ("DD/MM/YYYY (or MM/DD/YYYY)", re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")),
    ("DD-MM-YYYY (or MM-DD-YYYY)", re.compile(r"^\d{1,2}-\d{1,2}-\d{2,4}$")),
    ("DD.MM.YYYY", re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$")),
)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_NAMED_DATES = (
    ("D Mon YYYY", re.compile(r"^\d{1,2} " + _MONTH + r",? \d{4}$", re.IGNORECASE)),
    ("Mon D, YYYY", re.compile(r"^" + _MONTH + r" \d{1,2},? \d{4}$", re.IGNORECASE)),
)
_MONTH_PREFIXES = frozenset(
    {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}
)

_NUMBER = ("number", None)
_BOOL = ("bool", None)
_TEXT = ("text", None)


@lru_cache(maxsize=65536)
def classify(value: str) -> Tuple[str, Optional[str]]:
    """Classify a non-empty, cleaned value.

    Returns ``(family, detail)`` where family is one of ``number``, ``date``,
    ``bool`` or ``text``; detail is the date format label for dates.
    Results are cached: real columns repeat the same values constantly.
    """
    first = value[0]
    if first.isascii() and first.isdigit():
        if value.isascii() and value.isdigit():
            return _NUMBER
        if _NUMBER_RE.match(value) or _THOUSANDS_RE.match(value):
            return _NUMBER
        for label, pattern in _NUMERIC_DATES:
            if pattern.match(value):
                return ("date", label)
            # A day-first named date ("15 Jan 2024") also starts with a digit.
        for label, pattern in _NAMED_DATES:
            if pattern.match(value):
                return ("date", label)
        return _TEXT
    if first in "+-.":
        if _NUMBER_RE.match(value) or _THOUSANDS_RE.match(value):
            return _NUMBER
        return _TEXT
    if value[:3].lower() in _MONTH_PREFIXES:
        for label, pattern in _NAMED_DATES:
            if pattern.match(value):
                return ("date", label)
    if value.lower() in _BOOLS:
        return _BOOL
    return _TEXT
