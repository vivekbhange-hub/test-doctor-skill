"""Tests for skills/testdoc-flaky/junit_report.py."""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from xml.sax.saxutils import quoteattr

from _load import ROOT, load, write

jr = load("testdoc-flaky", "junit_report")
SCRIPT = ROOT / "skills" / "testdoc-flaky" / "junit_report.py"


def case(name, cls="tests.test_a.TestA", time=0.1, status="pass", message="boom", kind="AssertionError",
         file=None, body=""):
    """One <testcase>. status: pass, fail, error, skip, flaky (passed after a retry), rerun (failed after retries)."""
    attrs = f"classname={quoteattr(cls)} name={quoteattr(name)} time={quoteattr(str(time))}"
    if file:
        attrs += f" file={quoteattr(file)}"
    inner = {
        "pass": "",
        "fail": f"<failure message={quoteattr(message)} type={quoteattr(kind)}>{body}</failure>",
        "error": f"<error message={quoteattr(message)} type={quoteattr(kind)}>{body}</error>",
        "skip": '<skipped message="not today"/>',
        "flaky": f"<flakyFailure message={quoteattr(message)} type={quoteattr(kind)}>{body}</flakyFailure>",
        "rerun": f"<failure message={quoteattr(message)} type={quoteattr(kind)}/>"
                 f"<rerunFailure message={quoteattr(message)} type={quoteattr(kind)}/>",
    }[status]
    return f"<testcase {attrs}>{inner}</testcase>" if inner else f"<testcase {attrs}/>"


def suite(*cases, root="testsuites", name="pytest"):
    body = "".join(cases)
    if root == "testsuites":
        return f'<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="{name}">{body}</testsuite></testsuites>'
    return f'<?xml version="1.0" encoding="utf-8"?><testsuite name="{name}">{body}</testsuite>'


def runs_from(*xml_docs):
    """Write each document as runN.xml and return the loaded runs."""
    with tempfile.TemporaryDirectory() as tmp:
        for i, doc in enumerate(xml_docs, 1):
            write(Path(tmp) / f"run{i}.xml", doc)
        return jr.load_runs([tmp])


def analyse(*xml_docs, **kw):
    runs, _ = runs_from(*xml_docs)
    return jr.analyse(runs, **kw)


