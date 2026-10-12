"""Command line interface: ``csvdoctor check`` and ``csvdoctor fix``."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from typing import List, Optional, Sequence

from . import __version__
from .diagnose import SEVERITY_RANK, diagnose
from .fix import repair
from .reader import CsvDoctorError, read_table
from .report import format_issue, format_report

DELIMITER_ALIASES = {"comma": ",", "semicolon": ";", "tab": "\t", "pipe": "|", "\\t": "\t"}
# Properties of how the *output* was chosen to be written, not of the data.
FORMAT_CODES = {"ENCODING", "BOM", "DELIMITER", "LINE_ENDINGS", "NUL_BYTES"}


def _delimiter(value: str) -> str:
    value = DELIMITER_ALIASES.get(value.lower(), value)
    if len(value) != 1:
        raise argparse.ArgumentTypeError(
            f"delimiter must be a single character or one of "
            f"{', '.join(k for k in DELIMITER_ALIASES if k != chr(92) + 't')} (got {value!r})"
        )
    return value


def _read_input(path: str) -> bytes:
    if path == "-":
        return sys.stdin.buffer.read()
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise CsvDoctorError(f"Cannot read {path}: {exc.strerror or exc}") from exc


def _atomic_write(path: str, data: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".csvdoctor-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _use_color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="csvdoctor",
        description="Diagnose and repair messy CSV files.",
    )
    parser.add_argument("--version", action="version", version=f"csvdoctor {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{check,fix}")

    def add_input_options(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--encoding", help="input encoding (default: detect automatically)", metavar="NAME"
        )
        p.add_argument(
            "--delimiter",
            type=_delimiter,
            help="input delimiter: a character, or comma/semicolon/tab/pipe (default: detect)",
            metavar="CHAR",
        )

    check = sub.add_parser("check", help="report problems without changing anything")
    check.add_argument("files", nargs="+", help="CSV file(s) to check, or - for stdin")
    check.add_argument("--format", choices=("text", "json"), default="text")
    check.add_argument(
        "--fail-on",
        choices=("error", "warning", "info", "never"),
        default="error",
        help="exit with status 1 if an issue of at least this severity is found "
        "(default: error)",
    )
    add_input_options(check)

    fix = sub.add_parser("fix", help="write a cleaned copy of a CSV file")
    fix.add_argument("file", help="CSV file to fix, or - for stdin")
    target = fix.add_mutually_exclusive_group()
    target.add_argument("-o", "--output", help="output path, or - for stdout")
    target.add_argument(
        "--in-place", action="store_true", help="overwrite the input (a .bak copy is kept)"
    )
    add_input_options(fix)
    fix.add_argument("--dedupe", action="store_true", help="remove exact duplicate rows")
    fix.add_argument(
        "--normalize-nulls",
        action="store_true",
        help="turn N/A, NULL, none, -, and spreadsheet errors (#REF!, ...) into empty cells",
    )
    fix.add_argument(
        "--neutralize-formulas",
        action="store_true",
        help="prefix cells that look like formulas with ' (prevents CSV injection)",
    )
    fix.add_argument(
        "--out-delimiter", type=_delimiter, default=",", metavar="CHAR", help="default: comma"
    )
    fix.add_argument(
        "--bom", action="store_true", help="write a UTF-8 BOM (makes Excel read UTF-8 correctly)"
    )
    fix.add_argument("--crlf", action="store_true", help="use Windows line endings")
    return parser


def _cmd_check(args: argparse.Namespace) -> int:
    color = _use_color() and args.format == "text"
    exit_code = 0
    results = []
    blocks: List[str] = []
    for path in args.files:
        raw = _read_input(path)
        table = read_table(raw, encoding=args.encoding, delimiter=args.delimiter)
        report = diagnose(table)
        label = "<stdin>" if path == "-" else path
        results.append({"path": label, **report.to_dict()})
        blocks.append(format_report(label, report, color))
        if args.fail_on != "never" and report.at_least(args.fail_on):
            exit_code = 1
    if args.format == "json":
        print(json.dumps({"version": __version__, "files": results}, indent=2, ensure_ascii=False))
    else:
        print("\n\n".join(blocks))
    return exit_code


def _cmd_fix(args: argparse.Namespace) -> int:
    raw = _read_input(args.file)
    repaired = repair(
        raw,
        encoding=args.encoding,
        delimiter=args.delimiter,
        out_delimiter=args.out_delimiter,
        bom=args.bom,
        crlf=args.crlf,
        dedupe=args.dedupe,
        normalize_nulls=args.normalize_nulls,
        neutralize_formulas=args.neutralize_formulas,
    )

    to_stdout = args.output == "-" or (args.file == "-" and not args.output and not args.in_place)
    if args.in_place and args.file == "-":
        raise CsvDoctorError("--in-place cannot be used with stdin")
    if to_stdout:
        destination = "<stdout>"
    elif args.in_place:
        destination = args.file
        _atomic_write(args.file + ".bak", raw)
    elif args.output:
        destination = args.output
    else:
        stem, ext = os.path.splitext(args.file)
        destination = f"{stem}.fixed{ext or '.csv'}"

    if to_stdout:
        sys.stdout.buffer.write(repaired.data)
        sys.stdout.buffer.flush()
    else:
        _atomic_write(destination, repaired.data)

    out = sys.stderr  # keep stdout clean for piping
    source = "<stdin>" if args.file == "-" else args.file
    print(f"Fixed {source} -> {destination}", file=out)
    if repaired.actions:
        for action in repaired.actions:
            print(f"  - {action}", file=out)
    else:
        print("  - Nothing needed fixing", file=out)

    # Re-check the result so nothing is claimed that isn't true.
    after = diagnose(
        read_table(repaired.data, encoding="utf-8-sig" if args.bom else "utf-8"),
    )
    remaining = [i for i in after.issues if i.code not in FORMAT_CODES]
    exit_code = 0
    if remaining:
        print(f"\nStill needs attention ({len(remaining)}):", file=out)
        print("(row numbers below refer to the fixed file)", file=out)
        for issue in remaining:
            for line in format_issue(issue, color=False):
                print(line, file=out)
        if any(SEVERITY_RANK[i.severity] >= SEVERITY_RANK["error"] for i in remaining):
            exit_code = 1
    return exit_code


def _harden_streams() -> None:
    """Never crash on a character the terminal cannot display (legacy Windows consoles)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):  # pragma: no cover - exotic stream types
                pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _harden_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return _cmd_check(args)
        return _cmd_fix(args)
    except CsvDoctorError as exc:
        print(f"csvdoctor: error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:  # e.g. `csvdoctor fix - -o - | head`
        return 0
