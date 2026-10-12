"""csvdoctor: diagnose and repair messy CSV files."""

__version__ = "0.1.0"

from .diagnose import Issue, Report, diagnose  # noqa: E402
from .fix import FixResult, Repaired, fix_table, render_csv, repair  # noqa: E402
from .reader import CsvDoctorError, Table, read_table  # noqa: E402

__all__ = [
    "CsvDoctorError",
    "FixResult",
    "Issue",
    "Repaired",
    "Report",
    "Table",
    "__version__",
    "diagnose",
    "fix_table",
    "read_table",
    "render_csv",
    "repair",
]