class ParsingTests(unittest.TestCase):
    def test_pytest_style_with_file_attribute(self):
        cases = jr.parse_junit(suite(case("test_x", cls="tests.test_a.TestA", file="tests/test_a.py")).encode())
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["id"], "tests.test_a.TestA::test_x")
        self.assertEqual(cases[0]["group"], "tests/test_a.py")

    def test_jest_style_same_classname_and_name(self):
        cases = jr.parse_junit(suite(case("Cart adds an item", cls="Cart adds an item"), name="Cart").encode())
        self.assertEqual(cases[0]["id"], "Cart adds an item")
        self.assertEqual(cases[0]["group"], "Cart")  # falls back to the suite name

    def test_surefire_style(self):
        doc = suite(case("testAdd", cls="com.shop.CartTest", time="1,250.5"), root="testsuite", name="com.shop.CartTest")
        cases = jr.parse_junit(doc.encode())
        self.assertEqual(cases[0]["id"], "com.shop.CartTest::testAdd")
        self.assertEqual(cases[0]["group"], "com.shop.CartTest")
        self.assertAlmostEqual(cases[0]["time"], 1250.5)  # commas are treated as thousands separators

    def test_gotestsum_style_subtests(self):
        doc = suite(case("TestParse", cls="github.example/shop/pricing"),
                    case("TestParse/negative", cls="github.example/shop/pricing", status="fail", message="got -1"))
        cases = jr.parse_junit(doc.encode())
        self.assertEqual([c["id"] for c in cases],
                         ["github.example/shop/pricing::TestParse", "github.example/shop/pricing::TestParse/negative"])

    def test_bare_testsuite_root_and_nested_suites(self):
        nested = ('<testsuites><testsuite name="outer"><testsuite name="inner">'
                  + case("a") + '</testsuite>' + case("b") + '</testsuite></testsuites>')
        self.assertEqual([c["id"] for c in jr.parse_junit(nested.encode())], ["tests.test_a.TestA::a", "tests.test_a.TestA::b"])
        self.assertEqual(len(jr.parse_junit(suite(case("a"), root="testsuite").encode())), 1)

    def test_namespaced_root(self):
        doc = '<testsuites xmlns="urn:x"><testsuite name="s"><testcase classname="c" name="n" time="1"/></testsuite></testsuites>'
        self.assertEqual(jr.parse_junit(doc.encode())[0]["id"], "c::n")

    def test_outcomes(self):
        doc = suite(case("p"), case("f", status="fail"), case("e", status="error"), case("s", status="skip"),
                    case("r", status="flaky"))
        out = {c["id"].split("::")[1]: c for c in jr.parse_junit(doc.encode())}
        self.assertEqual(out["p"]["outcome"], "pass")
        self.assertEqual(out["f"]["outcome"], "fail")
        self.assertEqual(out["e"]["outcome"], "error")
        self.assertEqual(out["s"]["outcome"], "skip")
        self.assertEqual((out["r"]["outcome"], out["r"]["retried"]), ("pass", True))

    def test_message_falls_back_to_body_text(self):
        doc = ('<testsuite><testcase classname="c" name="n"><failure type="E">first line\nsecond</failure>'
               '</testcase></testsuite>')
        case_ = jr.parse_junit(doc.encode())[0]
        self.assertEqual(case_["message"], "first line")
        self.assertEqual(case_["kind"], "E")

    def test_rejects_bad_documents(self):
        with self.assertRaises(ValueError):
            jr.parse_junit(b"<testsuite><oops></testsuite>")
        with self.assertRaises(ValueError):
            jr.parse_junit(b"<html></html>")
        with self.assertRaises(ValueError):
            jr.parse_junit(b'<!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite>&a;</testsuite>')

    def test_case_id_and_time_helpers(self):
        self.assertEqual(jr.case_id("", "only_name"), "only_name")
        self.assertEqual(jr.case_id("cls", ""), "cls")
        self.assertEqual(jr.case_id("", ""), "(unnamed)")
        self.assertEqual(jr.parse_time("1.5"), 1.5)
        self.assertEqual(jr.parse_time("nonsense"), 0.0)
        self.assertEqual(jr.parse_time(None), 0.0)
        self.assertEqual(jr.parse_time("-3"), 0.0)


