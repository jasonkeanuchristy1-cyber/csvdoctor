import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from csvdoctor.cli import main


def run(argv, stdin=b""):
    """Run the CLI in-process. Returns (exit_code, stdout_bytes, stderr_text)."""
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="")
    err = io.StringIO()
    stdin_stream = io.TextIOWrapper(io.BytesIO(stdin))
    old_stdin = sys.stdin
    sys.stdin = stdin_stream
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
    finally:
        sys.stdin = old_stdin
    out.flush()
    return code, out.buffer.getvalue(), err.getvalue()


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, name, data):
        path = self.dir / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return str(path)


class CheckTests(CliTestCase):
    def test_clean_file_exits_zero(self):
        path = self.write("ok.csv", "a,b\n1,2\n")
        code, out, _ = run(["check", path])
        self.assertEqual(code, 0)
        self.assertIn("No problems found", out.decode())

    def test_error_exits_one(self):
        path = self.write("bad.csv", "a,b\n1\n")
        code, out, _ = run(["check", path])
        self.assertEqual(code, 1)
        self.assertIn("RAGGED_ROWS", out.decode())

    def test_fail_on_levels(self):
        path = self.write("warn.csv", "a,b\n 1,2\n")  # whitespace warning only
        self.assertEqual(run(["check", path])[0], 0)
        self.assertEqual(run(["check", path, "--fail-on", "warning"])[0], 1)
        self.assertEqual(run(["check", path, "--fail-on", "never"])[0], 0)

    def test_info_only_with_fail_on_info(self):
        path = self.write("semi.csv", "a;b\n1;2\n")
        self.assertEqual(run(["check", path])[0], 0)
        self.assertEqual(run(["check", path, "--fail-on", "info"])[0], 1)

    def test_json_output(self):
        path = self.write("bad.csv", "a;a\n1;2\n")
        code, out, _ = run(["check", path, "--format", "json"])
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["files"][0]["path"], path)
        codes = {i["code"] for i in data["files"][0]["issues"]}
        self.assertEqual(codes, {"DUPLICATE_HEADERS", "DELIMITER"})

    def test_multiple_files_worst_wins(self):
        good = self.write("good.csv", "a,b\n1,2\n")
        bad = self.write("bad.csv", "a,b\n1\n")
        code, out, _ = run(["check", good, bad])
        self.assertEqual(code, 1)
        self.assertIn("good.csv", out.decode())
        self.assertIn("bad.csv", out.decode())

    def test_stdin(self):
        code, out, _ = run(["check", "-"], stdin=b"a,b\n1\n")
        self.assertEqual(code, 1)
        self.assertIn("RAGGED_ROWS", out.decode())

    def test_missing_file_exits_two(self):
        code, _, err = run(["check", str(self.dir / "nope.csv")])
        self.assertEqual(code, 2)
        self.assertIn("Cannot read", err)

    def test_encoding_and_delimiter_overrides(self):
        path = self.write("x.csv", "a|b;c\n1|2;3\n")
        code, out, _ = run(["check", path, "--delimiter", "pipe", "--format", "json"])
        data = json.loads(out)
        self.assertEqual(data["files"][0]["delimiter"], "|")

    def test_bad_delimiter_is_a_usage_error(self):
        path = self.write("x.csv", "a\n")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            run(["check", path, "--delimiter", "ab"])
        self.assertEqual(ctx.exception.code, 2)

    def test_no_color_codes_when_not_a_tty(self):
        path = self.write("bad.csv", "a,b\n1\n")
        _, out, _ = run(["check", path])
        self.assertNotIn(b"\x1b[", out)


