"""Tests for skills/testdoc-gaps/cov_gaps.py."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from _load import ROOT, load, write

cg = load("testdoc-gaps", "cov_gaps")
SCRIPT = ROOT / "skills" / "testdoc-gaps" / "cov_gaps.py"

LCOV = """TN:
SF:src/a.py
FN:1,10,alpha
FN:12,20,beta
FNDA:5,alpha
FNDA:0,beta
DA:1,5
DA:2,5
DA:3,0
DA:4,0
DA:6,0
DA:12,0
DA:13,0
BRDA:2,0,0,5
BRDA:2,0,1,0
BRDA:3,0,0,-
BRDA:3,0,1,-
end_of_record
SF:src/b.py
DA:1,1
DA:2,1
end_of_record
"""

COBERTURA = """<?xml version="1.0" ?>
<!DOCTYPE coverage SYSTEM "http://cobertura.sourceforge.net/xml/coverage-04.dtd">
<coverage line-rate="0.5" branch-rate="0.5" version="1">
  <sources><source>/work</source></sources>
  <packages><package name="shop"><classes>
    <class name="cart" filename="src/cart.py">
      <methods>
        <method name="add" signature="()"><lines><line number="1" hits="3"/><line number="2" hits="3"/></lines></method>
        <method name="remove" signature="()"><lines><line number="5" hits="0"/><line number="6" hits="0"/></lines></method>
      </methods>
      <lines>
        <line number="1" hits="3" branch="false"/>
        <line number="2" hits="3" branch="true" condition-coverage="50% (1/2)"/>
        <line number="5" hits="0" branch="false"/>
        <line number="6" hits="0" branch="true" condition-coverage="0% (0/2)">
          <conditions><condition number="0" type="jump" coverage="0%"/><condition number="1" type="jump" coverage="0%"/></conditions>
        </line>
      </lines>
    </class>
    <class name="cart$inner" filename="src/cart.py">
      <methods/>
      <lines><line number="7" hits="0" branch="false"/></lines>
    </class>
  </classes></package></packages>
