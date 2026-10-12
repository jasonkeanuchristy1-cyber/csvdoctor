# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-12

### Added
- `csvdoctor check`: diagnose a CSV file (22 checks covering encoding, delimiter, line
  endings, ragged rows, headers, whitespace, mojibake, duplicates, Excel damage, mixed
  types, inconsistent dates and CSV injection) with text or JSON output and
  configurable exit status (`--fail-on`).
- `csvdoctor fix`: write a cleaned UTF-8 copy; opt-in `--dedupe`, `--normalize-nulls`,
  `--neutralize-formulas`; `--in-place` with a `.bak` backup; stdin/stdout support.
- Python API: `read_table`, `diagnose`, `fix_table`, `render_csv`, `repair`.
- Automatic encoding detection (UTF-8/16/32 with or without BOM, Windows-1252,
  Latin-1) and delimiter detection (`,` `;` tab `|`).
- pre-commit hook definition.
