import unittest

from csvdoctor import diagnose, read_table

from .helpers import codes_for, issue_for, report_for

CLEAN = "id,name,amount\n1,Ana,10.5\n2,Bo,20\n3,Cy,30\n"


class CleanFileTests(unittest.TestCase):
    def test_clean_file_has_no_issues(self):
        report = report_for(CLEAN)
        self.assertEqual(report.issues, [])
        self.assertEqual((report.data_rows, report.columns), (3, 3))
        self.assertIsNone(report.worst())

    def test_empty_file(self):
        self.assertEqual(codes_for(""), {"EMPTY_FILE"})
        self.assertEqual(codes_for("\n\n"), {"EMPTY_FILE"})

    def test_header_only_file_is_fine(self):
        self.assertEqual(codes_for("a,b,c\n"), set())

    def test_correct_unicode_text_is_not_flagged(self):
        self.assertEqual(codes_for("name\nJosé\nZoë\n日本語\n"), set())

    def test_emoji_zwj_sequences_are_not_invisible_chars(self):
        family = "\U0001f468\u200d\U0001f469\u200d\U0001f467"
        self.assertEqual(codes_for(f"emoji\n{family}\n"), set())

    def test_phone_numbers_with_plus_are_not_formulas(self):
        self.assertNotIn("FORMULA_INJECTION", codes_for("phone\n+62 812-3456-789\n"))


class FileLevelTests(unittest.TestCase):
    def test_non_utf8_encoding(self):
        self.assertIn("ENCODING", codes_for("n\nJos\xe9\n", encoding="cp1252"))

    def test_bom(self):
        self.assertEqual(codes_for(b"\xef\xbb\xbfa,b\n1,2\n"), {"BOM"})

    def test_delimiter(self):
        self.assertEqual(codes_for("a;b\n1;2\n"), {"DELIMITER"})

    def test_mixed_line_endings(self):
        self.assertEqual(codes_for(b"a,b\r\n1,2\n3,4\r\n"), {"LINE_ENDINGS"})

    def test_nul(self):
        self.assertIn("NUL_BYTES", codes_for(b"a,b\n1,2\x00\n"))


class StructureTests(unittest.TestCase):
    def test_short_rows(self):
        issue = issue_for("a,b,c\n1,2,3\n4,5\n6,7,8\n", "RAGGED_ROWS")
        self.assertEqual(issue.rows, [3])
        self.assertEqual(issue.severity, "error")
        self.assertEqual(issue.fix, "auto")

    def test_long_rows_with_empty_extras_are_ragged(self):
        self.assertEqual(codes_for("a,b\n1,2,,\n"), {"RAGGED_ROWS"})

    def test_long_rows_with_real_data(self):
        issue = issue_for("name,city\nSmith, John,Paris\n", "EXTRA_DATA")
        self.assertEqual(issue.fix, "manual")
        self.assertEqual(issue.rows, [2])

    def test_empty_rows_including_leading_and_trailing(self):
        issue = issue_for("\na,b\n1,2\n\n,\n", "EMPTY_ROWS")
        self.assertEqual(issue.rows, [1, 4, 5])

    def test_empty_columns(self):
        issue = issue_for("a,b,c\n1,,3\n4,,6\n", "EMPTY_COLUMNS")
        self.assertEqual(issue.columns, ["b"])

    def test_empty_header_names(self):
        self.assertIn("EMPTY_HEADERS", codes_for("a,,c\n1,2,3\n"))

    def test_duplicate_headers_case_insensitive(self):
        issue = issue_for("Email,email,x\n1,2,3\n", "DUPLICATE_HEADERS")
        self.assertEqual(issue.severity, "error")


