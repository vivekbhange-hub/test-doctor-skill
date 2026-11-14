# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-13

### Added

- Five skills: `testdoc-flaky`, `testdoc-gaps`, `testdoc-lint`, `testdoc-write` and
  `testdoc-triage`.
- Two read-only agents: `flake-hunter` and `test-skeptic`.
- Helper scripts (standard library only): `junit_report.py` (flaky tests, slow tests and failure
  clusters from JUnit XML), `cov_gaps.py` (lcov, Cobertura and coverage.py JSON to a ranked
  list of untested code) and `weak_tests.py` (ten rules, WT001 to WT010, for Python, JS/TS, Go
  and Java tests).
- A fictional shop suite under `examples/`: five JUnit runs with deterministic flakes, an lcov
  file and deliberately weak tests in four languages, with generated reports under
  `examples/output/` that the test suite checks byte-for-byte.
- CI on Linux, Windows and macOS with Python 3.9, 3.12 and 3.13.
