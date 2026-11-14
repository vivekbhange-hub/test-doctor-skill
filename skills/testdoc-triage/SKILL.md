---
name: testdoc-triage
description: >-
  Triages a red CI run: groups the failures into clusters by normalised message (numbers, ids,
  addresses and paths stripped), decides for each cluster whether it is a product bug, a test bug
  or an environment problem, and gives one concrete next action per cluster with an owner. Use
  when the user says "CI is red", "triage these test failures", "why did 40 tests fail", "is this
  a real bug or a flaky test", "what broke the build", or "group these failures".
argument-hint: "[JUnit XML of the failing run, or a run id]"
---

# testdoc-triage: from 40 red tests to 3 causes

A red run with many failures usually has few causes. `junit_report.py` groups failures by their
normalised message so you can see that 31 of 40 are one broken fixture. Then you decide, per
cluster, whose problem it is and what happens next.

## Inputs

- JUnit XML from the failing run. Best: also one or two earlier green or red runs of the same
  suite, so "new failure" and "already failing" can be told apart.
- With `gh`: `gh run download <run-id> --pattern 'junit*' --dir ci-runs/<run-id>`, and
  `gh run view <run-id> --log-failed` for the log of the failed step.
- The diff of the commit under test (`git diff --stat <base>..<head>`).
- Commands below say `python3`; on Windows use `python` (or `py -3`).

## Outputs

- `testdoc/triage.md`: one section per cluster with count, example, verdict, next action.
- A one-paragraph summary for the user: how many causes, which block the merge, which can wait.

## Steps

1. **Confirm permission.** Download CI artifacts and logs only for repositories the user owns or
   is authorized to access. Logs can contain secrets; summarize, do not paste.

2. **Cluster the failures** with the script that ships in the sibling `testdoc-flaky` skill.
   ```
   python3 "${CLAUDE_SKILL_DIR}/../testdoc-flaky/junit_report.py" ci-runs/failing --top 0 -o testdoc/triage.md
   ```
   Add earlier runs as extra paths to see which failures are new (`Consistently failing` and
   `Failed in` show history). Read "Failure clusters" first; the "Tests per cluster" list says
   which tests share a cause.

3. **Order clusters by blast radius**, largest count first, but look at every cluster: a cluster of
   one can be the real bug while a cluster of thirty is a missing environment variable.

4. **For each cluster, read one failing test and its failure text.** Then pick the verdict:

   | Verdict | Signs | Typical next action |
   |---|---|---|
   | Product bug | The test is right, the code changed behaviour; failure appears right after a commit touching that code | Fix the code or revert the commit; assign to the author of the change |
   | Test bug | The code is right, the test assumed something false (hard-coded date, order, shared data, out-of-date expectation) | Fix the test using `testdoc-write` rules |
   | Environment | Same failure across unrelated tests, mentions network, DNS, disk, memory, missing variable, tool version | Fix CI config, pin versions, retry the job once to confirm, tell infra |
   | Flaky | Passed on a rerun or in earlier runs with the same code | Hand to `testdoc-flaky`; do not just rerun |

5. **Check the evidence for the verdict.** Compare with the last green run of the same test
   (`Failed in` column), look at `git log` for the files the failing test touches, and re-run the
   single test locally when you can. If you cannot confirm a verdict, label it "suspected" and
   say what would confirm it.

6. **Write the next action per cluster** as an imperative with an owner and a check: "Revert
   commit abc123 or fix `apply_coupon` rounding; owner: author; check: `pytest
   tests/test_cart.py` green". Avoid "investigate".

7. **Summarize for the user**: number of clusters, the verdict for each in one line, what blocks
   the merge, what can be ticketed. Mention anything you could not verify.

## Decision rules

- Everything failing in the same second, with the same setup error: environment or fixture, one
  cluster, one fix.
- Failure text with a connection, timeout or resource keyword and no code change in the area:
  environment or flaky before product bug.
- A test failing in every run since a specific commit: product bug or outdated test from that
  commit; check `git log -S` for the changed expectation.
- Never mark a cluster "flaky" without at least one run where the same test passed on the same code.
- If two clusters have different messages but one root cause (for example a null returned by a
  changed function), merge them in your write-up and say so.
- Tests that were skipped or failing before the commit are not this commit's regression; list
  them under "already red".

## What NOT to do

- Do not rerun the job until it goes green and call it fixed.
- Do not skip, delete or loosen a failing test to unblock a merge without saying so and getting
  agreement.
- Do not blame the commit author without evidence from the diff or history.
- Do not change production code during triage unless the user asks for the fix.
- Do not paste raw CI logs into the conversation; quote the one line that matters.
