import unittest

from csvdoctor.reader import CsvDoctorError, detect_delimiter, detect_encoding, read_table


class EncodingTests(unittest.TestCase):
    def test_plain_ascii_is_utf8(self):
        self.assertEqual(detect_encoding(b"a,b\n1,2\n"), ("utf-8", False))

    def test_utf8_with_accents(self):
        raw = "name\nJosé\n".encode("utf-8")
        self.assertEqual(detect_encoding(raw), ("utf-8", False))

    def test_utf8_bom(self):
        table = read_table(b"\xef\xbb\xbfid,name\n1,Ana\n")
        self.assertEqual(table.encoding, "utf-8-sig")
        self.assertTrue(table.bom)
        self.assertEqual(table.rows[0], ["id", "name"])  # no stray BOM character

    def test_cp1252_detected(self):
        table = read_table("name\nJos\xe9\n".encode("cp1252"))
        self.assertEqual(table.encoding, "cp1252")
        self.assertEqual(table.rows[1], ["José"])

    def test_cp1252_smart_quotes(self):
        table = read_table(b"note\n\x93hello\x94\n")
        self.assertEqual(table.encoding, "cp1252")
        self.assertEqual(table.rows[1], ["\u201chello\u201d"])

    def test_falls_back_to_latin1_for_undefined_cp1252_bytes(self):
        table = read_table(b"a\n\x81\n")  # 0x81 is undefined in cp1252
        self.assertEqual(table.encoding, "latin-1")

    def test_utf16_with_bom(self):
        table = read_table("a,b\n1,2\n".encode("utf-16"))
        self.assertEqual(table.rows, [["a", "b"], ["1", "2"]])
        self.assertTrue(table.bom)

    def test_utf16_without_bom(self):
        raw = "a,b\n1,2\n".encode("utf-16-le")
        self.assertEqual(detect_encoding(raw), ("utf-16-le", False))
        self.assertEqual(read_table(raw).rows, [["a", "b"], ["1", "2"]])

    def test_explicit_encoding_wins(self):
        table = read_table("é\n".encode("cp1252"), encoding="latin-1")
        self.assertEqual(table.encoding, "latin-1")

    def test_unknown_encoding_raises(self):
        with self.assertRaises(CsvDoctorError):
            read_table(b"a\n", encoding="not-a-codec")

    def test_wrong_explicit_encoding_raises(self):
        with self.assertRaises(CsvDoctorError):
            read_table("é".encode("cp1252"), encoding="utf-8")

    def test_empty_file(self):
        self.assertEqual(read_table(b"").rows, [])

    def test_nul_characters_removed(self):
        table = read_table(b"a,b\n1,2\x00\n")
        self.assertTrue(table.had_nul)
        self.assertEqual(table.rows[1], ["1", "2"])


class DelimiterTests(unittest.TestCase):
    def test_comma(self):
        self.assertEqual(detect_delimiter("a,b,c\n1,2,3\n"), ",")

    def test_semicolon(self):
        self.assertEqual(detect_delimiter("a;b;c\n1;2;3\n"), ";")

    def test_semicolon_with_decimal_commas(self):
        self.assertEqual(detect_delimiter("name;price\nx;1,50\ny;2,75\nz;3,10\n"), ";")

    def test_tab(self):
        self.assertEqual(detect_delimiter("a\tb\n1\t2\n"), "\t")

    def test_pipe(self):
        self.assertEqual(detect_delimiter("a|b\n1|2\n"), "|")

    def test_single_column_defaults_to_comma(self):
        self.assertEqual(detect_delimiter("a\n1\n2\n"), ",")

    def test_ignores_delimiters_inside_quotes(self):
        text = 'a;b\n"x;y";2\n"p;q";3\n'
        self.assertEqual(detect_delimiter(text), ";")

    def test_explicit_delimiter_wins(self):
        table = read_table(b"a;b,c\n1;2,3\n", delimiter=",")
        self.assertEqual(table.rows[0], ["a;b", "c"])


class StructureTests(unittest.TestCase):
    def test_quoted_newlines_stay_in_one_record(self):
        table = read_table(b'a,b\n"line1\nline2",2\n')
        self.assertEqual(len(table.rows), 2)
        self.assertEqual(table.rows[1][0], "line1\nline2")

    def test_crlf_records_with_lf_inside_quotes_are_not_mixed(self):
        table = read_table(b'a,b\r\n"x\ny",2\r\n3,4\r\n')
        self.assertEqual(table.line_ending, "CRLF")

    def test_lf(self):
        self.assertEqual(read_table(b"a,b\n1,2\n").line_ending, "LF")

    def test_mixed_line_endings(self):
        self.assertEqual(read_table(b"a,b\r\n1,2\n3,4\r\n").line_ending, "mixed")

    def test_single_line_without_terminator(self):
        self.assertEqual(read_table(b"a,b").line_ending, "none")

    def test_blank_lines_are_kept_as_empty_rows(self):
        table = read_table(b"a,b\n\n1,2\n")
        self.assertEqual(table.rows, [["a", "b"], [], ["1", "2"]])


if __name__ == "__main__":
    unittest.main()