class FlakyTests(unittest.TestCase):
    def test_flaky_needs_pass_and_fail_across_runs(self):
        report = analyse(
            suite(case("wobbly"), case("solid"), case("broken", status="fail")),
            suite(case("wobbly", status="fail", message="timeout waiting for x"), case("solid"),
                  case("broken", status="fail")),
            suite(case("wobbly"), case("solid"), case("broken", status="fail")))
        self.assertEqual([f["test"] for f in report["flaky"]], ["tests.test_a.TestA::wobbly"])
        flaky = report["flaky"][0]
        self.assertEqual((flaky["passes"], flaky["failures"], flaky["runs"]), (2, 1, 3))
        self.assertAlmostEqual(flaky["flake_rate"], 0.3333, places=3)
        self.assertEqual(flaky["failed_in"], ["run2.xml"])
        self.assertEqual(flaky["likely_cause"], "timing")
        self.assertEqual([f["test"] for f in report["failing"]], ["tests.test_a.TestA::broken"])
        self.assertEqual(report["summary"]["flaky"], 1)

    def test_error_counts_as_failure(self):
        report = analyse(suite(case("t")), suite(case("t", status="error", kind="KeyError", message="'x'")))
        self.assertEqual(len(report["flaky"]), 1)

    def test_skipped_runs_do_not_count_as_executions(self):
        report = analyse(suite(case("t")), suite(case("t", status="skip")), suite(case("t")))
        self.assertEqual(report["flaky"], [])
        self.assertEqual(report["summary"]["executions"], 2)

    def test_always_passing_is_neither_flaky_nor_failing(self):
        report = analyse(suite(case("t")), suite(case("t")))
        self.assertEqual((report["flaky"], report["failing"]), ([], []))

    def test_min_runs_filters_rare_tests(self):
        docs = [suite(case("often"), case("rare")), suite(case("often", status="fail"), case("rare", status="fail")),
                suite(case("often"))]
        self.assertEqual(len(analyse(*docs, min_runs=1)["flaky"]), 2)  # rare: passed once, failed once, in 2 runs
        report = analyse(*docs, min_runs=3)
        self.assertEqual([f["test"] for f in report["flaky"]], ["tests.test_a.TestA::often"])
        self.assertEqual(report["failing"], [])

    def test_retry_plugin_pass_after_failure_is_flaky(self):
        report = analyse(suite(case("t", status="flaky", message="connection reset")), suite(case("t")))
        flaky = report["flaky"][0]
        self.assertEqual((flaky["passes"], flaky["failures"], flaky["retried_passes"]), (1, 0, 1))
        self.assertEqual(flaky["likely_cause"], "network")
        self.assertEqual(flaky["failed_in"], [])

    def test_failure_after_reruns_is_a_failure_not_a_flake(self):
        report = analyse(suite(case("t", status="rerun")), suite(case("t", status="rerun")))
        self.assertEqual(report["flaky"], [])
        self.assertEqual(len(report["failing"]), 1)

    def test_same_test_twice_in_one_run_pass_and_fail_is_flaky(self):
        report = analyse(suite(case("t", status="fail"), case("t")), suite(case("t")))
        self.assertEqual(len(report["flaky"]), 1)
        self.assertEqual(report["flaky"][0]["failures"], 0)
        self.assertEqual(report["flaky"][0]["retried_passes"], 1)

    def test_ranking_by_rate_then_failures_then_name(self):
        docs = [suite(case("a", status="fail"), case("b"), case("c", status="fail")),
                suite(case("a"), case("b", status="fail"), case("c")),
                suite(case("a"), case("b"), case("c"))]
        order = [f["test"].split("::")[1] for f in analyse(*docs)["flaky"]]
        self.assertEqual(order, ["a", "b", "c"])

    def test_single_run_has_no_flaky_tests(self):
        report = analyse(suite(case("t", status="fail")))
        self.assertEqual(report["flaky"], [])
        self.assertEqual(len(report["failing"]), 1)
        self.assertIn("Only one run", jr.render_markdown(report))


class TimingTests(unittest.TestCase):
    def test_slowest_tests_use_mean_and_percent_of_total(self):
        report = analyse(suite(case("slow", time=8), case("fast", time=2)),
                         suite(case("slow", time=12), case("fast", time=2)))
        slow = report["slow_tests"]
        self.assertEqual([s["test"].split("::")[1] for s in slow], ["slow", "fast"])
        self.assertEqual(slow[0]["mean_seconds"], 10.0)
        self.assertEqual(slow[0]["max_seconds"], 12.0)
        self.assertEqual(slow[0]["percent_of_total"], 83.3)
        self.assertEqual(report["summary"]["total_mean_seconds"], 12.0)

    def test_groups_by_file_then_class(self):
        report = analyse(suite(case("a", time=3, file="tests/test_one.py"), case("b", time=1, file="tests/test_one.py"),
                               case("c", time=2, file="tests/test_two.py"), case("d", cls="com.x.Slow", time=6)))
        groups = {g["group"]: g for g in report["slow_groups"]}
        self.assertEqual(groups["tests/test_one.py"]["mean_seconds"], 4.0)
        self.assertEqual(groups["tests/test_one.py"]["tests"], 2)
        self.assertEqual(groups["com.x.Slow"]["percent_of_total"], 50.0)
        self.assertEqual(report["slow_groups"][0]["group"], "com.x.Slow")
        self.assertAlmostEqual(sum(g["percent_of_total"] for g in report["slow_groups"]), 100.0, places=0)

    def test_zero_total_time_does_not_divide_by_zero(self):
        report = analyse(suite(case("a", time=0)))
        self.assertEqual(report["slow_tests"][0]["percent_of_total"], 0.0)


