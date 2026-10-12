"""Regenerate examples/messy.csv, a deliberately broken export used in the README.

Run:  python examples/make_messy.py
"""

from pathlib import Path

LINES = [
    "ID;Customer;Email;Signup Date;Amount;City;Notes;Email",
    "1.23457E+11;  Ana Lopez ;ana@example.com;2024-01-15;1250.50;Madrid;;ana@example.com",
    "1.23457E+11;Jos\u00e9 Garc\u00eda;jose@example.com;15/01/2024;980;M\u00e1laga;;"
    "jose@example.com",
    # "Caf\u00c3\u00a9" is what "Caf\u00e9" looks like after a UTF-8/Windows-1252 mix-up.
    "100000000003;Caf\u00c3\u00a9 Central;cafe@example.com;2024-02-03;N/A;Sevilla;;"
    "cafe@example.com",
    "",
    "100000000004;Li Wei;li@example.com;03/02/2024;12o;Bilbao;;li@example.com",
    "100000000005;Sam Ortiz;sam@example.com;2024-03-09;455.00;Vigo",
    "100000000006;Dee Park;dee@example.com;2024-03-11;300;Le\u00f3n;;dee@example.com;leftover",
    '100000000007;=HYPERLINK("http://evil.example","Click me");x@example.com;2024-03-12;75;'
    "Cadiz;;x@example.com",
    "100000000008;Mia Rossi;mia@example.com;2024-03-14;610.25;Murcia;;mia@example.com",
    "1.23457E+11;  Ana Lopez ;ana@example.com;2024-01-15;1250.50;Madrid;;ana@example.com",
]

path = Path(__file__).with_name("messy.csv")
path.write_bytes(("\r\n".join(LINES) + "\r\n").encode("cp1252"))
print(f"wrote {path} ({path.stat().st_size} bytes)")
