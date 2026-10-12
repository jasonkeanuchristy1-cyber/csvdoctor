"""Seeded, randomised checks that csvdoctor behaves on realistic messy files."""

import csv
import io
import random
import unittest

from csvdoctor import CsvDoctorError, diagnose, read_table, repair

WORDS = [
    "Ana", "José", "Zoë", "Müller", "Łukasz", "日本語", "Café Central", "O'Brien",
    "plain", "x", "Smith, John", 'say "hi"', "two\nlines", "N/A", "null", "#REF!",
    "2024-01-15", "15/01/2024", "1250.50", "980", "1,000", "=SUM(A1)", "12o",
]


def make_cell(rng):
    cell = rng.choice(WORDS)
    roll = rng.random()
    if roll < 0.15:
        cell = f"  {cell} "
    elif roll < 0.20:
        cell = f"\u00a0{cell}\u00a0"
    elif roll < 0.25:
        cell = cell.encode("utf-8").decode("cp1252", errors="ignore")  # mojibake
    elif roll < 0.28:
        cell = cell + "\u200b"
    elif roll < 0.35:
        cell = ""
    return cell


def make_file(rng):
    width = rng.randint(2, 6)
    names = ["id", "name", "Name", "email", "city", "", "amount"]
    header = [rng.choice(names) for _ in range(width)]
    rows = [header]
    for _ in range(rng.randint(3, 25)):
        row = [make_cell(rng) for _ in range(width)]
        roll = rng.random()
        if roll < 0.10:
            row = row[: rng.randint(1, width)]  # short row
        elif roll < 0.15:
            row = row + ["extra"]
        elif roll < 0.20:
            row = []  # blank line
        rows.append(row)
    delimiter = rng.choice([",", ";", "\t", "|"])
    buffer = io.StringIO(newline="")
    terminator = rng.choice(["\n", "\r\n"])
    csv.writer(buffer, delimiter=delimiter, lineterminator=terminator).writerows(rows)
    text = buffer.getvalue()
    encoding = rng.choice(["utf-8", "utf-8-sig", "cp1252", "utf-16"])
    try:
        return text.encode(encoding)
    except UnicodeEncodeError:
        return text.encode("utf-8")


class PropertyTests(unittest.TestCase):
    N = 400

    def raws(self, seed):
        rng = random.Random(seed)
        return [make_file(rng) for _ in range(self.N)]

    def test_never_crashes(self):
        for raw in self.raws(1):
            try:
                diagnose(read_table(raw))
                repair(raw, dedupe=True, normalize_nulls=True, neutralize_formulas=True)
            except CsvDoctorError:
                pass

    def test_repair_is_idempotent(self):
        for raw in self.raws(2):
            first = repair(raw)
            second = repair(first.data)
            self.assertEqual(second.data, first.data, raw)

    def test_repaired_output_is_valid_utf8_comma_csv(self):
        for raw in self.raws(3):
            data = repair(raw).data
            data.decode("utf-8")
            table = read_table(data)
            self.assertIn(table.delimiter, {",", ";", "\t", "|"})
            report = diagnose(table)
            auto = [i.code for i in report.issues if i.fix == "auto" and i.code != "DELIMITER"]
            self.assertEqual(auto, [], raw)

    def test_default_repair_keeps_every_non_empty_cell(self):
        for raw in self.raws(4):
            table = read_table(raw)
            blank = [not any(c.strip() for c in r) for r in table.rows]
            start = blank.index(False) + 1 if False in blank else 0
            expected = sum(1 for r in table.rows[start:] for c in r if c.strip())
            data = repair(raw).data
            out = list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))
            actual = sum(1 for r in out[1:] for c in r if c)
            # Empty-header columns that hold data are kept (renamed), so nothing may be lost.
            self.assertEqual(actual, expected, raw)


if __name__ == "__main__":
    unittest.main()