class NormaliserTests(unittest.TestCase):
    def test_numbers_ids_addresses_paths_urls_and_timestamps(self):
        n = jr.normalise_message
        self.assertEqual(n("Timeout after 30.5s on attempt 3"), "Timeout after Ns on attempt N")
        self.assertEqual(n("object at 0x7f3a1c2b5d90"), "object at ADDR")
        self.assertEqual(n("open /var/tmp/run-1234/out.txt failed"), "open PATH failed")
        self.assertEqual(n(r"open C:\Users\ci\work\out.txt failed"), "open PATH failed")
        self.assertEqual(n("GET https://api.shop.example/v1/orders/42?x=1 returned 503"), "GET URL returned N")
        self.assertEqual(n("at 2026-11-13T09:10:11Z"), "at TIMESTAMP")
        self.assertEqual(n("id 3f2b8c1e-aaaa-4bbb-8ccc-0123456789ab missing"), "id UUID missing")
        self.assertEqual(n("sha deadbeefcafe1234 changed"), "sha ID changed")

    def test_keeps_words_and_identifiers_with_digits(self):
        self.assertEqual(jr.normalise_message("sqlite3.IntegrityError: UNIQUE constraint failed: reservations.sku"),
                         "sqlite3.IntegrityError: UNIQUE constraint failed: reservations.sku")
        self.assertEqual(jr.normalise_message("py3 expected 'abc'"), "py3 expected 'abc'")

    def test_slash_in_dates_and_ratios_is_not_a_path(self):
        self.assertEqual(jr.normalise_message("expected 11/13/2026 got 3/4"), "expected N/N/N got N/N")

    def test_whitespace_collapsed_and_truncated(self):
        self.assertEqual(jr.normalise_message("a   b\n c"), "a b c")
        self.assertEqual(len(jr.normalise_message("x" * 500)), 160)

    def test_clusters_group_equal_failures_and_separate_different_ones(self):
        report = analyse(
            suite(case("a", status="fail", message="row 17 missing"), case("b", status="fail", message="row 99 missing"),
                  case("c", status="fail", message="boom")),
            suite(case("a", status="fail", message="row 4 missing")))
        clusters = report["clusters"]
        self.assertEqual(len(clusters), 2)
        top = clusters[0]
        self.assertEqual(top["pattern"], "AssertionError: row N missing")
        self.assertEqual(top["count"], 3)
        self.assertEqual(top["tests"], ["tests.test_a.TestA::a", "tests.test_a.TestA::b"])
        self.assertEqual(top["runs"], ["run1.xml", "run2.xml"])
        self.assertEqual(top["sample"], "AssertionError: row 17 missing")  # the first real message
        self.assertEqual(clusters[1]["pattern"], "AssertionError: boom")

    def test_type_is_not_duplicated_when_message_already_has_it(self):
        report = analyse(suite(case("a", status="fail", message="TimeoutError: slow", kind="TimeoutError")))
        self.assertEqual(report["clusters"][0]["pattern"], "TimeoutError: slow")

    def test_retried_pass_message_joins_clusters(self):
        report = analyse(suite(case("a", status="flaky", message="connection reset by peer")))
        self.assertEqual(report["clusters"][0]["count"], 1)


