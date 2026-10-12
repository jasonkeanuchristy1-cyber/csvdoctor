import csv
import io
import unittest

from csvdoctor import diagnose, fix_table, read_table, render_csv, repair

from .helpers import codes_for


def fixed_rows(text, **options):
    raw = text.encode("utf-8") if isinstance(text, str) else text
    return fix_table(read_table(raw), **options)


def parse(data: bytes):
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))


class CellCleaningTests(unittest.TestCase):
    def test_trims_whitespace_and_nbsp(self):
        result = fixed_rows("a,b\n  x ,\u00a0y\u00a0\n")
        self.assertEqual(result.rows, [["a", "b"], ["x", "y"]])

    def test_removes_invisible_characters(self):
        result = fixed_rows("a\nfoo\u200bbar\n")
        self.assertEqual(result.rows[1], ["foobar"])

    def test_repairs_mojibake_but_leaves_good_text(self):
        result = fixed_rows("a\nCaf\u00c3\u00a9\nCafé\nZoë\n")
        self.assertEqual([r[0] for r in result.rows[1:]], ["Café", "Café", "Zoë"])

    def test_keeps_emoji_joiners(self):
        family = "\U0001f468\u200d\U0001f469\u200d\U0001f467"
        self.assertEqual(fixed_rows(f"a\n{family}\n").rows[1], [family])


class StructureFixTests(unittest.TestCase):
    def test_pads_short_rows(self):
        result = fixed_rows("a,b,c\n1,2,3\n4,5\n")
        self.assertEqual(result.rows[2], ["4", "5", ""])

    def test_trims_empty_extra_fields(self):
        result = fixed_rows("a,b\n1,2,,\n")
        self.assertEqual(result.rows[1], ["1", "2"])

    def test_extra_data_is_kept_and_reported(self):
        result = fixed_rows("name,city\nSmith, John,Paris\n")
        self.assertEqual(result.rows[1], ["Smith", "John", "Paris"])
        self.assertEqual(len(result.unresolved), 1)
        self.assertIn("Row 2", result.unresolved[0])

    def test_drops_empty_rows_and_columns(self):
        result = fixed_rows("\na,b,c\n1,,3\n\n4,,6\n")
        self.assertEqual(result.rows, [["a", "c"], ["1", "3"], ["4", "6"]])

    def test_header_only_file_keeps_all_columns(self):
        self.assertEqual(fixed_rows("a,b\n").rows, [["a", "b"]])

    def test_names_blank_headers(self):
        result = fixed_rows("a,,c\n1,2,3\n")
        self.assertEqual(result.rows[0], ["a", "column_2", "c"])

    def test_renames_duplicate_headers_without_collisions(self):
        result = fixed_rows("x,X,x_2,x\n1,2,3,4\n")
        header = result.rows[0]
        self.assertEqual(len({h.casefold() for h in header}), 4)
        self.assertEqual(header[0], "x")

    def test_empty_input(self):
        self.assertEqual(fixed_rows("").rows, [])


class OptInTests(unittest.TestCase):
    def test_nothing_is_dropped_or_blanked_by_default(self):
        result = fixed_rows("a,b\n1,N/A\n1,N/A\n#REF!,x\n")
        self.assertEqual(len(result.rows), 4)
        self.assertEqual(result.rows[1], ["1", "N/A"])

    def test_dedupe(self):
        result = fixed_rows("a,b\n1,x\n2,y\n1, x\n", dedupe=True)
        self.assertEqual(result.rows, [["a", "b"], ["1", "x"], ["2", "y"]])

    def test_normalize_nulls_includes_excel_errors(self):
        result = fixed_rows("a,b\nN/A,#REF!\nnull,ok\n", normalize_nulls=True)
        self.assertEqual(result.rows[1:], [["", ""], ["", "ok"]])

    def test_column_of_placeholders_is_not_dropped_as_empty(self):
        result = fixed_rows("a,b\nN/A,1\nnull,2\n", normalize_nulls=True)
        self.assertEqual(result.rows, [["a", "b"], ["", "1"], ["", "2"]])

    def test_normalize_nulls_leaves_headers_alone(self):
        result = fixed_rows("NA,b\n1,2\n", normalize_nulls=True)
        self.assertEqual(result.rows[0], ["NA", "b"])

    def test_custom_null_tokens(self):
        result = fixed_rows("a\nunknown\nN/A\n", normalize_nulls=True, null_tokens=["unknown"])
        self.assertEqual([r[0] for r in result.rows[1:]], ["", "N/A"])

    def test_neutralize_formulas(self):
        result = fixed_rows("a\n=1+1\n+62 812\nplain\n", neutralize_formulas=True)
        self.assertEqual([r[0] for r in result.rows[1:]], ["'=1+1", "+62 812", "plain"])


class RenderTests(unittest.TestCase):
    def test_quotes_only_when_needed(self):
        data = render_csv([["a", "b c"], ["x,y", 'say "hi"'], ["line1\nline2", ""]])
        self.assertEqual(
            data.decode(), 'a,b c\n"x,y","say ""hi"""\n"line1\nline2",\n'
        )

    def test_options(self):
        data = render_csv([["a", "b"]], delimiter=";", bom=True, crlf=True)
        self.assertEqual(data, b"\xef\xbb\xbfa;b\r\n")

    def test_roundtrip_preserves_awkward_values(self):
        rows = [["h1", "h2"], ["a,b", 'q"uote'], ["multi\nline", "é日本"]]
        self.assertEqual(parse(render_csv(rows)), rows)


class RepairTests(unittest.TestCase):
    MESSY = (
        "ID;Name;Name;Notes\r\n1;  Caf\xe9 ;x;\r\n\r\n2;Bob;y\r\n"
    ).encode("cp1252")

    def test_end_to_end(self):
        repaired = repair(self.MESSY)
        self.assertEqual(
            parse(repaired.data), [["ID", "Name", "Name_2"], ["1", "Café", "x"], ["2", "Bob", "y"]]
        )
        joined = " | ".join(repaired.actions)
        for expected in ("Windows-1252", "semicolon", "whitespace", "empty row", "duplicate"):
            self.assertIn(expected, joined)

    def test_output_is_clean_and_idempotent(self):
        first = repair(self.MESSY)
        report = diagnose(read_table(first.data))
        self.assertEqual(report.issues, [])
        second = repair(first.data)
        self.assertEqual(second.data, first.data)
        self.assertEqual(second.actions, [])

    def test_fixable_issues_actually_disappear(self):
        raw = "a;a\n 1;2\n\n3\n\u200b4;5;\n".encode("utf-8")
        before = {i.code for i in diagnose(read_table(raw)).issues if i.fix == "auto"}
        self.assertTrue(before)
        after = codes_for(repair(raw).data)
        self.assertFalse(before & after, before & after)

    def test_no_data_cells_lost_by_default(self):
        raw = "a;b;c\n1; x ;3\n4;5\n7;8;9;10\n1;x;3\n".encode("utf-8")
        before = sum(1 for row in read_table(raw).rows[1:] for cell in row if cell.strip())
        after = sum(1 for row in parse(repair(raw).data)[1:] for cell in row if cell)
        self.assertEqual(before, after)

    def test_output_options(self):
        data = repair(b"a;b\n1;2\n", out_delimiter="\t", bom=True, crlf=True).data
        self.assertEqual(data, b"\xef\xbb\xbfa\tb\r\n1\t2\r\n")


if __name__ == "__main__":
    unittest.main()
