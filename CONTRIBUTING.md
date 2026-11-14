# Contributing

Thanks for helping. This pack is small on purpose, so a few rules keep it that way.

## Ground rules

- Helper scripts use the Python standard library only, run on Python 3.9+, make no network
  calls, and produce the same bytes for the same input. The only subprocess is `git diff
  --name-only`, and only when `cov_gaps.py --changed-since` is used.
- Every script change comes with a test in `tests/`. Run the suite from the repo root:

  ```
  python -m unittest discover -s tests -v
  ```

- If your change alters what the examples produce, regenerate the committed outputs and include
  them in the same pull request:

  ```
  python examples/regenerate.py
  python examples/regenerate.py --check
  ```

- Write files with LF line endings (`.gitattributes` enforces this in git).
- Skills keep the format checked by `tests/test_repo.py`: `name` equals the folder name, the
  description says what it does and lists trigger phrases, and the body has Inputs, Outputs,
  Steps, Decision rules and "What NOT to do" sections.
- Anything quoted from tool output in the README must be copied from `examples/output/`; a test
  compares them line by line.

## Fixtures

Test data and examples must be fictional. Use reserved domains (`.example`, `.invalid`) and
fake values that are obviously fake. Never commit a real CI log, real coverage from a private
project, or a real customer's test names.

## Adding a rule to `weak_tests.py`

A new rule needs an id (the next free `WT0nn`), a severity, a test that triggers it in each
language it supports, and a test showing a nearby case that must not trigger it. False alarms
cost more than misses: a lint that cries wolf gets suppressed. Prefer a narrow rule.

## Changing the failure normaliser

`junit_report.py` strips numbers, ids, addresses and paths before clustering. A change needs a
test with two messages that must cluster together and two that must stay apart.

## Conduct

Be kind and specific. This project follows the spirit of the
[Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).

## Releasing

Bump `version` in `.claude-plugin/plugin.json` and add a matching `## [x.y.z] - YYYY-MM-DD`
section to `CHANGELOG.md`; the test suite checks that they agree.