class CauseHintTests(unittest.TestCase):
    def test_each_cause(self):
        h = jr.cause_hint
        self.assertEqual(h("TimeoutError: timed out waiting for mailbox"), "timing")
        self.assertEqual(h("UNIQUE constraint failed: users.email"), "ordering/shared state")
        self.assertEqual(h("ConnectionError: Connection refused"), "network")
        self.assertEqual(h("HTTP 503 Service Unavailable"), "network")
        self.assertEqual(h("datetime.date(2026, 1, 2) != datetime.date(2026, 1, 1) near midnight"), "time-zone/date")
        self.assertEqual(h("OSError: [Errno 24] Too many open files"), "resource limits")
        self.assertEqual(h("seed 12345 produced a different shuffle"), "randomness")
        self.assertEqual(h("AssertionError: 'a' != 'b'"), "unknown")
        self.assertEqual(h(""), "unknown")


class LoadingTests(unittest.TestCase):
    def test_directory_file_and_missing_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "a" / "run1.xml", suite(case("t")))
            write(root / "a" / "notes.txt", "not xml")
            write(root / "run2.xml", suite(case("t")))
            runs, warnings = jr.load_runs([str(root), str(root / "nope.xml")])
            self.assertEqual(len(runs), 2)
            self.assertEqual(len(warnings), 1)
            self.assertIn("no such file", warnings[0])
            single, _ = jr.load_runs([str(root / "run2.xml"), str(root / "run2.xml")])
            self.assertEqual(len(single), 1)  # the same file twice is one run

    def test_bad_xml_is_skipped_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp) / "good.xml", suite(case("t")))
            write(Path(tmp) / "bad.xml", "<testsuite><nope>")
            write(Path(tmp) / "other.xml", "<html/>")
            runs, warnings = jr.load_runs([tmp])
            self.assertEqual([r["label"] for r in runs], ["good.xml"])
            self.assertEqual(len(warnings), 2)

    def test_labels_disambiguate_same_file_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            for run in ("101", "102"):
                write(Path(tmp) / run / "junit.xml", suite(case("t")))
            runs, _ = jr.load_runs([tmp])
            self.assertEqual([r["label"] for r in runs], ["101/junit.xml", "102/junit.xml"])

    def test_run_per_dir_merges_files_in_one_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            for run in ("r1", "r2"):
                write(Path(tmp) / run / "api.xml", suite(case("api_test")))
                write(Path(tmp) / run / "web.xml", suite(case("web_test")))
            runs, _ = jr.load_runs([tmp], run_per="dir")
            self.assertEqual([r["label"] for r in runs], ["r1", "r2"])
            self.assertEqual([len(r["cases"]) for r in runs], [2, 2])
            by_file, _ = jr.load_runs([tmp], run_per="file")
            self.assertEqual(len(by_file), 4)

    def test_empty_directory_reports_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs, warnings = jr.load_runs([tmp])
            self.assertEqual(runs, [])
            self.assertIn("no .xml files", warnings[0])


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.report = analyse(
            suite(case("wobbly", cls="tests.x.TestX", time=2.0), case("slow|pipe", time=9.0, cls="tests.x.TestX")),
            suite(case("wobbly", cls="tests.x.TestX", status="fail", message="timeout | waiting"),
                  case("slow|pipe", time=11.0, cls="tests.x.TestX")))

    def test_markdown_sections_and_escaping(self):
        text = jr.render_markdown(self.report)
        for heading in ("# JUnit report", "## Runs", "## Flaky tests (1)", "## Consistently failing (0)",
                        "## Slowest tests", "## Slowest files and classes", "## Failure clusters (1)"):
            self.assertIn(heading, text)
        self.assertIn("`tests.x.TestX::wobbly`", text)
        self.assertIn("50%", text)
        self.assertIn("slow\\|pipe", text)  # pipes escaped so tables stay intact
        self.assertNotIn("\r", text)
        self.assertTrue(text.endswith("\n"))

    def test_top_limits_rows(self):
        many = analyse(*[suite(*[case(f"t{i}", time=i + 1) for i in range(6)])] * 2)
        text = jr.render_markdown(many, top=2)
        self.assertEqual(text.count("| `tests.test_a.TestA::t"), 2)
        self.assertEqual(jr.render_markdown(many, top=0).count("| `tests.test_a.TestA::t"), 6)

    def test_no_failures_message(self):
        text = jr.render_markdown(analyse(suite(case("t")), suite(case("t"))))
        self.assertIn("No failures in these runs.", text)
        self.assertIn("None found.", text)

    def test_json_is_serialisable_and_stable(self):
        a = json.dumps(self.report, sort_keys=True)
        b = json.dumps(analyse(
            suite(case("wobbly", cls="tests.x.TestX", time=2.0), case("slow|pipe", time=9.0, cls="tests.x.TestX")),
            suite(case("wobbly", cls="tests.x.TestX", status="fail", message="timeout | waiting"),
                  case("slow|pipe", time=11.0, cls="tests.x.TestX"))), sort_keys=True)
        self.assertEqual(a, b)