</coverage>
"""

COVERAGEPY = json.dumps({
    "meta": {"version": "7.6.0", "branch_coverage": True},
    "files": {
        "src/shop/pricing.py": {
            "executed_lines": [1, 2, 3, 8],
            "missing_lines": [4, 5, 9],
            "excluded_lines": [],
            "executed_branches": [[2, 3]],
            "missing_branches": [[2, 4], [8, -9]],
            "functions": {"": {"executed_lines": [1], "missing_lines": []},
                          "price": {"executed_lines": [2, 3], "missing_lines": [4, 5]},
                          "convert": {"executed_lines": [], "missing_lines": [8, 9]}},
        },
        "src/shop/ok.py": {"executed_lines": [1, 2], "missing_lines": []},
    },
    "totals": {},
})


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cg.main(argv)
    return code, out.getvalue(), err.getvalue()


class LcovTests(unittest.TestCase):
    def setUp(self):
        self.files = cg.parse_lcov(LCOV)

    def test_lines_and_files(self):
        self.assertEqual(sorted(self.files), ["src/a.py", "src/b.py"])
        a = self.files["src/a.py"]
        self.assertEqual(a.lines, {1: 5, 2: 5, 3: 0, 4: 0, 6: 0, 12: 0, 13: 0})

    def test_branches_distinguish_not_taken_from_unreached(self):
        branches = self.files["src/a.py"].branches
        self.assertEqual(branches[2], {"missing": 1, "total": 2, "targets": []})
        self.assertEqual(branches[3], {"missing": 2, "total": 2, "targets": []})

    def test_functions_with_and_without_end_line(self):
        fns = self.files["src/a.py"].functions
        self.assertEqual(fns["alpha"], {"line": 1, "hits": 5, "span": (1, 10)})
        self.assertEqual(fns["beta"]["hits"], 0)
        old = cg.parse_lcov("SF:x.c\nFN:3,main\nFNDA:0,main\nDA:3,0\nend_of_record\n")
        self.assertEqual(old["x.c"].functions["main"], {"line": 3, "hits": 0, "span": None})

    def test_function_without_fnda_counts_as_never_called(self):
        files = cg.parse_lcov("SF:x.c\nFN:3,9,lonely\nDA:3,0\nend_of_record\n")
        self.assertEqual(files["x.c"].functions["lonely"]["hits"], 0)

    def test_repeated_records_for_one_file_are_merged(self):
        files = cg.parse_lcov("SF:x\nDA:1,0\nDA:2,1\nend_of_record\nSF:x\nDA:1,4\nend_of_record\n")
        self.assertEqual(files["x"].lines, {1: 4, 2: 1})

    def test_garbage_lines_ignored(self):
        files = cg.parse_lcov("hello\nDA:1,1\nSF:x\nDA:oops\nDA:1,2,checksum\nend_of_record\n")
        self.assertEqual(files["x"].lines, {1: 2})


class CoberturaTests(unittest.TestCase):
    def test_parse(self):
        files = cg.parse_cobertura(COBERTURA)
        self.assertEqual(list(files), ["src/cart.py"])
        cart = files["src/cart.py"]
        self.assertEqual(cart.lines, {1: 3, 2: 3, 5: 0, 6: 0, 7: 0})  # classes of one file are merged
        self.assertEqual(cart.branches[2]["missing"], 1)
        self.assertEqual(cart.branches[2]["total"], 2)
        self.assertEqual(cart.branches[6]["missing"], 2)
        self.assertEqual(cart.functions["add"]["hits"], 3)
        self.assertEqual(cart.functions["remove"], {"line": 5, "hits": 0, "span": (5, 6)})

    def test_conditions_used_when_no_summary(self):
        xml = ('<coverage><packages><package><classes><class filename="f.py"><lines>'
               '<line number="1" hits="1" branch="true"><conditions><condition number="0" coverage="100%"/>'
               '<condition number="1" coverage="50%"/></conditions></line></lines></class></classes></package>'
               '</packages></coverage>')
        branches = cg.parse_cobertura(xml)["f.py"].branches
        self.assertEqual(branches[1], {"missing": 1, "total": 2, "targets": []})

    def test_entities_and_bad_xml_rejected(self):
        with self.assertRaises(ValueError):
            cg.parse_cobertura('<!DOCTYPE c [<!ENTITY a "b">]><coverage/>')
        with self.assertRaises(ValueError):
            cg.parse_cobertura("<coverage><oops></coverage>")


class CoveragePyTests(unittest.TestCase):
    def test_parse(self):
        files = cg.parse_coveragepy(COVERAGEPY)
        p = files["src/shop/pricing.py"]
        self.assertEqual(p.lines, {1: 1, 2: 1, 3: 1, 8: 1, 4: 0, 5: 0, 9: 0})
        self.assertEqual(p.branches[2], {"missing": 1, "total": 2, "targets": ["2->4"]})
        self.assertEqual(p.branches[8], {"missing": 1, "total": 1, "targets": ["8->exit"]})
        self.assertNotIn("", p.functions)
        self.assertEqual(p.functions["price"]["hits"], 1)
        self.assertEqual(p.functions["convert"], {"line": 8, "hits": 0, "span": (8, 9)})

    def test_branch_total_unknown_without_executed_branches(self):
        data = {"files": {"a.py": {"executed_lines": [1], "missing_lines": [2], "missing_branches": [[1, 2]]}}}
        branch = cg.parse_coveragepy(json.dumps(data))["a.py"].branches[1]
        self.assertEqual((branch["missing"], branch["total"]), (1, None))

    def test_not_coveragepy_json(self):
        with self.assertRaises(ValueError):
            cg.parse_coveragepy('{"hello": 1}')
        with self.assertRaises(ValueError):
            cg.parse_coveragepy("{broken")


class DetectTests(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(cg.detect_format(LCOV), "lcov")
        self.assertEqual(cg.detect_format(COBERTURA), "cobertura")
        self.assertEqual(cg.detect_format("﻿" + COVERAGEPY), "coveragepy")
        self.assertEqual(cg.detect_format("  \n<coverage/>"), "cobertura")
        self.assertIsNone(cg.detect_format("hello world"))


class RangeTests(unittest.TestCase):
    def test_bridges_non_executable_lines(self):
        executable = {1: 1, 2: 1, 3: 0, 5: 0, 6: 0, 9: 1, 12: 0}
        ranges = cg.line_ranges([3, 5, 6, 12], executable)
        self.assertEqual(ranges, [(3, 6), (12, 12)])
        self.assertEqual([cg.fmt_range(r) for r in ranges], ["3-6", "12"])

    def test_does_not_bridge_over_a_covered_line(self):
        executable = {1: 0, 2: 1, 3: 0}
        self.assertEqual(cg.line_ranges([1, 3], executable), [(1, 1), (3, 3)])

    def test_does_not_bridge_across_function_boundary(self):
        executable = {5: 0, 6: 0, 10: 0}
        self.assertEqual(cg.line_ranges([5, 6, 10], executable), [(5, 10)])
        self.assertEqual(cg.line_ranges([5, 6, 10], executable, boundaries=[8]), [(5, 6), (10, 10)])

    def test_empty(self):
        self.assertEqual(cg.line_ranges([], {1: 1}), [])


class ReportTests(unittest.TestCase):
    def build(self, text=LCOV, **kw):
        return cg.build_report(cg.parse_lcov(text), "cov.info", "lcov", **kw)

    def test_file_analysis(self):
        report = self.build()
        self.assertEqual([f["file"] for f in report["files"]], ["src/a.py"])  # b.py is fully covered
        a = report["files"][0]
        self.assertEqual((a["lines_total"], a["lines_uncovered"], a["line_coverage"]), (7, 5, 28.6))
        self.assertEqual(a["uncovered_ranges"], ["3-6", "12-13"])
        self.assertEqual(a["priority"], round(5 * 5 / 7, 1))
        self.assertEqual(a["branches_missing"], 3)
        self.assertEqual(a["uncovered_branches"], ["2 (1/2 untaken)", "3 (2/2 untaken)"])
        self.assertEqual(a["never_called"], [{"function": "beta", "line": 12}])
        self.assertEqual(a["biggest_block"], {"range": "3-6", "lines": 3, "function": "alpha"})

    def test_totals(self):
        t = self.build()["totals"]
        self.assertEqual((t["lines"], t["lines_covered"]), (9, 4))
        self.assertEqual(t["line_coverage"], 44.4)
        self.assertEqual((t["branches"], t["branches_covered"]), (4, 1))
        self.assertEqual(t["branch_coverage"], 25.0)
        self.assertEqual((t["files_considered"], t["files_with_gaps"]), (2, 1))

    def test_ranking_uses_priority_not_percentage(self):
        big = "SF:big.py\n" + "".join(f"DA:{i},{0 if i <= 50 else 1}\n" for i in range(1, 101)) + "end_of_record\n"
        small = "SF:tiny.py\nDA:1,0\nDA:2,0\nend_of_record\n"  # 0% but only 2 lines
        mid = "SF:mid.py\n" + "".join(f"DA:{i},{0 if i <= 20 else 1}\n" for i in range(1, 101)) + "end_of_record\n"
        report = self.build(big + small + mid)
        self.assertEqual([f["file"] for f in report["files"]], ["big.py", "mid.py", "tiny.py"])

    def test_threshold_and_top(self):
        text = LCOV + "SF:c.py\nDA:1,0\nDA:2,1\nDA:3,1\nDA:4,1\nend_of_record\n"  # 75%
        self.assertEqual([f["file"] for f in self.build(text, threshold=50)["files"]], ["src/a.py"])
        self.assertEqual(len(self.build(text, threshold=80)["files"]), 2)
        self.assertEqual(len(self.build(text, top=1)["files"]), 1)
        self.assertEqual(self.build(text, top=1)["files_not_shown"], 1)
        self.assertEqual(self.build(text, top=0)["files_not_shown"], 0)

    def test_changed_filter_matches_by_suffix(self):
        report = self.build(changed=["repo/src/a.py"])
        self.assertEqual([f["file"] for f in report["files"]], ["src/a.py"])
        self.assertEqual(self.build(changed=["other.py"])["files"], [])
        self.assertEqual(self.build(changed=["xa.py"])["files"], [])  # a different file with a similar name
        self.assertIn("changed since", self.build(changed=[])["scope"])

    def test_path_matching_and_normalising(self):
        self.assertTrue(cg.path_matches("src/a.py", ["src/a.py"]))
        self.assertTrue(cg.path_matches("pkg/src/a.py", ["src/a.py"]))
        self.assertTrue(cg.path_matches("a.py", ["src/a.py"]))
        self.assertFalse(cg.path_matches("xa.py", ["a.py"]))
        self.assertEqual(cg.normalise_path("src\\shop\\a.py"), "src/shop/a.py")
        self.assertEqual(cg.normalise_path("./src/a.py"), "src/a.py")
        self.assertEqual(cg.normalise_path("/home/ci/work/src/a.py", "/home/ci/work"), "src/a.py")
        here = Path.cwd().as_posix().rstrip("/")
        self.assertEqual(cg.normalise_path(here + "/src/a.py"), "src/a.py")

    def test_empty_gap_report(self):
        text = cg.render_markdown(self.build("SF:a.py\nDA:1,1\nend_of_record\n"))
        self.assertIn("No coverage gaps in scope.", text)

    def test_zero_executable_lines_file_skipped(self):
        report = self.build("SF:empty.py\nend_of_record\nSF:a.py\nDA:1,0\nend_of_record\n")
        self.assertEqual([f["file"] for f in report["files"]], ["a.py"])

    def test_markdown_content(self):
        text = cg.render_markdown(self.build())
        for needle in ("# Where to write tests first", "## Ranked files", "`src/a.py`", "28.6%", "3-6, 12-13",
                       "Functions never called: `beta` (line 12)",
                       "Largest untested block: lines 3-6 (3 uncovered, inside `alpha`)",
                       "Branches never taken: 2 (1/2 untaken), 3 (2/2 untaken)"):
            self.assertIn(needle, text)
        self.assertNotIn("\r", text)

    def test_many_ranges_are_truncated_in_markdown_only(self):
        lines = "".join(f"DA:{i},{0 if i % 2 else 1}\n" for i in range(1, 100))
        report = self.build("SF:z.py\n" + lines + "end_of_record\n")
        self.assertGreater(len(report["files"][0]["uncovered_ranges"]), cg.MAX_RANGES_SHOWN)
        self.assertIn("more ranges", cg.render_markdown(report))


class ChangedFilesTests(unittest.TestCase):
    def fake_runner(self, stdout="", code=0, stderr=""):
        calls = []

        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)
        run.calls = calls
        return run

    def test_parses_names_and_builds_command(self):
        runner = self.fake_runner("src/a.py\r\nsrc\\b.py\n\n")
        self.assertEqual(cg.changed_files("origin/main", "/repo", runner), ["src/a.py", "src/b.py"])
        cmd, kwargs = runner.calls[0]
        self.assertEqual(cmd[:3], ["git", "diff", "--name-only"])
        self.assertIn("origin/main", cmd)
        self.assertEqual(cmd[-1], "--")
        self.assertEqual(kwargs["cwd"], "/repo")

    def test_rejects_option_like_refs(self):
        for ref in ("--output=x", "-p", ""):
            with self.assertRaises(RuntimeError):
                cg.changed_files(ref, None, self.fake_runner())

    def test_git_failure_and_missing_git(self):
        with self.assertRaises(RuntimeError) as ctx:
            cg.changed_files("nope", None, self.fake_runner(code=128, stderr="fatal: bad revision"))
        self.assertIn("bad revision", str(ctx.exception))

        def missing(cmd, **kwargs):
            raise FileNotFoundError("git")
        with self.assertRaises(RuntimeError):
            cg.changed_files("main", None, missing)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_real_git_repository(self):
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)

        def git(*args):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                            "-c", "commit.gpgsign=false", *args], cwd=tmp, check=True, capture_output=True, env=env)
        with tempfile.TemporaryDirectory() as tmp:
            git("init", "-q")
            write(Path(tmp) / "keep.py", "x = 1\n")
            write(Path(tmp) / "src" / "edit.py", "y = 1\n")
            git("add", ".")
            git("commit", "-q", "-m", "one")
            write(Path(tmp) / "src" / "edit.py", "y = 2\n")
            write(Path(tmp) / "src" / "new.py", "z = 1\n")
            git("add", ".")
            git("commit", "-q", "-m", "two")
            self.assertEqual(cg.changed_files("HEAD~1", tmp), ["src/edit.py", "src/new.py"])
            self.assertEqual(cg.changed_files("HEAD", tmp), [])


class CliTests(unittest.TestCase):
    def make(self, tmp, name="lcov.info", text=LCOV):
        return str(write(Path(tmp) / name, text))

    def test_markdown_and_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_main([self.make(tmp)])
            self.assertEqual((code, err), (0, ""))
            self.assertIn("(lcov)", out)

    def test_each_format_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, text, fmt in (("c.xml", COBERTURA, "cobertura"), ("c.json", COVERAGEPY, "coveragepy"),
                                    ("l.info", LCOV, "lcov")):
                code, out, _ = run_main([self.make(tmp, name, text), "--json"])
                data = json.loads(out)
                self.assertEqual((code, data["format"]), (0, fmt))
                self.assertTrue(data["files"])

    def test_explicit_format_overrides_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_main([self.make(tmp, "x.txt", LCOV), "--format", "cobertura"])
            self.assertEqual(code, 2)
            self.assertIn("not valid XML", err)

    def test_threshold_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make(tmp)
            self.assertEqual(run_main([path, "--threshold", "50"])[0], 1)
            self.assertEqual(run_main([path, "--threshold", "10"])[0], 0)

    def test_input_errors_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_main([str(Path(tmp) / "missing.info")])
            self.assertEqual((code, out), (2, ""))
            self.assertIn("cannot read", err)
            self.assertEqual(run_main([self.make(tmp, "junk.txt", "hello")])[0], 2)
            self.assertEqual(run_main([self.make(tmp, "empty.info", "TN:\n")])[0], 2)

    def test_changed_since_uses_git_output(self):
        original = cg.changed_files
        try:
            cg.changed_files = lambda ref, repo=None, runner=None: ["src/a.py"]
            with tempfile.TemporaryDirectory() as tmp:
                code, out, _ = run_main([self.make(tmp), "--changed-since", "main", "--json"])
                self.assertEqual(code, 0)
                self.assertEqual([f["file"] for f in json.loads(out)["files"]], ["src/a.py"])
                cg.changed_files = lambda ref, repo=None, runner=None: ["unrelated.py"]
                _, out, _ = run_main([self.make(tmp), "--changed-since", "main", "--json"])
                self.assertEqual(json.loads(out)["files"], [])

                def boom(ref, repo=None, runner=None):
                    raise RuntimeError("git diff failed: bad revision")
                cg.changed_files = boom
                code, _, err = run_main([self.make(tmp), "--changed-since", "nope"])
                self.assertEqual(code, 2)
                self.assertIn("bad revision", err)
        finally:
            cg.changed_files = original

    def test_git_is_not_run_without_the_flag(self):
        original = cg.changed_files

        def forbidden(*args, **kwargs):
            raise AssertionError("git must not run without --changed-since")
        cg.changed_files = forbidden
        try:
            with tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(run_main([self.make(tmp)])[0], 0)
        finally:
            cg.changed_files = original

    def test_out_file_uses_lf_and_strip_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = LCOV.replace("SF:src/a.py", "SF:/ci/work/src/a.py")
            target = Path(tmp) / "out.md"
            code, out, _ = run_main([self.make(tmp, text=text), "--strip-prefix", "/ci/work", "-o", str(target)])
            self.assertEqual((code, out), (0, ""))
            data = target.read_bytes()
            self.assertIn(b"`src/a.py`", data)
            self.assertNotIn(b"\r\n", data)

    def test_out_creates_missing_folders_and_reports_unwritable_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self.make(tmp)
            nested = Path(tmp) / "testdoc" / "gaps.md"
            self.assertEqual(run_main([src, "-o", str(nested)])[0], 0)
            self.assertTrue(nested.exists())
            blocker = write(Path(tmp) / "afile", "x")
            code, _, err = run_main([src, "-o", str(blocker / "r.md")])
            self.assertEqual(code, 2)
            self.assertIn("cannot write", err)

    def test_runs_as_a_script(self):
        proc = subprocess.run([sys.executable, "-I", str(SCRIPT), str(ROOT / "examples" / "coverage" / "lcov.info"),
                               "--top", "2"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("src/shop/checkout.py", proc.stdout)


if __name__ == "__main__":
    unittest.main()
