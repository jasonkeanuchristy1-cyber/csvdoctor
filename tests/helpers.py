"""Shared helpers for building CSV test input."""

from csvdoctor import diagnose, read_table


def report_for(text, encoding="utf-8", **kwargs):
    raw = text.encode(encoding) if isinstance(text, str) else text
    return diagnose(read_table(raw), **kwargs)


def codes_for(text, **kwargs):
    return {issue.code for issue in report_for(text, **kwargs).issues}


def issue_for(text, code, **kwargs):
    for issue in report_for(text, **kwargs).issues:
        if issue.code == code:
            return issue
    raise AssertionError(f"{code} not reported")