class CliTests(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = jr.main(argv)
        return code, out.getvalue(), err.getvalue()

    def make_dir(self, tmp):
        write(Path(tmp) / "run1.xml", suite(case("t"), case("bad", status="fail")))
        write(Path(tmp) / "run2.xml", suite(case("t", status="fail", message="timeout"), case("bad", status="fail")))
        write(Path(tmp) / "run3.xml", suite(case("t"), case("bad", status="fail")))

    def test_markdown_default_and_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_dir(tmp)
            code, out, err = self.run_main([tmp])
            self.assertEqual((code, err), (0, ""))
            self.assertIn("1 flaky, 1 consistently failing", out)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_dir(tmp)
            code, out, _ = self.run_main([tmp, "--json"])
            data = json.loads(out)
            self.assertEqual(data["summary"]["runs"], 3)
            self.assertEqual(data["flaky"][0]["test"], "tests.test_a.TestA::t")

    def test_fail_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_dir(tmp)
            self.assertEqual(self.run_main([tmp, "--fail-on", "flaky"])[0], 1)
            self.assertEqual(self.run_main([tmp, "--fail-on", "failing"])[0], 1)
            self.assertEqual(self.run_main([tmp, "--fail-on", "any"])[0], 1)
            self.assertEqual(self.run_main([tmp, "--fail-on", "none"])[0], 0)
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp) / "r1.xml", suite(case("t")))
            write(Path(tmp) / "r2.xml", suite(case("t")))
            self.assertEqual(self.run_main([tmp, "--fail-on", "any"])[0], 0)

    def test_no_usable_input_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = self.run_main([tmp])
            self.assertEqual(code, 2)
            self.assertIn("no usable JUnit XML", err)
            self.assertEqual(out, "")
            write(Path(tmp) / "bad.xml", "garbage")
            self.assertEqual(self.run_main([tmp])[0], 2)

    def test_out_file_uses_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_dir(tmp)
            target = Path(tmp) / "report" / "r.md"
            target.parent.mkdir()
            code, out, _ = self.run_main([tmp, "-o", str(target)])
            self.assertEqual((code, out), (0, ""))
            data = target.read_bytes()
            self.assertIn(b"# JUnit report", data)
            self.assertNotIn(b"\r\n", data)

    def test_out_creates_missing_folders_and_reports_unwritable_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_dir(tmp)
            nested = Path(tmp) / "testdoc" / "deep" / "r.md"
            self.assertEqual(self.run_main([tmp, "-o", str(nested)])[0], 0)
            self.assertTrue(nested.exists())
            blocker = write(Path(tmp) / "afile", "x")
            code, _, err = self.run_main([tmp, "-o", str(blocker / "r.md")])
            self.assertEqual(code, 2)
            self.assertIn("cannot write", err)

    def test_min_runs_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_dir(tmp)
            _, out, _ = self.run_main([tmp, "--json", "--min-runs", "4"])
            self.assertEqual(json.loads(out)["summary"]["flaky"], 0)

    def test_runs_as_a_script(self):
        example = ROOT / "examples" / "junit"
        proc = subprocess.run([sys.executable, "-I", str(SCRIPT), str(example), "--top", "3"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("# JUnit report", proc.stdout)


if __name__ == "__main__":
    unittest.main()
