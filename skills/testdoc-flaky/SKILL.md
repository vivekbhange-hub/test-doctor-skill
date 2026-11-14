---
name: testdoc-flaky
description: >-
  Finds flaky tests from the JUnit XML that CI already produces: collects several runs of the
  same suite, ranks tests that both passed and failed by flake rate, guesses the cause (timing,
  shared state, network, randomness, time zone or date, resource limits) from the failure text,
  and proposes the smallest fix for that cause, never a blanket retry. Use when the user says
  "this test is flaky", "tests fail randomly in CI", "find my flaky tests", "which tests fail
  intermittently", "it passes on rerun", or "rank flaky tests".
argument-hint: "[directory or files of JUnit XML]"
---

# testdoc-flaky: which tests lie, and why

A flaky test is a test that gives different answers for the same code. CI already holds the
evidence: every run uploads a JUnit XML file. This skill collects several of them, lets
`junit_report.py` do the counting, and then you do the reading: open the failing test, find the
cause, and make the smallest change that removes it.

## Inputs

- JUnit XML from at least 3 runs of the same suite, ideally 5-10, on the same commit or on
  commits that did not touch the failing code. One run cannot show flakiness.
- Or access to the repo's CI through `gh` so you can download them.
- Commands below say `python3`; on Windows use `python` (or `py -3`).

## Outputs

- `testdoc/flaky-report.md`: the script's report (flaky, failing, slow, clusters).
- A ranked list for the user: test, flake rate, likely cause with the evidence line, the fix.
- Optionally one small change per flaky test, each in its own commit.

## Steps

1. **Confirm permission.** Only pull CI artifacts and run tests in repositories the user owns or
   is authorized to work on. Downloaded artifacts can contain secrets in logs; do not paste them.

2. **Get the runs.** If the user has no JUnit files yet, check which tool writes them (pytest
   `--junitxml=junit.xml`, jest-junit, Maven Surefire `target/surefire-reports`, Go
   `gotestsum --junitfile junit.xml`) and that the workflow uploads them with
   `actions/upload-artifact`. Then download recent runs of one workflow:
   ```
   gh run list --workflow tests.yml --limit 10 --json databaseId,conclusion,headSha
   for id in $(gh run list --workflow tests.yml --limit 10 --json databaseId --jq '.[].databaseId'); do
     gh run download "$id" --pattern 'junit*' --dir "ci-runs/$id" || true
   done
   ```
   For runs on the same commit, `gh run rerun <id>` a few times and download each result. Prefer
   that over mixed commits: a regression on one commit looks like a flake otherwise.

3. **Run the report.** Each XML file counts as one run:
   ```
   python3 "${CLAUDE_SKILL_DIR}/junit_report.py" ci-runs --top 15 -o testdoc/flaky-report.md
   ```
   Use `--run-per dir` when each run produced several XML files in one folder (monorepos), and
   `--min-runs 3` to ignore tests seen in fewer runs. `--json` gives the same data for scripts.

4. **Read the report in this order.** Consistently failing tests first (those are bugs, hand
   them to `testdoc-triage`), then flaky tests by flake rate, then failure clusters (one cluster
   across several tests means one shared cause), then slow tests (slow tests are the usual
   cause of timeouts).

5. **Classify each flaky test** by reading the failure text and then the test and the code it
   calls. The "likely cause" column is only a keyword match; confirm it in the code:

   | Cause | Evidence in the failure | Smallest fix |
   |---|---|---|
   | Timing | timeout, "waiting for", fails on slow runners | Wait for the condition (poll with a deadline, await the event), not a fixed sleep; fake the clock |
   | Ordering or shared state | UNIQUE constraint, "already exists", fails after another test | Give each test its own data (unique ids, a fresh temp dir or transaction rolled back); reset globals in teardown |
   | Network | connection refused or reset, DNS, 502/503 | Stub the HTTP client or use a local fake server; mark real-network tests as integration |
   | Randomness | different values per run, set or dict order | Seed the generator inside the test, sort before comparing, or compare sets |
   | Time zone or date | off by one day, near midnight, DST | Inject a fixed clock; build dates in UTC explicitly |
   | Resource limits | out of memory, too many open files, address in use | Close what the test opens; use port 0 for servers; lower parallelism |

6. **Prove the cause before fixing.** Reproduce it: run the test in a loop
   (`pytest path::test -x --count 50` with pytest-repeat, `go test -count=50 -run Name`,
   `jest --runInBand` repeated), shuffled order for ordering suspects, `TZ=Pacific/Auckland` for
   date suspects. If you cannot reproduce it, say so and keep the hypothesis labelled as such.

7. **Apply the smallest fix** for the proven cause, rerun the loop, and report the before and
   after flake rate. Use `testdoc-write` rules to confirm the fixed test can still fail.

8. **Quarantine only as a last resort.** If a test must stay flaky for now, skip it with a
   reason and a ticket, and tell the user it is a debt, not a fix.

## Decision rules

- A test that failed in every run is not flaky; send it to `testdoc-triage`.
- A test that failed once in 10 runs with a cause you can name is still worth fixing; a test
  that failed once and has no cause is noise until it fails again.
- Several tests in one cluster with the same message: fix the shared fixture, not each test.
- Flake rate above 80% usually means a real regression on a recent commit, not flakiness.
- Retries (`rerunfailures`, `jest.retryTimes`, `retry:` in CI) are never the fix. They hide the
  signal and slow the suite. Mention them only to say what the report would look like without them.
- A `retried in-run` entry means a retry plugin turned a failure into a pass. List those tests as
  flaky anyway, since the plugin is masking them.

## What NOT to do

- Do not recommend or add blanket retries, longer global timeouts or `sleep` as the fix.
- Do not delete or skip a flaky test without a stated reason and a follow-up.
- Do not mix runs from commits that changed the failing code and call the result a flake rate.
- Do not claim a cause you did not reproduce or see in the code; label it a hypothesis.
- Do not paste log lines that may contain tokens or customer data into the conversation.
- Do not rerun a CI workflow in a repository the user is not authorized to run it in.