class CellTests(unittest.TestCase):
    def test_whitespace(self):
        issue = issue_for("a,b\n 1,2\n3,4 \n5\u00a0,6\n", "WHITESPACE")
        self.assertEqual(issue.count, 3)
        self.assertEqual(issue.rows, [2, 3, 4])

    def test_invisible_characters(self):
        self.assertIn("INVISIBLE_CHARS", codes_for("a\nfoo\u200bbar\n"))

    def test_mojibake(self):
        issue = issue_for("name\nCaf\u00c3\u00a9\n", "MOJIBAKE")
        self.assertIn("Café", issue.message)

    def test_duplicate_rows_ignore_whitespace_differences(self):
        issue = issue_for("a,b\n1,x\n2,y\n1, x\n", "DUPLICATE_ROWS")
        self.assertEqual(issue.rows, [4])
        self.assertEqual(issue.fix, "--dedupe")

    def test_null_tokens(self):
        issue = issue_for("a\nx\nN/A\nnull\nnull\n", "NULL_TOKENS")
        self.assertEqual(issue.count, 3)
        self.assertEqual(issue.severity, "info")

    def test_custom_null_tokens(self):
        self.assertNotIn("NULL_TOKENS", codes_for("a\nN/A\n", null_tokens=["unknown"]))
        self.assertIn("NULL_TOKENS", codes_for("a\nunknown\n", null_tokens=["unknown"]))

    def test_excel_errors(self):
        issue = issue_for("a\n#DIV/0!\n#REF!\n5\n", "EXCEL_ERRORS")
        self.assertEqual(issue.count, 2)

    def test_excel_scientific_notation(self):
        issue = issue_for("id,n\n1.23457E+11,1\n1.5E+3,2\n", "EXCEL_SCI_NOTATION")
        self.assertEqual(issue.columns, ["id"])
        self.assertEqual(issue.count, 1)  # E+3 is ordinary science, not Excel damage

    def test_formula_injection(self):
        issue = issue_for('a\n=1+1\n@SUM(A1)\n+cmd|\' /C calc\'\nplain\n', "FORMULA_INJECTION")
        self.assertEqual(issue.count, 3)


class ColumnTypeTests(unittest.TestCase):
    def test_mixed_types_in_numeric_column(self):
        text = "amount\n1\n2\n3\n4\n5\n6\n7\n8\n9\nabc\n"
        issue = issue_for(text, "MIXED_TYPES")
        self.assertEqual(issue.columns, ["amount"])
        self.assertEqual(issue.rows, [11])

    def test_genuinely_mixed_text_column_is_not_flagged(self):
        self.assertNotIn("MIXED_TYPES", codes_for("v\nabc\n1\ndef\n2\nghi\n3\n"))

    def test_too_few_values_to_judge(self):
        self.assertNotIn("MIXED_TYPES", codes_for("a\n1\n2\nx\n"))

    def test_numbers_with_thousands_separators_count_as_numbers(self):
        text = 'amount\n"1,000"\n"2,500.50"\n3\n4\n5\n'
        self.assertNotIn("MIXED_TYPES", codes_for(text))

    def test_placeholders_do_not_count_as_mixed(self):
        text = "amount\n1\n2\n3\n4\n5\nN/A\n"
        self.assertNotIn("MIXED_TYPES", codes_for(text))

    def test_inconsistent_dates(self):
        text = "d\n2024-01-01\n2024-01-02\n03/01/2024\n"
        issue = issue_for(text, "INCONSISTENT_DATES")
        self.assertEqual(issue.rows, [4])
        self.assertIn("ambiguous", issue.message)

    def test_consistent_dates_with_and_without_time_are_fine(self):
        text = "d\n2024-01-01\n2024-01-02 10:30\n2024-01-03T08:00:00Z\n"
        self.assertNotIn("INCONSISTENT_DATES", codes_for(text))

    def test_month_name_dates(self):
        text = 'd\n15 Jan 2024\n"Jan 15, 2024"\n'
        self.assertIn("INCONSISTENT_DATES", codes_for(text))


class ReportTests(unittest.TestCase):
    def test_issues_sorted_by_severity(self):
        report = report_for("a;a\n1\n 2;3\n")
        ranks = [{"error": 2, "warning": 1, "info": 0}[i.severity] for i in report.issues]
        self.assertEqual(ranks, sorted(ranks, reverse=True))
        self.assertEqual(report.worst(), "error")

    def test_to_dict_is_json_serialisable(self):
        import json

        report = diagnose(read_table(b"a;a\n1\n"))
        data = json.loads(json.dumps(report.to_dict()))
        self.assertEqual(data["summary"]["error"], 2)
        self.assertEqual(data["delimiter"], ";")

    def test_row_samples_are_capped(self):
        text = "a,b\n" + "1\n" * 50
        issue = issue_for(text, "RAGGED_ROWS")
        self.assertEqual(issue.count, 50)
        self.assertEqual(len(issue.rows), 8)


if __name__ == "__main__":
    unittest.main()
