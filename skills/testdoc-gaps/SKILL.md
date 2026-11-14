---
name: testdoc-gaps
description: >-
  Turns a coverage file (lcov.info, Cobertura XML or coverage.py JSON) into a ranked "write these
  tests first" list: files ordered by how much of them is untested, the uncovered line ranges,
  branches never taken and functions never called, optionally limited to files changed in a git
  diff. Then guides the user through writing the first tests. Use when the user says "where
  should I add tests", "what is untested", "improve our coverage", "which files need tests
  first", "coverage report says 62%, now what", or "what did my PR leave untested".
argument-hint: "[coverage file] [--changed-since REF]"
---

# testdoc-gaps: where to write tests first

A coverage percentage says how much, not where. `cov_gaps.py` ranks files by priority (uncovered
lines multiplied by the share of the file that is uncovered), lists the exact ranges, and names
the functions nothing calls. Your job is to turn the top of that list into real tests.

## Inputs

- A coverage file: `lcov.info`, Cobertura `coverage.xml`, or coverage.py `coverage.json`. If the
  user has none, show how to produce one for their stack (`coverage json` or `coverage lcov`
  after `coverage run -m pytest`, `jest --coverage --coverageReporters=lcov`,
  `go test -coverprofile` then a converter, JaCoCo to Cobertura XML).
- Optional: a git ref to compare against, for "what did my branch leave untested".
- Commands below say `python3`; on Windows use `python` (or `py -3`).

## Outputs

- `testdoc/coverage-gaps.md`: ranked files with ranges, branches and never-called functions.
- A short plan: the 3 to 5 places to test first, each with the behaviour worth pinning down.
- New tests (through `testdoc-write`) for as many of those as the user wants.

## Steps

1. **Confirm permission.** Run the tests and read the code only in a repository the user owns or
   is authorized to work on.

2. **Make sure the coverage is fresh.** Coverage from an old commit points at the wrong lines.
   If the file is older than the last code change, regenerate it first.

3. **Run the report.**
   ```
   python3 "${CLAUDE_SKILL_DIR}/cov_gaps.py" coverage/lcov.info --top 10 -o testdoc/coverage-gaps.md
   ```
   For a pull request, limit it to the files the branch touched (this is the only time the
   script runs git):
   ```
   python3 "${CLAUDE_SKILL_DIR}/cov_gaps.py" coverage/lcov.info --changed-since origin/main
   ```
   `--threshold 80` lists only files below 80% line coverage and exits 1 if there are any, which
   suits a CI gate. `--strip-prefix /home/runner/work/app/app` shortens absolute paths.

4. **Choose targets, not files.** For each of the top files, read the "Largest untested block"
   and "Functions never called" lines, then open the code at those ranges. Pick what to test by
   risk, not by line count:
   - money, permissions, data deletion, parsing of external input: first;
   - error handling that production will hit (timeouts, empty input, not found): second;
   - getters, logging, generated code, `__repr__`: skip, and say so.

5. **State the behaviour per target** in one sentence before writing anything ("refund of a
   paid order restores stock and returns the card amount; refund of an unpaid order raises").
   This is the test's name and the check that you understand the code.

6. **Write the tests with `testdoc-write`**: one behaviour per test, each proven able to fail.
   Add them in the file next to the existing tests for that module.

7. **Re-measure.** Rerun the coverage command and the report. Show the user the before and
   after for those files, and the branches that are still never taken.

8. **Report honestly.** Coverage that rose because tests execute lines without asserting is not
   progress. Run `testdoc-lint` over the new tests, and say which gaps you left and why.

## Decision rules

- Rank by the script's order unless the user names a risk area; then restrict to that area.
- A file at 95% with two untaken branches can matter more than a 50% file of constants. Read the
  branches line before dismissing a high-percentage file.
- Branch data missing (lcov without `BRDA`, coverage.py without `--branch`): say the report is
  line-only and suggest enabling branch coverage.
- Never-called functions in a file whose other code is covered are often dead code. Ask whether to
  delete the function or test it; do not write a test just to execute dead code.
- Do not set a global coverage target. Suggest a per-file or changed-lines gate instead.

## What NOT to do

- Do not write tests that call code without asserting anything just to raise the number.
- Do not mock the unit under test, or assert on the mock, to get lines covered.
- Do not edit coverage config to exclude the gaps (`# pragma: no cover`, `istanbul ignore`)
  unless the user agrees the code is untestable by design.
- Do not rank by percentage alone: a tiny file at 0% is rarely the first target.
- Do not run `--changed-since` against a ref you did not check exists in the repo.
