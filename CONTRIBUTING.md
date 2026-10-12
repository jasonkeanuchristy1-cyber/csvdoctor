# Contributing to csvdoctor

Thanks for helping! The most valuable contribution is a **small, anonymised sample of a
CSV file that csvdoctor handles badly**. Real-world mess is what makes this tool better.

## Development setup

```bash
git clone https://github.com/jasonkeanuchristy1-cyber/csvdoctor.git
cd csvdoctor
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

Run the checks before opening a pull request:

```bash
python -m pytest        # tests (unittest-style, collected by pytest)
ruff check .            # lint
```

Both also run in CI on Linux, macOS and Windows for Python 3.9 to 3.13.

## Project layout

| Path | Responsibility |
| --- | --- |
| `src/csvdoctor/reader.py` | bytes -> `Table`: encoding, delimiter, line-ending detection |
| `src/csvdoctor/textutil.py` | cell-level helpers: mojibake repair, classification, `normalize_cell` |
| `src/csvdoctor/diagnose.py` | all checks; returns a `Report` of `Issue`s |
| `src/csvdoctor/fix.py` | repairs, `render_csv`, and the one-call `repair` |
| `src/csvdoctor/report.py` | human-readable text output |
| `src/csvdoctor/cli.py` | argument parsing, exit codes, file I/O |
| `tests/` | unit tests, CLI tests, and seeded randomised property tests |

## Adding a new check

1. **Detect it** in `diagnose.py`. Add an `Issue` with a stable `UPPER_SNAKE` code, a
   severity (`error` only if downstream tools will misread the data), and a `fix` value:
   `"auto"`, an opt-in flag such as `"--dedupe"`, or `"manual"`.
2. **Fix it** in `fix.py` if it can be done *without losing information*. If a fix could
   remove or alter real data, make it opt-in behind a new CLI flag.
3. **Test it** in `tests/test_diagnose.py` and `tests/test_fix.py`. Include a test for the
   *false positive* you most worry about (for example, phone numbers starting with `+`
   must not be flagged as formulas).
4. **Document it** in the README check table and add a line to `CHANGELOG.md`.

## Ground rules

- **No runtime dependencies.** The standard library only.
- **Never lose data silently.** Destructive behaviour must be opt-in and reported.
- **Idempotence.** `repair(repair(x).data)` must equal `repair(x).data`. The property tests
  enforce this; if you break them, the fix is usually an ordering problem in cleaning.
- **Don't guess ambiguous data** (for example day/month order). Report it instead.
- Keep lines at 100 characters or fewer and code compatible with Python 3.9.

## Releasing (maintainers)

1. Update `__version__` in `src/csvdoctor/__init__.py` and move the changelog entries under
   a new version heading.
2. Commit, tag (`git tag v0.1.1`) and push the tag.
3. Create a GitHub Release from the tag. The `Release` workflow builds the package and
   publishes it to PyPI using
   [trusted publishing](https://docs.pypi.org/trusted-publishers/). Configure the trusted
   publisher on PyPI once (repository `csvdoctor`, workflow `release.yml`, environment `pypi`).
   The name `csvdoctor` may already be taken on PyPI; if so, change `name` in
   `pyproject.toml` (the import name can stay the same).
