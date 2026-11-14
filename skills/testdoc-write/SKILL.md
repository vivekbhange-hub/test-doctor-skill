---
name: testdoc-write
description: >-
  A disciplined procedure for writing characterization and regression tests for one function,
  class or bug: read the code, list its behaviours and edge cases, write tests that are named
  after the behaviour, prove each test can fail by breaking the code on purpose, and keep the
  tests independent of order and of the clock. Use when the user says "write tests for this
  function", "add a regression test for this bug", "characterize this legacy code", "cover this
  module", "pin down the current behavior", or "make sure this never breaks again".
argument-hint: "[file:function or bug description]"
---

# testdoc-write: tests that can actually fail

Most weak tests were written fast and never seen red. This procedure has one non-negotiable
step: every test is shown to fail when the code is wrong, then the code is put back.

## Inputs

- The target: a function, class, module, or a bug report with steps to reproduce.
- The project's test framework and where its tests live. Look at 2 existing tests and copy their
  style, fixtures and naming.
- Commands below say `python3`; on Windows use `python` (or `py -3`). Use the project's own runner
  (`python3 -m pytest`, `npx jest`, `go test`, `mvn test`).

## Outputs

- New tests next to the existing ones, one behaviour per test, named after the behaviour.
- A short table in your reply: test name, behaviour, how you proved it can fail.
- Any bug found in the code, reported rather than silently pinned.

## Steps

1. **Confirm permission.** Write tests and run the code only in a repository the user owns or is
   authorized to change. Do not run code that touches production systems or real credentials.

2. **Read before writing.** Read the target and everything it calls that affects the result.
   Note inputs, outputs, side effects (files, network, database, clock, randomness) and the
   errors it raises. Read the docstring and callers for the intended behaviour.

3. **Enumerate behaviours.** Write the list first, in plain sentences, before any test code:
   - the main path with typical input;
   - each branch (every `if`, `else`, early return, `except`);
   - boundaries: empty, one, many, zero, negative, maximum, off-by-one;
   - invalid input and the error it should produce;
   - state changes and what must not change.
   Show the list to the user when it is more than about eight items and let them cut it.

4. **For a bug, start red.** Write the test that reproduces the bug first, run it, and confirm it
   fails for the reason in the bug report (not because of a typo). Only then fix the code.

5. **For legacy code with unknown intent (characterization), record what it does** and mark
   anything surprising with a comment `# current behaviour, confirm with owner`. Do not claim it
   is correct. If a result looks like a bug, report it and ask before pinning it.

6. **Write each test the same way.** Arrange the smallest input that exercises the behaviour,
   act once, assert the result and, where it matters, the side effect. Name it for the behaviour
   (`test_refund_of_unpaid_order_raises`), not the method (`test_refund_2`). One reason to fail
   per test. Prefer exact values over `is not None` or `> 0`.

7. **Make it independent.**
   - No shared mutable state between tests; build what you need in the test or a fixture that
     resets.
   - No dependence on test order, on the real clock (inject or freeze time), on randomness (seed
     it), on the time zone (use explicit UTC), on the network or on files outside a temp dir.
   - No fixed `sleep`; wait on a condition if you must wait.

8. **Prove it can fail (mutation by hand).** For each test, change the code under test in the
   smallest way that makes the behaviour wrong: flip the comparison, return a constant, drop the
   line, change a boundary. Run the test and confirm it fails. If the test cannot be run against
   modified code, invert its expected value instead. Then restore the code exactly
   (`git diff` should show only your new tests).

9. **Run the whole file, then the suite**, twice, and once in random order if the framework
   supports it. Fix anything that depends on order.

10. **Report.** Give the behaviour table, the proof column, the bugs found, and what you left
    untested and why.

## Decision rules

- Test behaviour through the public interface. Reach into private helpers only to pin down a
  tricky algorithm that has no other entry point.
- Mock only what you do not own or cannot run cheaply (network, payment, clock). Never mock the
  unit under test; never assert only that a mock was called.
- If setup takes more than about 15 lines, extract a builder or fixture instead of copying it.
- Table-driven or parametrized tests are good for boundary lists; give each case an id.
- If you cannot make a test fail by breaking the code, the test is not testing it: rewrite it or
  drop it.

## What NOT to do

- Do not write a test, see it pass, and stop. Green on the first run proves nothing.
- Do not copy the implementation into the test to compute the expected value.
- Do not add `sleep`, retries, or broad `try/except` to make a test pass.
- Do not leave the code under test modified after the failure check.
- Do not snapshot-test what you could assert in one line.
- Do not touch real services, real accounts or real customer data from a test.