class FixTests(CliTestCase):
    MESSY = "ID;Name;Name\r\n1;  Ana ;x\r\n\r\n2;Bob\r\n"

    def test_default_output_name(self):
        path = self.write("data.csv", self.MESSY)
        code, _, err = run(["fix", path])
        self.assertEqual(code, 0)
        fixed = self.dir / "data.fixed.csv"
        self.assertEqual(fixed.read_text(), "ID,Name,Name_2\n1,Ana,x\n2,Bob,\n")
        self.assertIn("data.fixed.csv", err)
        self.assertEqual(Path(path).read_bytes(), self.MESSY.encode("utf-8"))  # untouched

    def test_explicit_output(self):
        path = self.write("data.csv", self.MESSY)
        out_path = str(self.dir / "clean.csv")
        self.assertEqual(run(["fix", path, "-o", out_path])[0], 0)
        self.assertTrue(os.path.exists(out_path))

    def test_stdout_keeps_stdout_clean(self):
        path = self.write("data.csv", self.MESSY)
        code, out, err = run(["fix", path, "-o", "-"])
        self.assertEqual(out.decode(), "ID,Name,Name_2\n1,Ana,x\n2,Bob,\n")
        self.assertIn("Fixed", err)

    def test_stdin_to_stdout(self):
        code, out, _ = run(["fix", "-"], stdin=b"a;b\n1;2\n")
        self.assertEqual(code, 0)
        self.assertEqual(out, b"a,b\n1,2\n")

    def test_in_place_keeps_backup(self):
        path = self.write("data.csv", self.MESSY)
        original = Path(path).read_bytes()
        self.assertEqual(run(["fix", path, "--in-place"])[0], 0)
        self.assertEqual(Path(path + ".bak").read_bytes(), original)
        self.assertEqual(Path(path).read_text(), "ID,Name,Name_2\n1,Ana,x\n2,Bob,\n")

    def test_in_place_rejects_stdin(self):
        code, _, err = run(["fix", "-", "--in-place"], stdin=b"a\n1\n")
        self.assertEqual(code, 2)
        self.assertIn("--in-place", err)

    def test_output_and_in_place_conflict(self):
        path = self.write("data.csv", "a\n1\n")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run(["fix", path, "-o", "x.csv", "--in-place"])

    def test_flags(self):
        path = self.write("data.csv", "a,b\n1,N/A\n1,N/A\n=2+2,x\n")
        out_path = str(self.dir / "o.csv")
        code, _, _ = run(
            ["fix", path, "-o", out_path, "--dedupe", "--normalize-nulls",
             "--neutralize-formulas", "--out-delimiter", "semicolon", "--bom", "--crlf"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            Path(out_path).read_bytes(), b"\xef\xbb\xbfa;b\r\n1;\r\n'=2+2;x\r\n"
        )

    def test_exit_one_when_errors_remain(self):
        path = self.write("data.csv", "name,city\nSmith, John,Paris\n")
        code, _, err = run(["fix", path, "-o", str(self.dir / "o.csv")])
        self.assertEqual(code, 1)
        self.assertIn("EXTRA_DATA", err)

    def test_warnings_that_remain_do_not_fail(self):
        text = "d\n2024-01-01\n2024-01-02\n03/01/2024\n"
        code, _, err = run(["fix", self.write("d.csv", text), "-o", str(self.dir / "o.csv")])
        self.assertEqual(code, 0)
        self.assertIn("INCONSISTENT_DATES", err)

    def test_nothing_to_fix(self):
        path = self.write("ok.csv", "a,b\n1,2\n")
        code, _, err = run(["fix", path, "-o", str(self.dir / "o.csv")])
        self.assertEqual(code, 0)
        self.assertIn("Nothing needed fixing", err)

    def test_cp1252_input_becomes_utf8(self):
        path = self.write("x.csv", "name\nJos\xe9\n".encode("cp1252"))
        run(["fix", path, "-o", str(self.dir / "o.csv")])
        self.assertEqual((self.dir / "o.csv").read_bytes(), "name\nJosé\n".encode("utf-8"))


class MiscTests(unittest.TestCase):
    def test_version(self):
        with contextlib.redirect_stdout(io.StringIO()) as buf, self.assertRaises(SystemExit) as ctx:
            main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("csvdoctor", buf.getvalue())

    def test_command_required(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            main([])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
