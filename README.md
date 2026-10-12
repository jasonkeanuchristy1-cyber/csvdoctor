# csvdoctor

[![CI](https://github.com/jasonkeanuchristy1-cyber/csvdoctor/actions/workflows/ci.yml/badge.svg)](https://github.com/jasonkeanuchristy1-cyber/csvdoctor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen.svg)

**Find out what is wrong with a CSV file, and fix it, in one command.**

CSV has no standard. Every export is a small gamble: Excel writes `;`-separated
Windows-1252 in many countries, databases dump UTF-16, web tools add invisible
byte-order marks, and somebody always sorts the spreadsheet and leaves an empty
column behind. `csvdoctor` tells you *exactly* what is wrong and writes a clean,
UTF-8, comma-separated copy, without touching your original.

- **Zero dependencies.** Pure Python standard library. Works anywhere Python 3.9+ does.
- **Honest.** It re-checks its own output and tells you what it could *not* fix.
- **Safe by default.** It never silently deletes rows or blanks values. Anything
  destructive is opt-in.
- **Usable everywhere.** CLI, Python library, JSON output for scripts, and a
  [pre-commit](https://pre-commit.com) hook for CI.

## Install

```bash
pip install git+https://github.com/jasonkeanuchristy1-cyber/csvdoctor.git
# or, to keep it out of your project environments:
pipx install git+https://github.com/jasonkeanuchristy1-cyber/csvdoctor.git
```

## Quick start

```console
$ csvdoctor check examples/messy.csv
examples/messy.csv
  Encoding ........ Windows-1252
  Delimiter ....... semicolon
  Line endings .... CRLF
  Size ............ 9 data rows x 8 columns

  Found 15 issues (3 errors, 10 warnings, 2 info)

  ERROR   RAGGED_ROWS  Wrong number of fields in 1 row (the header has 8): 1 too short.
            rows: 7
            -> fixed by `csvdoctor fix`

  ERROR   EXTRA_DATA  Real data beyond the last header column in 1 row. This usually means an
                      unquoted delimiter inside a value (e.g. a comma in 'Smith, John').
            rows: 8
            -> needs manual review
  ...
```

(The full report is abridged here; [`examples/messy.csv`](examples/messy.csv) is a
real, deliberately broken file you can try it on.)

Now fix it:

```console
$ csvdoctor fix examples/messy.csv --dedupe --normalize-nulls --neutralize-formulas
Fixed examples/messy.csv -> examples/messy.fixed.csv
  - Re-encoded from Windows-1252 to UTF-8
  - Changed delimiter from semicolon to comma
  - Trimmed whitespace in 2 cells
  - Repaired garbled text in 1 cell
  - Removed 1 empty row
  - Padded 1 short row with empty fields
  - Dropped 1 empty column: "Notes"
  - Emptied 1 placeholder value (N/A, #REF!, ...)
  - Prefixed 1 formula-like cell with an apostrophe
  - Renamed duplicate columns: "Email" -> "Email_2"
  - Removed 1 duplicate row

Still needs attention (4):
(row numbers below refer to the fixed file)
  ERROR   EXTRA_DATA  ...
  WARNING EXCEL_SCI_NOTATION  ...
  WARNING MIXED_TYPES  ...
  WARNING INCONSISTENT_DATES  ...
```

The four leftovers are things no tool can safely decide for you: a row with a stray
delimiter, IDs that Excel already rounded, a `12o` typed instead of `120`, and dates
that could be day-first *or* month-first. `csvdoctor` shows you where they are and
leaves the data alone.

## What it checks

| Check | Severity | Resolved by |
| --- | --- | --- |
| `EMPTY_FILE` no data at all | error | - |
| `RAGGED_ROWS` rows with too few fields, or extra *empty* fields | error | `fix` |
| `EXTRA_DATA` real data past the last column (usually an unquoted delimiter) | error | manual |
| `DUPLICATE_HEADERS` same column name twice (most tools drop one silently) | error | `fix` renames `x_2` |
| `ENCODING` not UTF-8 (Windows-1252, Latin-1, UTF-16/32) | warning | `fix` |
| `LINE_ENDINGS` mixed CRLF / LF / CR (ignores newlines inside quoted cells) | warning | `fix` |
| `NUL_BYTES` NUL characters in the file | warning | `fix` |
| `EMPTY_ROWS` blank lines and rows of empty cells | warning | `fix` |
| `EMPTY_HEADERS` columns without a name | warning | `fix` names `column_N` |
| `EMPTY_COLUMNS` columns with no data in any row | warning | `fix` |
| `WHITESPACE` leading/trailing spaces, including non-breaking spaces | warning | `fix` |
| `INVISIBLE_CHARS` zero-width spaces, word joiners, stray BOMs | warning | `fix` |
| `MOJIBAKE` text like `CafÃ©` from a past UTF-8 / Windows-1252 mix-up | warning | `fix` |
| `DUPLICATE_ROWS` exact repeated rows | warning | `--dedupe` |
| `EXCEL_ERRORS` `#REF!`, `#DIV/0!`, `#N/A`... exported as data | warning | `--normalize-nulls` |
| `FORMULA_INJECTION` cells starting with `=`, `@`, `+cmd`... that spreadsheets may execute | warning | `--neutralize-formulas` |
| `EXCEL_SCI_NOTATION` IDs/phone numbers Excel rounded to `1.23457E+11` | warning | manual (the digits are gone) |
| `MIXED_TYPES` a mostly numeric/date column containing text like `12o` | warning | manual |
| `INCONSISTENT_DATES` several date formats in one column | warning | manual (day/month order is ambiguous) |
| `BOM` UTF-8 byte-order mark | info | `fix` (`--bom` to keep one for Excel) |
| `DELIMITER` not a comma | info | `fix` |
| `NULL_TOKENS` `N/A`, `null`, `none`, `-` standing in for "missing" | info | `--normalize-nulls` |

"`fix`" means the default `csvdoctor fix` handles it. `--flags` are opt-in because they
change or remove data: for example `NA` is a *real value* in some data sets (Namibia's
country code), so blanking placeholders is never done unless you ask.

## Command reference

```text
csvdoctor check FILE [FILE ...]   report problems, change nothing
csvdoctor fix FILE                write a cleaned copy
```

Use `-` as the file name to read from standard input.

**`check`**

| Option | Meaning |
| --- | --- |
| `--format text\|json` | human report (default) or machine-readable JSON |
| `--fail-on error\|warning\|info\|never` | exit status 1 if an issue at least this severe exists (default `error`) |
| `--encoding NAME` | skip detection and read the file as this encoding |
| `--delimiter CHAR` | skip detection (`,` `;` `tab` `pipe` or any single character) |

**`fix`**

| Option | Meaning |
| --- | --- |
| `-o, --output PATH` | where to write (`-` for stdout). Default: `<name>.fixed.csv` next to the input |
| `--in-place` | overwrite the input; a `.bak` copy of the original is kept |
| `--dedupe` | remove exact duplicate rows |
| `--normalize-nulls` | turn `N/A`, `null`, `none`, `-` and spreadsheet errors into empty cells |
| `--neutralize-formulas` | prefix formula-looking cells with `'` to prevent CSV injection |
| `--out-delimiter CHAR` | delimiter to write (default `,`) |
| `--bom` | write a UTF-8 BOM so **Excel** reads accented characters correctly |
| `--crlf` | write Windows line endings |
| `--encoding`, `--delimiter` | as for `check` |

Progress messages go to **stderr**, so `csvdoctor fix data.csv -o - | other-tool` is safe.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | no issues at or above `--fail-on` (`check`), or fixed with no errors remaining (`fix`) |
| `1` | issues found (`check`), or errors remain after fixing (`fix`) |
| `2` | usage error or unreadable file |

## Use it in CI and pre-commit

Fail a pull request when a committed CSV is broken:

```yaml
# .github/workflows/csv.yml
- run: pip install git+https://github.com/jasonkeanuchristy1-cyber/csvdoctor.git
- run: csvdoctor check data/*.csv --fail-on error
```

As a [pre-commit](https://pre-commit.com) hook:

```yaml
repos:
  - repo: https://github.com/jasonkeanuchristy1-cyber/csvdoctor
    rev: v0.1.0
    hooks:
      - id: csvdoctor
```

Machine-readable output for scripts and dashboards:

```bash
csvdoctor check export.csv --format json | jq '.files[0].summary'
```

## Use it as a library

```python
from csvdoctor import read_table, diagnose, repair

raw = open("export.csv", "rb").read()

report = diagnose(read_table(raw))
for issue in report.issues:
    print(issue.severity, issue.code, issue.message)

fixed = repair(raw, dedupe=True)      # -> Repaired(data=bytes, actions=[...], ...)
open("clean.csv", "wb").write(fixed.data)
print("\n".join(fixed.actions))
```

| Function | Purpose |
| --- | --- |
| `read_table(raw, encoding=None, delimiter=None)` | detect encoding/dialect and parse bytes into a `Table` |
| `diagnose(table)` | return a `Report` with a list of `Issue` objects (`code`, `severity`, `message`, `rows`, `fix`) |
| `fix_table(table, ...)` | return cleaned rows plus a log of what changed |
| `render_csv(rows, delimiter=",", bom=False, crlf=False)` | serialise rows to UTF-8 CSV bytes |
| `repair(raw, ...)` | all of the above in one call |

## Design principles

1. **Never lose data silently.** Dropping rows and blanking values are opt-in. Rows
   that cannot be repaired safely are left untouched and reported.
2. **Don't guess when it matters.** `03/02/2024` could be 3 February or 2 March, so
   csvdoctor reports mixed date formats instead of "fixing" them.
3. **Verify, don't claim.** After `fix`, the result is re-parsed and re-checked, and
   what remains is shown to you.
4. **Idempotent.** Running `fix` on its own output changes nothing. This is covered by
   randomised tests.

## Limitations

- The whole file is loaded into memory. Files up to a few hundred MB are fine.
- Speed is roughly 50,000 rows per second for `check` on a typical 8-column file
  (pure Python, no dependencies).
- Encoding and delimiter detection are heuristics. If it guesses wrong, pass
  `--encoding` / `--delimiter`. Windows-1252 and Latin-1 cannot be told apart with
  certainty, and csvdoctor assumes Windows-1252 whenever the bytes allow it.
- It does not validate data against a schema (for that, see
  [Frictionless](https://frictionlessdata.io/)) and does not infer or convert types.

## Contributing

Bug reports with a small sample file are the most valuable contribution: real-world
messy CSVs are exactly what makes this tool better. See [CONTRIBUTING.md](CONTRIBUTING.md)
for setup and how to add a new check.

## License

[MIT](LICENSE)
