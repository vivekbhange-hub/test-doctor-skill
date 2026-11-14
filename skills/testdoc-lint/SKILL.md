---
name: testdoc-lint
description: >-
  Scans test files (Python unittest and pytest, JavaScript and TypeScript Jest, Vitest and Mocha,
  Go, Java JUnit) for tests that cannot fail or that hide failures: no assertions, assertTrue(True),
  not-None-only checks, empty bodies, expect() with no matcher, skips without a reason, sleeps,
  swallowed exceptions, commented-out assertions and snapshot-only tests. Then fixes each one so
  it can fail. Use when the user says "are my tests any good", "find tests that never fail",
  "audit our test quality", "this test passes but checks nothing", "lint my tests", or "why did
  this bug get past the tests".
argument-hint: "[test directory or files]"
---

# testdoc-lint: tests that cannot fail

A green suite only means something if the tests could have been red. `weak_tests.py` scans test
files for the patterns that make a test pass no matter what the code does, with a rule id,
severity and `file:line` for each. You then fix them one by one, checking each fix can fail.

## Inputs

- A test directory or specific test files. Python is parsed with `ast`; JS/TS, Go and Java use
  pattern matching, so expect a few misses and the odd false alarm.
- Commands below say `python3`; on Windows use `python` (or `py -3`).

## Outputs

- `testdoc/weak-tests.md`: findings by rule and by location.
- Fixed tests, grouped in one commit per rule or per file, each shown to fail when the code is wrong.
- A list of findings you chose not to fix, with the reason.

## Steps

1. **Confirm permission.** Scan and edit tests only in a repository the user owns or is
   authorized to change.

2. **Scan.**
   ```
   python3 "${CLAUDE_SKILL_DIR}/weak_tests.py" tests -o testdoc/weak-tests.md
   ```
   Useful flags: `--min-severity medium`, `--ignore WT007,WT010` for rules the project accepts,
   `--json` for scripts, and `--fail-on high` to make it a CI gate (exit code 1).

3. **Read the count line first.** If more than a third of the tests have findings, say so before
   fixing anything: the suite's green status has been overstated and the user should know.

4. **Fix high findings first**, one rule at a time:

   | Rule | What it means | Fix |
   |---|---|---|
   | WT001 | No assertion | State the expected result and assert it; if the point is "does not raise", assert that explicitly |
   | WT002 | Assertion cannot fail | Replace with the real expected value from the spec or code |
   | WT004 | Empty test | Write it, or delete it and open an issue; an empty test is a lie |
   | WT005 | `expect(x)` with no matcher | Add the matcher (`.toBe`, `.toEqual`, `.toThrow`) |
   | WT008 | Broad exception swallowed | Use the framework's raises or `expect(...).toThrow`, or re-raise |
   | WT003 | Only not-None | Assert the value, its type and a key field |
   | WT006 | Skipped, no reason | Add a reason and ticket, or re-enable it and fix it |
   | WT009 | Commented-out assertion | Restore it and fix the failure it was hiding, or delete it |
   | WT007 | Sleep | Wait on a condition or fake the clock; see `testdoc-flaky` |
   | WT010 | Snapshot only | Add one explicit assertion on the property that matters |

5. **For every fix, make the test fail once.** Break the code under test in the smallest way
   (flip a comparison, return a constant), run the test, confirm it goes red, then restore the
   code. This is the same check `testdoc-write` requires. If the fixed test stays green, it is
   still weak.

6. **Suppress deliberately.** A finding that is correct for a reason (a smoke test that only needs
   to not crash) gets `# testdoc: ignore WT001` or `// testdoc: ignore WT001` on the line or the
   line above, plus the reason in a comment.

7. **Rerun the scan** and show before and after counts. Report what remains and why.

## Decision rules

- Fix by what the code is supposed to do, not by what it currently returns. Pasting today's
  output into an assertion turns a bug into a spec.
- Smoke tests ("imports", "app boots") may legitimately have no assertion; keep them, suppress
  WT001 with a comment, and keep them few.
- A not-None check followed by field checks is fine; the scanner flags only tests where it is
  the sole assertion.
- If the code under test is wrong and the strengthened test fails, that is the point: report the
  bug, do not weaken the test back.
- Rule IDs are stable (WT001 to WT010). Quote them in commit messages.

## What NOT to do

- Do not "fix" a finding by adding `assert True`, `expect(x).toBeDefined()` or a bare `try/except`.
- Do not delete weak tests just to make the report clean without telling the user.
- Do not generate snapshot files to replace assertions you could write by hand.
- Do not change production code while linting tests unless the user asks.
- Do not treat a clean scan as proof the tests are good: the rules find only common patterns.
