"""The bundled demo: committed outputs must be exactly what the scripts produce (examples/regenerate.py)."""
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from _load import ROOT, load, load_path

regen = load_path(ROOT / "examples" / "regenerate.py", "regenerate_under_test")
jr = load("testdoc-flaky", "junit_report")
cg = load("testdoc-gaps", "cov_gaps")
wt = load("testdoc-lint", "weak_tests")
OUTPUT = ROOT / "examples" / "output"
EXPECTED = ["coverage-gaps.md", "flaky-report.md", "weak-tests.md"]


class DeterminismTests(unittest.TestCase):
    def test_regenerating_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = regen.generate(Path(tmp))
            self.assertEqual(written, EXPECTED)
            self.assertEqual(regen.compare(OUTPUT, Path(tmp)), [])

    def test_check_mode(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(regen.main(["--check"]), 0)
        self.assertIn("up to date", out.getvalue())

    def test_compare_reports_differences(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            (Path(a) / "x.txt").write_text("1", encoding="utf-8")
            (Path(b) / "x.txt").write_text("2", encoding="utf-8")
            (Path(b) / "y.txt").write_text("2", encoding="utf-8")
            self.assertEqual(regen.compare(Path(a), Path(b)), ["y.txt: not committed", "x.txt: content differs"])

    def test_outputs_use_lf_and_no_machine_paths(self):
        for name in EXPECTED:
            with self.subTest(file=name):
                data = (OUTPUT / name).read_bytes()
                self.assertNotIn(b"\r\n", data)
                self.assertNotIn(b"Users", data)
                self.assertNotIn(b":\\", data)


class JunitFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runs, warnings = jr.load_runs([str(ROOT / "examples" / "junit")])
        cls.warnings = warnings
        cls.report = jr.analyse(runs)

    def test_five_clean_runs(self):
        self.assertEqual(self.warnings, [])
        self.assertEqual([r["label"] for r in self.report["runs"]], [f"run{i}.xml" for i in range(1, 6)])
        self.assertTrue(all(r["tests"] == 24 for r in self.report["runs"]))

    def test_the_flakes_are_deterministic(self):
        flaky = {f["test"].split("::")[1]: f for f in self.report["flaky"]}
        self.assertEqual(sorted(flaky), ["test_fetch_exchange_rate", "test_order_confirmation_email",
                                         "test_release_stock", "test_report_covers_today", "test_reserve_stock",
                                         "test_top_pick_is_stable"])
        self.assertEqual(flaky["test_reserve_stock"]["failed_in"], ["run1.xml", "run3.xml", "run4.xml"])
        causes = {name: f["likely_cause"] for name, f in flaky.items()}
        self.assertEqual(causes, {
            "test_fetch_exchange_rate": "network", "test_order_confirmation_email": "timing",
            "test_release_stock": "ordering/shared state", "test_report_covers_today": "time-zone/date",
            "test_reserve_stock": "ordering/shared state", "test_top_pick_is_stable": "unknown"})

    def test_consistent_failures_and_clusters(self):
        failing = sorted(f["test"].split("::")[1] for f in self.report["failing"])
        self.assertEqual(failing, ["test_apply_coupon_expired", "test_zone_lookup"])
        patterns = {c["pattern"]: c for c in self.report["clusters"]}
        shared = [c for p, c in patterns.items() if "UNIQUE constraint" in p]
        self.assertEqual(len(shared), 1)  # the row ids differ between runs and tests, one cluster
        self.assertEqual((shared[0]["count"], len(shared[0]["tests"])), (5, 2))

    def test_slow_tests(self):
        slowest = self.report["slow_tests"][0]
        self.assertTrue(slowest["test"].endswith("test_full_checkout_flow"))
        self.assertGreater(slowest["percent_of_total"], 40)
        self.assertEqual(self.report["slow_groups"][0]["group"], "tests/test_checkout.py")


class CoverageFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "examples" / "coverage" / "lcov.info").read_text(encoding="utf-8")
        cls.report = cg.build_report(cg.parse_lcov(text), "examples/coverage/lcov.info", "lcov", top=0)

    def test_ranking_and_content(self):
        files = self.report["files"]
        self.assertEqual(files[0]["file"], "src/shop/checkout.py")
        self.assertNotIn("src/shop/pricing.py", [f["file"] for f in files])  # fully covered
        checkout = files[0]
        self.assertEqual(checkout["never_called"], [{"function": "refund", "line": 92}])
        self.assertEqual(checkout["biggest_block"]["function"], "refund")
        self.assertTrue(any("2/3 untaken" in b for b in checkout["uncovered_branches"]))

    def test_every_file_has_a_distinct_priority_order(self):
        priorities = [f["priority"] for f in self.report["files"]]
        self.assertEqual(priorities, sorted(priorities, reverse=True))


class WeakFixtureTests(unittest.TestCase):
    def test_every_language_and_rule_is_demonstrated(self):
        report = wt.scan([str(ROOT / "examples" / "weak")])
        self.assertEqual(sorted(report["summary"]["by_rule"]), sorted(wt.RULES))
        self.assertGreaterEqual(report["summary"]["tests"], 40)

    def test_fixtures_are_fictional(self):
        for path in (ROOT / "examples").rglob("*"):
            if path.is_file() and path.suffix in {".xml", ".info", ".py", ".js", ".go", ".java", ".md"}:
                text = path.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"https?://(?!.*\.example)[\w.-]+\.(com|org|net|io)\b", str(path))


if __name__ == "__main__":
    unittest.main()
