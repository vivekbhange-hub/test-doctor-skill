#!/usr/bin/env python3
"""junit_report: find flaky tests, slow tests and failure clusters across JUnit XML files.

Give it the JUnit XML from several CI runs of the same suite (files or directories). Each file is
one run (use --run-per dir to treat each directory as one run). It reports:

  * flaky tests: passed in some runs and failed or errored in others (or retried and passed),
    with pass and fail counts, flake rate and the runs they failed in
  * consistently failing tests
  * the slowest tests and the slowest files or classes, with their share of total time
  * failure clusters: messages with numbers, ids, addresses and paths stripped, grouped, with a
    count and one real sample

Handles pytest, Jest (jest-junit), Maven Surefire, gotestsum and other tools that write
<testsuites> or <testsuite> roots. The cause hints are keyword matches, not diagnoses.
Standard library only, deterministic.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

RETRY_TAGS = {"flakyFailure", "flakyError", "rerunFailure", "rerunError"}
FAIL_OUTCOMES = {"fail", "error"}

# Applied in order; each pattern is replaced by a fixed token so equal failures compare equal.
NORMALISERS = [
    (re.compile(r"https?://[^\s'\")>\]]+"), "URL"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "UUID"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"), "TIMESTAMP"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "ADDR"),
    (re.compile(r"(?<![\w.])(?:[A-Za-z]:)?(?:[\\/][\w.@+~-]+){2,}[\\/]?"), "PATH"),
    (re.compile(r"\b[0-9a-fA-F]{12,}\b"), "ID"),
    (re.compile(r"\b\d+(?:\.\d+)?"), "N"),
]

# Keyword hints only. First match with the highest count wins; ties go to the earlier entry.
CAUSE_PATTERNS = [
    ("timing", r"time(?:d)? ?out|timeout|deadline|waiting for|not ready|still running|took longer|"
               r"race condition|eventually|stale element"),
    ("network", r"connection (?:refused|reset|aborted|error)|econn\w+|enotfound|getaddrinfo|"
                r"name or service|name resolution|\bdns\b|\bsocket|\bssl\b|\btls\b|max retries exceeded|"
                r"bad gateway|service unavailable|gateway time-?out|\b50[234]\b|unreachable|network"),
    ("resource limits", r"out ?of ?memory|\boom\b|memoryerror|too many open files|enospc|no space left|"
                        r"address already in use|eaddrinuse|resource temporarily unavailable|"
                        r"cannot allocate|disk quota|\bkilled\b|heap space|rate limit|\b429\b"),
    ("time-zone/date", r"time ?zone|\btz\b|\butc\b|daylight|\bdst\b|midnight|datetime\.date|"
                       r"off by one day|leap (?:day|year)|strftime"),
    ("randomness", r"\brandom|\bseed\b|shuffl|nondetermin|hash ?seed"),
    ("ordering/shared state", r"already exists|duplicate (?:key|entry)|unique constraint|integrityerror|"
                              r"no such table|database is locked|already (?:registered|in use|open|started)|"
                              r"left ?over|polluted|\bshared\b"),
]
CAUSE_REGEXES = [(name, re.compile(rx, re.I)) for name, rx in CAUSE_PATTERNS]


def local_name(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def parse_time(value) -> float:
    try:
        return max(0.0, float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0.0


def case_id(classname: str, name: str) -> str:
    """classname::name, collapsing Jest-style entries where both are the same string."""
    if classname and name and classname != name:
        return f"{classname}::{name}"
    return name or classname or "(unnamed)"


def first_lines(text: str, count: int = 5) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[:count])


def read_case(el, suites) -> dict:
    classname = el.get("classname") or ""
    name = el.get("name") or ""
    failing = None
    skipped = False
    retried = False
    retry_message = ""
    for child in el:
        tag = local_name(child.tag)
        if tag in ("failure", "error") and failing is None:
            failing = child
            failing_outcome = "fail" if tag == "failure" else "error"
        elif tag == "skipped":
            skipped = True
        elif tag in RETRY_TAGS:
            retried = True
            if not retry_message:
                retry_message = (child.get("message") or first_lines(child.text, 1)).strip()
    case = {"id": case_id(classname, name), "outcome": "pass", "retried": False, "message": "",
            "kind": "", "detail": "", "time": parse_time(el.get("time"))}
    if failing is not None:
        case["outcome"] = failing_outcome
        case["kind"] = (failing.get("type") or "").strip()
        case["message"] = (failing.get("message") or "").strip() or first_lines(failing.text, 1)
        case["detail"] = first_lines(failing.text)
    elif skipped:
        case["outcome"] = "skip"
    elif retried:
        case["retried"] = True
        case["message"] = retry_message
    group = el.get("file")
    for suite in reversed(suites):
        group = group or suite.get("file")
    if not group:
        group = classname if classname and classname != name else ""
    for suite in reversed(suites):
        group = group or suite.get("name")
    case["group"] = group or "(unknown)"
    return case


def walk(elem, suites, out) -> None:
    for child in elem:
        tag = local_name(child.tag)
        if tag == "testsuite":
            walk(child, suites + [child], out)
        elif tag == "testsuites":
            walk(child, suites, out)
        elif tag == "testcase":
            out.append(read_case(child, suites))


def parse_junit(data: bytes) -> list:
    """Return the list of case dicts in one JUnit XML document. Raises ValueError if unusable."""
    if b"<!ENTITY" in data:
        raise ValueError("entity declarations are not accepted in JUnit files")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"not valid XML ({exc})")
    if local_name(root.tag) not in ("testsuites", "testsuite", "testcase"):
        raise ValueError("root element is not testsuites or testsuite")
    cases = []
    if local_name(root.tag) == "testcase":
        cases.append(read_case(root, []))
    else:
        walk([root], [], cases)  # walk() handles a testsuites or testsuite root as a child
    return cases


def make_labels(keys) -> list:
    """Shortest trailing path pieces that make every label unique."""
    for depth in range(1, 8):
        labels = ["/".join(k.parts[-depth:]) for k in keys]
        if len(set(labels)) == len(labels):
            return labels
    return [k.as_posix() for k in keys]


def collect_files(paths) -> list:
    files, problems = [], []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found = sorted(f for f in p.rglob("*.xml") if f.is_file())
            if not found:
                problems.append(f"{raw}: no .xml files found")
            files.extend(found)
        elif p.is_file():
            files.append(p)
        else:
            problems.append(f"{raw}: no such file or directory")
    seen, unique = set(), []
    for f in files:
        key = f.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique, problems


def load_runs(paths, run_per: str = "file"):
    """Return (runs, warnings). A run is {"label": str, "cases": [...]}."""
    files, warnings = collect_files(paths)
    by_key = OrderedDict()
    for f in files:
        try:
            cases = parse_junit(f.read_bytes())
        except (OSError, ValueError) as exc:
            warnings.append(f"{f.name}: skipped, {exc}")
            continue
        key = f.resolve() if run_per == "file" else f.resolve().parent
        by_key.setdefault(key, []).extend(cases)
    keys = list(by_key)
    labels = make_labels(keys) if keys else []
    return [{"label": lab, "cases": by_key[k]} for lab, k in zip(labels, keys)], warnings


def normalise_message(text: str, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    for rx, token in NORMALISERS:
        text = rx.sub(token, text)
    return text[:limit]


def cause_hint(text: str) -> str:
    best, best_count = "unknown", 0
    for name, rx in CAUSE_REGEXES:
        count = len(rx.findall(text or ""))
        if count > best_count:
            best, best_count = name, count
    return best


def resolve_attempts(cases: list) -> dict:
    """Collapse several entries for one test in one run (retry plugins) into one outcome."""
    executed = [c for c in cases if c["outcome"] != "skip"]
    if not executed:
        return dict(cases[0])
    failed = [c for c in executed if c["outcome"] in FAIL_OUTCOMES]
    result = dict(failed[0] if failed else executed[0])
    result["time"] = sum(c["time"] for c in executed)
    if failed and len(failed) == len(executed):
        return result
    if failed:  # failed and passed in the same run
        result["outcome"] = "pass"
        result["retried"] = True
        return result
    result["retried"] = any(c["retried"] for c in executed)
    if result["retried"]:
        result["message"] = next((c["message"] for c in executed if c["retried"] and c["message"]), "")
    return result


class TestStat:
    __slots__ = ("id", "group", "passes", "fails", "retried", "skips", "failed_in", "times", "messages")

    def __init__(self, tid: str, group: str):
        self.id, self.group = tid, group
        self.passes = self.fails = self.retried = self.skips = 0
        self.failed_in, self.times, self.messages = [], [], []

    @property
    def executed(self) -> int:
        return self.passes + self.fails + self.retried

    @property
    def mean_time(self) -> float:
        return sum(self.times) / len(self.times) if self.times else 0.0


def analyse(runs: list, min_runs: int = 1) -> dict:
    stats = OrderedDict()
    failures = []  # (test id, raw message, run label)
    run_rows = []
    for run in runs:
        per_test = OrderedDict()
        for case in run["cases"]:
            per_test.setdefault(case["id"], []).append(case)
        row = {"label": run["label"], "tests": 0, "failed": 0, "skipped": 0, "time": 0.0}
        for tid, cases in per_test.items():
            res = resolve_attempts(cases)
            stat = stats.setdefault(tid, TestStat(tid, res["group"]))
            row["tests"] += 1
            if res["outcome"] == "skip":
                stat.skips += 1
                row["skipped"] += 1
                continue
            stat.times.append(res["time"])
            row["time"] += res["time"]
            if res["outcome"] in FAIL_OUTCOMES:
                stat.fails += 1
                stat.failed_in.append(run["label"])
                row["failed"] += 1
            elif res["retried"]:
                stat.retried += 1
            else:
                stat.passes += 1
            if res["outcome"] in FAIL_OUTCOMES or res["retried"]:
                text = res["message"] or res["detail"]
                if res["kind"] and not text.startswith(res["kind"]):
                    text = f"{res['kind']}: {text}" if text else res["kind"]
                if text.strip():
                    first = text.strip().splitlines()[0].strip()
                    stat.messages.append(first)
                    failures.append((tid, first, run["label"], res["detail"]))
        run_rows.append(row)

    eligible = [s for s in stats.values() if s.executed >= min_runs and s.executed > 0]
    flaky = []
    for s in eligible:
        if (s.passes > 0 and s.fails > 0) or s.retried > 0:
            bad = s.fails + s.retried
            sample = next(iter(s.messages), "")
            flaky.append({
                "test": s.id, "passes": s.passes, "failures": s.fails, "retried_passes": s.retried,
                "runs": s.executed, "flake_rate": round(bad / s.executed, 4),
                "failed_in": s.failed_in, "sample": sample[:200],
                "likely_cause": cause_hint(" ".join(dict.fromkeys(s.messages))),
            })
    flaky.sort(key=lambda r: (-r["flake_rate"], -r["failures"], r["test"]))
    failing = []
    for s in eligible:
        if s.fails == s.executed:
            sample = next(iter(s.messages), "")
            failing.append({"test": s.id, "runs": s.executed, "sample": sample[:200],
                            "likely_cause": cause_hint(" ".join(dict.fromkeys(s.messages)))})
    failing.sort(key=lambda r: (-r["runs"], r["test"]))

    timed = [s for s in stats.values() if s.times]
    total = sum(s.mean_time for s in timed)

    def pct(value: float) -> float:
        return round(100.0 * value / total, 1) if total > 0 else 0.0

    slow_tests = [{"test": s.id, "mean_seconds": round(s.mean_time, 3), "max_seconds": round(max(s.times), 3),
                   "percent_of_total": pct(s.mean_time)}
                  for s in sorted(timed, key=lambda s: (-s.mean_time, s.id))]
    groups = defaultdict(lambda: [0.0, 0])
    for s in timed:
        groups[s.group][0] += s.mean_time
        groups[s.group][1] += 1
    slow_groups = [{"group": g, "tests": n, "mean_seconds": round(t, 3), "percent_of_total": pct(t)}
                   for g, (t, n) in sorted(groups.items(), key=lambda kv: (-kv[1][0], kv[0]))]

    clusters = OrderedDict()
    for tid, raw, label, detail in failures:
        key = normalise_message(raw)
        c = clusters.setdefault(key, {"pattern": key, "count": 0, "tests": [], "runs": [],
                                      "sample": raw[:200], "_text": []})
        c["count"] += 1
        if tid not in c["tests"]:
            c["tests"].append(tid)
        if label not in c["runs"]:
            c["runs"].append(label)
        if len(c["_text"]) < 3:
            c["_text"].append(raw + " " + detail)
    cluster_list = []
    for c in clusters.values():
        c["likely_cause"] = cause_hint(" ".join(c.pop("_text")))
        c["tests"] = sorted(c["tests"])
        cluster_list.append(c)
    cluster_list.sort(key=lambda c: (-c["count"], c["pattern"]))

    return {
        "summary": {
            "runs": len(runs), "tests": len(stats), "flaky": len(flaky), "failing": len(failing),
            "executions": sum(s.executed for s in stats.values()),
            "total_mean_seconds": round(total, 3), "min_runs": min_runs,
        },
        "runs": [dict(r, time=round(r["time"], 3)) for r in run_rows],
        "flaky": flaky, "failing": failing, "slow_tests": slow_tests, "slow_groups": slow_groups,
        "clusters": cluster_list,
    }


def cell(text, limit: int = 110) -> str:
    text = " ".join(str(text).split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def code(text, limit: int = 110) -> str:
    return "`" + cell(str(text).replace("`", "'"), limit) + "`"


def limited(items: list, top: int) -> list:
    return items if top <= 0 else items[:top]


def render_markdown(report: dict, top: int = 10) -> str:
    s = report["summary"]
    out = ["# JUnit report", "",
           f"{s['runs']} run(s), {s['tests']} distinct tests, {s['executions']} executions. "
           f"{s['flaky']} flaky, {s['failing']} consistently failing."]
    if s["runs"] < 2:
        out += ["", "Only one run was given: flakiness needs at least two runs of the same code."]
    out += ["", "## Runs", "", "| Run | Tests | Failed | Skipped | Time (s) |", "|---|---:|---:|---:|---:|"]
    for r in report["runs"]:
        out.append(f"| {cell(r['label'])} | {r['tests']} | {r['failed']} | {r['skipped']} | {r['time']:.2f} |")

    rows = limited(report["flaky"], top)
    out += ["", f"## Flaky tests ({len(report['flaky'])})", ""]
    if rows:
        out += ["Flake rate is failing runs divided by runs executed. Likely cause is a keyword match on the "
                "failure text, so treat it as a place to start reading.", "",
                "| Test | Pass | Fail | Flake rate | Failed in | Likely cause |", "|---|---:|---:|---:|---|---|"]
        for r in rows:
            fails = r["failures"] + r["retried_passes"]
            out.append(f"| {code(r['test'])} | {r['passes']} | {fails} | {r['flake_rate'] * 100:.0f}% | "
                       f"{cell(', '.join(r['failed_in']) or 'retried in-run', 40)} | {r['likely_cause']} |")
        if len(rows) < len(report["flaky"]):
            out += ["", f"Showing {len(rows)} of {len(report['flaky'])}; use --top 0 for all."]
    else:
        out.append("None found.")

    rows = limited(report["failing"], top)
    out += ["", f"## Consistently failing ({len(report['failing'])})", ""]
    if rows:
        out += ["| Test | Runs | Sample message |", "|---|---:|---|"]
        for r in rows:
            out.append(f"| {code(r['test'])} | {r['runs']} | {cell(r['sample'], 80)} |")
    else:
        out.append("None found.")

    rows = limited(report["slow_tests"], top)
    out += ["", f"## Slowest tests (mean of {s['runs']} run(s), {s['total_mean_seconds']:.2f}s total)", "",
            "| Test | Mean (s) | Max (s) | % of total |", "|---|---:|---:|---:|"]
    for r in rows:
        out.append(f"| {code(r['test'])} | {r['mean_seconds']:.2f} | {r['max_seconds']:.2f} | "
                   f"{r['percent_of_total']:.1f}% |")

    rows = limited(report["slow_groups"], top)
    out += ["", "## Slowest files and classes", "", "| File or class | Tests | Mean (s) | % of total |",
            "|---|---:|---:|---:|"]
    for r in rows:
        out.append(f"| {code(r['group'])} | {r['tests']} | {r['mean_seconds']:.2f} | {r['percent_of_total']:.1f}% |")

    rows = limited(report["clusters"], top)
    out += ["", f"## Failure clusters ({len(report['clusters'])})", ""]
    if rows:
        out += ["Numbers, ids, addresses, paths, URLs and timestamps are replaced before grouping.", "",
                "| # | Count | Tests | Pattern | Sample |", "|---:|---:|---:|---|---|"]
        for i, c in enumerate(rows, 1):
            out.append(f"| {i} | {c['count']} | {len(c['tests'])} | {code(c['pattern'], 100)} | "
                       f"{cell(c['sample'], 100)} |")
        out += ["", "Tests per cluster:", ""]
        for i, c in enumerate(rows, 1):
            names = ", ".join(c["tests"][:3]) + (f" (+{len(c['tests']) - 3} more)" if len(c["tests"]) > 3 else "")
            out.append(f"{i}. {cell(names, 200)}")
    else:
        out.append("No failures in these runs.")
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="junit_report.py",
        description="Flaky tests, consistently failing tests, slowest tests and failure clusters "
                    "from JUnit XML files (one file per CI run).")
    parser.add_argument("paths", nargs="+", help="JUnit XML files or directories of them")
    parser.add_argument("--run-per", choices=("file", "dir"), default="file",
                        help="what counts as one run: each file (default) or each directory")
    parser.add_argument("--top", type=int, default=10, help="rows per section, 0 for all (default 10)")
    parser.add_argument("--min-runs", type=int, default=1,
                        help="ignore tests executed in fewer than N runs when listing flaky/failing")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    parser.add_argument("-o", "--out", help="write the report to this file instead of stdout")
    parser.add_argument("--fail-on", choices=("none", "flaky", "failing", "any"), default="none",
                        help="exit 1 when flaky and/or consistently failing tests exist (default none)")
    args = parser.parse_args(argv)

    runs, warnings = load_runs(args.paths, args.run_per)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if not runs:
        print("error: no usable JUnit XML files found", file=sys.stderr)
        return 2
    report = analyse(runs, max(1, args.min_runs))
    if args.json:
        text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    else:
        text = render_markdown(report, args.top)
    if args.out:
        try:
            Path(args.out).resolve().parent.mkdir(parents=True, exist_ok=True)
            with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(text)
    bad = ((args.fail_on in ("flaky", "any") and report["summary"]["flaky"])
           or (args.fail_on in ("failing", "any") and report["summary"]["failing"]))
    return 1 if bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
