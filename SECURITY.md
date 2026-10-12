# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately through
[GitHub security advisories](https://github.com/jasonkeanuchristy1-cyber/csvdoctor/security/advisories/new).
You can expect an acknowledgement within a few days.

## Scope and notes

- csvdoctor parses untrusted files but never executes their contents. It reads the whole
  file into memory, so extremely large inputs can exhaust memory (a denial of service for
  the process, not a code-execution risk).
- `fix --neutralize-formulas` mitigates CSV/formula injection for files you pass on to
  spreadsheet users. It is a mitigation, not a guarantee; treat untrusted CSV with care.
- Only the latest released version receives security fixes.
