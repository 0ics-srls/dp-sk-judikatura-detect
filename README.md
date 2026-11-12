# dp-sk-judikatura-detect

Proc-protocol v1.1 class (Python 3.12, standard library only) of the `sk-judikatura` package. Turns the `nsud-decisions` Source config into Catalog items without any network call:

- one item per calendar month of decision dates `nsud:YYYY-MM` (meta `kind`, `itemId`, `version`, `from`, `to`) from `max(annoFrom, 2005)` to the current month;
- `ids` set: ONE item `nsud:ids` with those ids (sample filter);
- key `<itemId>|v<version>`, version `1` or `1-<hash8 of refreshToken>`; `state.seen` skips emitted keys; unset (null) settings are absent.

Tests: `.venv/Scripts/python -m pytest tests`; `docker build -f Dockerfile.test .` is the ProcMon gate.
