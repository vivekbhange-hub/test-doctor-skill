#!/usr/bin/env python3
"""Regenerate (or verify) every file in examples/output/ from the fixtures in examples/.

  python examples/regenerate.py           rewrite examples/output/
  python examples/regenerate.py --check   exit 1 if the committed outputs are stale

Runs the same commands the README shows, from the repository root:

  junit_report.py examples/junit            -> flaky-report.md
  cov_gaps.py examples/coverage/lcov.info   -> coverage-gaps.md
  weak_tests.py examples/weak               -> weak-tests.md

Standard library only.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "examples" / "output"

# (skill folder, script, arguments, output file)
STEPS = [
    ("testdoc-flaky", "junit_report", ["examples/junit"], "flaky-report.md"),
    ("testdoc-gaps", "cov_gaps", ["examples/coverage/lcov.info"], "coverage-gaps.md"),
    ("testdoc-lint", "weak_tests", ["examples/weak"], "weak-tests.md"),
]


def _load(skill: str, script: str):
    path = ROOT / "skills" / skill / f"{script}.py"
    spec = importlib.util.spec_from_file_location(f"_regen_{script}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate(out: Path) -> list:
    """Run every script from the repo root and write its report into `out`."""
    out.mkdir(parents=True, exist_ok=True)
    previous = os.getcwd()
    os.chdir(ROOT)
    try:
        for skill, script, args, name in STEPS:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = _load(skill, script).main(list(args))
            if code != 0:
                raise RuntimeError(f"{script} exited with {code}")
            (out / name).write_bytes(buffer.getvalue().encode("utf-8"))
    finally:
        os.chdir(previous)
    return sorted(p.name for p in out.iterdir() if p.is_file())


def compare(expected_dir: Path, actual_dir: Path) -> list:
    """Return a list of differences between two output folders."""
    problems = []
    expected = {p.name for p in expected_dir.iterdir() if p.is_file()}
    actual = {p.name for p in actual_dir.iterdir() if p.is_file()}
    for name in sorted(expected ^ actual):
        problems.append(f"{name}: {'missing from regenerated output' if name in expected else 'not committed'}")
    for name in sorted(expected & actual):
        if (expected_dir / name).read_bytes() != (actual_dir / name).read_bytes():
            problems.append(f"{name}: content differs")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="verify instead of rewriting")
    args = parser.parse_args(argv)
    if not args.check:
        for name in generate(OUTPUT):
            print(f"wrote examples/output/{name}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        generate(Path(tmp))
        problems = compare(OUTPUT, Path(tmp))
    for problem in problems:
        print(problem)
    print("examples/output is up to date" if not problems else f"{len(problems)} stale file(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
