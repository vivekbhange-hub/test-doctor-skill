#!/usr/bin/env python3
"""cov_gaps: turn a coverage file into a ranked "where to write tests first" list.

Reads lcov (lcov.info), Cobertura XML or coverage.py JSON (format is auto-detected). For each file
it reports line coverage, the uncovered line ranges, branches never taken and functions never
called, and ranks files by priority = uncovered lines x (uncovered lines / executable lines), so a
big file that is mostly untested beats a tiny one and beats a big, mostly covered one.

--changed-since REF restricts the report to files that `git diff --name-only REF` lists. That is
the only time this script runs git. Standard library only, deterministic.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_RANGES_SHOWN = 20


class FileCov:
    """Coverage facts for one source file."""

    def __init__(self, path: str):
        self.path = path
        self.lines = {}      # executable line -> hit count
        self.branches = {}   # line -> {"missing": int, "total": int or None, "targets": [str]}
        self.functions = {}  # name -> {"line": int, "hits": int, "span": (first, last) or None}

    def add_line(self, line: int, hits: int) -> None:
        self.lines[line] = self.lines.get(line, 0) + max(0, hits)

    def add_branch(self, line: int, missing: int, total, targets=()) -> None:
        b = self.branches.setdefault(line, {"missing": 0, "total": 0, "targets": []})
        b["missing"] += missing
        b["total"] = None if (total is None or b["total"] is None) else b["total"] + total
        b["targets"].extend(targets)

    def add_function(self, name: str, line: int, hits: int, span=None) -> None:
        f = self.functions.setdefault(name, {"line": line, "hits": 0, "span": span})
        f["hits"] += max(0, hits)
        if span and not f["span"]:
            f["span"] = span


def to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_lcov(text: str) -> dict:
    files = {}
    cur = None
    fn_lines = {}
    brda = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            path = line[3:].strip()
            cur = files.setdefault(path, FileCov(path))
            fn_lines, brda = {}, {}
        elif cur is None:
            continue
        elif line.startswith("FN:"):
            parts = line[3:].split(",")
            if len(parts) >= 3:      # FN:start,end,name (lcov 2.x)
                name = ",".join(parts[2:])
                fn_lines[name] = (to_int(parts[0]), to_int(parts[1]))
            elif len(parts) == 2:
                fn_lines[parts[1]] = (to_int(parts[0]), None)
        elif line.startswith("FNDA:"):
            hits, _, name = line[5:].partition(",")
            start, end = fn_lines.get(name, (0, None))
            cur.add_function(name, start, to_int(hits), (start, end) if end else None)
        elif line.startswith("DA:"):
            parts = line[3:].split(",")
            if len(parts) >= 2:
                cur.add_line(to_int(parts[0]), to_int(parts[1]))
        elif line.startswith("BRDA:"):
            parts = line[5:].split(",")
            if len(parts) == 4:
                ln = to_int(parts[0])
                taken = parts[3].strip() not in ("-", "0", "")
                m = brda.setdefault(ln, [0, 0])
                m[1] += 1
                m[0] += 0 if taken else 1
        elif line == "end_of_record":
            for ln, (missing, total) in brda.items():
                cur.add_branch(ln, missing, total)
            for name, (start, end) in fn_lines.items():
                cur.functions.setdefault(name, {"line": start, "hits": 0, "span": (start, end) if end else None})
            cur = None
            fn_lines, brda = {}, {}
    return files


def parse_cobertura(text: str) -> dict:
    if "<!ENTITY" in text:
        raise ValueError("entity declarations are not accepted")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"not valid XML ({exc})")
    files = {}
    for cls in root.iter("class"):
        path = cls.get("filename")
        if not path:
            continue
        cov = files.setdefault(path, FileCov(path))
        for method in cls.iter("method"):
            lines = [(to_int(l.get("number")), to_int(l.get("hits"))) for l in method.iter("line")]
            if lines:
                nums = [n for n, _ in lines]
                cov.add_function(method.get("name") or "?", min(nums), max(h for _, h in lines),
                                 (min(nums), max(nums)))
        container = None
        for child in cls:
            if child.tag == "lines":
                container = child
        for line in (container if container is not None else []):
            number, hits = to_int(line.get("number")), to_int(line.get("hits"))
            cov.add_line(number, hits)
            if line.get("branch") == "true":
                conds = list(line.iter("condition"))
                cc = line.get("condition-coverage") or ""
                if "(" in cc and "/" in cc:
                    got, _, total = cc[cc.index("(") + 1:cc.index(")")].partition("/")
                    cov.add_branch(number, to_int(total) - to_int(got), to_int(total))
                elif conds:
                    missing = sum(1 for c in conds if not (c.get("coverage") or "").startswith("100"))
                    cov.add_branch(number, missing, len(conds))
    return files


def parse_coveragepy(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"not valid JSON ({exc})")
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise ValueError("JSON has no 'files' object; expected coverage.py's `coverage json` output")
    files = {}
    for path, info in data["files"].items():
        cov = files.setdefault(path, FileCov(path))
        for n in info.get("executed_lines", []):
            cov.add_line(to_int(n), 1)
        for n in info.get("missing_lines", []):
            cov.add_line(to_int(n), 0)
        executed = info.get("executed_branches") or []
        missing = info.get("missing_branches") or []
        by_line = {}
        for a, b in executed:
            by_line.setdefault(to_int(a), [[], []])[0].append(b)
        for a, b in missing:
            by_line.setdefault(to_int(a), [[], []])[1].append(b)
        have_executed = "executed_branches" in info
        for ln, (ok, bad) in by_line.items():
            if bad:
                targets = [f"{ln}->{'exit' if to_int(t) <= 0 else to_int(t)}" for t in bad]
                cov.add_branch(ln, len(bad), len(ok) + len(bad) if have_executed else None, targets)
        for name, fn in (info.get("functions") or {}).items():
            if not name:
                continue
            ex, mi = fn.get("executed_lines", []), fn.get("missing_lines", [])
            allines = [to_int(n) for n in list(ex) + list(mi)]
            if allines:
                cov.add_function(name, min(allines), 1 if ex else 0, (min(allines), max(allines)))
    return files


def detect_format(text: str):
    head = text.lstrip("﻿ \t\r\n")
    if head.startswith("{"):
        return "coveragepy"
    if head.startswith("<"):
        return "cobertura"
    if "SF:" in text:
        return "lcov"
    return None


PARSERS = {"lcov": parse_lcov, "cobertura": parse_cobertura, "coveragepy": parse_coveragepy}


def normalise_path(path: str, strip_prefix: str = "") -> str:
    p = path.replace("\\", "/")
    prefix = strip_prefix.replace("\\", "/")
    if prefix and p.startswith(prefix):
        p = p[len(prefix):].lstrip("/")
    cwd = Path.cwd().as_posix().rstrip("/") + "/"
    if p.startswith(cwd):
        p = p[len(cwd):]
    while p.startswith("./"):
        p = p[2:]
    return p


def line_ranges(uncovered, executable, boundaries=()) -> list:
    """Merge uncovered lines into (start, end) ranges, bridging lines that are not executable.

    A range never bridges across a function start listed in `boundaries`.
    """
    ranges = []
    ex = sorted(executable)
    uncovered_set = set(uncovered)
    for n in sorted(uncovered_set):
        if ranges:
            start, end = ranges[-1]
            between = [e for e in ex if end < e < n]
            crosses = any(end < b <= n for b in boundaries)
            if not crosses and all(e in uncovered_set for e in between):
                ranges[-1] = (start, n)
                continue
        ranges.append((n, n))
    return ranges


def fmt_range(r) -> str:
    return str(r[0]) if r[0] == r[1] else f"{r[0]}-{r[1]}"


def enclosing_function(cov: FileCov, line: int):
    best = None
    for name, fn in cov.functions.items():
        span = fn["span"]
        if span and span[0] <= line <= span[1]:
            if best is None or span[0] >= cov.functions[best]["span"][0]:
                best = name
    return best


def describe_branch(line: int, b: dict) -> str:
    if b["targets"]:
        return ", ".join(b["targets"])
    if b["total"] is not None:
        return f"{line} ({b['missing']}/{b['total']} untaken)"
    return f"{line} ({b['missing']} untaken)"


def analyse_file(cov: FileCov) -> dict:
    total = len(cov.lines)
    uncovered = sorted(n for n, h in cov.lines.items() if h == 0)
    covered = total - len(uncovered)
    boundaries = [fn["span"][0] for fn in cov.functions.values() if fn["span"]]
    ranges = line_ranges(uncovered, cov.lines, boundaries)
    br_missing = sum(b["missing"] for b in cov.branches.values())
    br_total = sum(b["total"] for b in cov.branches.values() if b["total"] is not None)
    br_known = all(b["total"] is not None for b in cov.branches.values())
    never = sorted(((fn["line"], name) for name, fn in cov.functions.items() if fn["hits"] == 0))
    biggest = max(ranges, key=lambda r: (r[1] - r[0], -r[0])) if ranges else None
    result = {
        "file": cov.path,
        "lines_total": total, "lines_covered": covered, "lines_uncovered": len(uncovered),
        "line_coverage": round(100.0 * covered / total, 1) if total else 100.0,
        "priority": round(len(uncovered) * len(uncovered) / total, 1) if total else 0.0,
        "uncovered_ranges": [fmt_range(r) for r in ranges],
        "branches_missing": br_missing,
        "branches_total": br_total if br_known else None,
        "uncovered_branches": [describe_branch(ln, b) for ln, b in sorted(cov.branches.items()) if b["missing"]],
        "never_called": [{"function": name, "line": line} for line, name in never],
        "biggest_block": None,
    }
    if biggest:
        result["biggest_block"] = {"range": fmt_range(biggest), "lines": sum(
            1 for n in uncovered if biggest[0] <= n <= biggest[1]), "function": enclosing_function(cov, biggest[0])}
    return result


def path_matches(cov_path: str, changed) -> bool:
    for ch in changed:
        if cov_path == ch or cov_path.endswith("/" + ch) or ch.endswith("/" + cov_path):
            return True
    return False


def changed_files(ref: str, repo=None, runner=subprocess.run) -> list:
    """Names from `git diff --name-only REF`. Raises RuntimeError with a readable message."""
    if not ref or ref.startswith("-"):
        raise RuntimeError(f"invalid git ref {ref!r}")
    cmd = ["git", "diff", "--name-only", "--diff-filter=ACMR", ref, "--"]
    try:
        proc = runner(cmd, cwd=repo, capture_output=True, text=True)
    except OSError as exc:
        raise RuntimeError(f"cannot run git: {exc}")
    if proc.returncode != 0:
        raise RuntimeError(f"git diff failed: {(proc.stderr or '').strip() or 'exit ' + str(proc.returncode)}")
    return [ln.strip().replace("\\", "/") for ln in proc.stdout.splitlines() if ln.strip()]


def build_report(files: dict, source: str, fmt: str, threshold=None, changed=None, top: int = 10,
                 strip_prefix: str = "") -> dict:
    rows = []
    for cov in files.values():
        shown = FileCov(normalise_path(cov.path, strip_prefix))
        shown.lines, shown.branches, shown.functions = cov.lines, cov.branches, cov.functions
        if shown.lines:
            rows.append(analyse_file(shown))
    all_total = sum(r["lines_total"] for r in rows)
    all_cov = sum(r["lines_covered"] for r in rows)
    br_total = sum(r["branches_total"] or 0 for r in rows)
    br_missing = sum(r["branches_missing"] for r in rows if r["branches_total"] is not None)
    scope = "all files"
    if changed is not None:
        rows = [r for r in rows if path_matches(r["file"], changed)]
        scope = f"{len(rows)} file(s) changed since the given ref"
    considered = len(rows)
    gaps = [r for r in rows if r["lines_uncovered"] or r["branches_missing"]]
    if threshold is not None:
        gaps = [r for r in gaps if r["line_coverage"] < threshold]
    gaps.sort(key=lambda r: (-r["priority"], -r["branches_missing"], r["file"]))
    return {
        "source": source, "format": fmt, "scope": scope, "threshold": threshold,
        "totals": {
            "files": len(files), "lines": all_total, "lines_covered": all_cov,
            "line_coverage": round(100.0 * all_cov / all_total, 1) if all_total else 100.0,
            "branches": br_total or None, "branches_covered": (br_total - br_missing) if br_total else None,
            "branch_coverage": round(100.0 * (br_total - br_missing) / br_total, 1) if br_total else None,
            "files_considered": considered, "files_with_gaps": len(gaps),
        },
        "files": gaps if top <= 0 else gaps[:top],
        "files_not_shown": 0 if top <= 0 else max(0, len(gaps) - top),
    }


def render_markdown(report: dict) -> str:
    t = report["totals"]
    out = ["# Where to write tests first", "",
           f"Source: `{report['source']}` ({report['format']}). Scope: {report['scope']}."]
    line = f"Lines: {t['lines_covered']}/{t['lines']} covered ({t['line_coverage']:.1f}%)."
    if report["scope"] != "all files":
        line = "Whole coverage file. " + line
    if t["branches"]:
        line += f" Branches: {t['branches_covered']}/{t['branches']} covered ({t['branch_coverage']:.1f}%)."
    out.append(line + f" Files with gaps: {t['files_with_gaps']} of {t['files_considered']}.")
    if report["threshold"] is not None:
        out.append(f"Only files below {report['threshold']:g}% line coverage are listed.")
    rows = report["files"]
    if not rows:
        out += ["", "No coverage gaps in scope."]
        return "\n".join(out) + "\n"
    out += ["", "## Ranked files", "",
            "Priority is uncovered lines multiplied by the share of the file that is uncovered.", "",
            "| # | File | Line coverage | Uncovered lines | Branches missed | Functions never called | Priority |",
            "|---:|---|---:|---:|---:|---:|---:|"]
    for i, r in enumerate(rows, 1):
        out.append(f"| {i} | `{r['file']}` | {r['line_coverage']:.1f}% | {r['lines_uncovered']} | "
                   f"{r['branches_missing']} | {len(r['never_called'])} | {r['priority']:.1f} |")
    out += ["", "## Details"]
    for i, r in enumerate(rows, 1):
        out += ["", f"### {i}. `{r['file']}` ({r['line_coverage']:.1f}%, {r['lines_uncovered']} uncovered lines)", ""]
        shown = r["uncovered_ranges"][:MAX_RANGES_SHOWN]
        more = len(r["uncovered_ranges"]) - len(shown)
        out.append(f"- Uncovered lines: {', '.join(shown) or 'none'}" + (f" (+{more} more ranges)" if more > 0 else ""))
        if r["uncovered_branches"]:
            b = r["uncovered_branches"][:MAX_RANGES_SHOWN]
            extra = len(r["uncovered_branches"]) - len(b)
            out.append(f"- Branches never taken: {', '.join(b)}" + (f" (+{extra} more)" if extra > 0 else ""))
        if r["never_called"]:
            names = ", ".join(f"`{f['function']}` (line {f['line']})" for f in r["never_called"][:8])
            more_fn = len(r["never_called"]) - 8
            out.append(f"- Functions never called: {names}" + (f" (+{more_fn} more)" if more_fn > 0 else ""))
        blk = r["biggest_block"]
        if blk:
            inside = f", inside `{blk['function']}`" if blk["function"] else ""
            out.append(f"- Largest untested block: lines {blk['range']} ({blk['lines']} uncovered{inside})")
    if report["files_not_shown"]:
        out += ["", f"{report['files_not_shown']} more file(s) with gaps not shown; use --top 0 for all."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="cov_gaps.py",
        description="Rank files by what is untested: lcov, Cobertura XML or coverage.py JSON in, "
                    "'where to write tests first' out.")
    parser.add_argument("coverage", help="path to lcov.info, cobertura XML or coverage.py JSON")
    parser.add_argument("--format", choices=("auto", "lcov", "cobertura", "coveragepy"), default="auto")
    parser.add_argument("--top", type=int, default=10, help="files to list, 0 for all (default 10)")
    parser.add_argument("--threshold", type=float, metavar="PCT",
                        help="list only files below this line coverage %%; exit 1 if there are any")
    parser.add_argument("--changed-since", metavar="REF",
                        help="only files listed by `git diff --name-only REF` (runs git)")
    parser.add_argument("--repo", help="directory to run git in (default: current directory)")
    parser.add_argument("--strip-prefix", default="", help="remove this leading path from file names")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    parser.add_argument("-o", "--out", help="write the report to this file instead of stdout")
    args = parser.parse_args(argv)

    path = Path(args.coverage)
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    fmt = args.format if args.format != "auto" else detect_format(text)
    if fmt is None:
        print("error: cannot tell the coverage format; pass --format lcov|cobertura|coveragepy", file=sys.stderr)
        return 2
    try:
        files = PARSERS[fmt](text)
    except ValueError as exc:
        print(f"error: {path}: {exc}", file=sys.stderr)
        return 2
    if not files:
        print(f"error: {path}: no files found in {fmt} data", file=sys.stderr)
        return 2
    changed = None
    if args.changed_since:
        try:
            changed = changed_files(args.changed_since, args.repo)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    report = build_report(files, Path(args.coverage).as_posix(), fmt, args.threshold, changed, args.top,
                          args.strip_prefix)
    text_out = (json.dumps(report, indent=2, sort_keys=True) + "\n") if args.json else render_markdown(report)
    if args.out:
        try:
            Path(args.out).resolve().parent.mkdir(parents=True, exist_ok=True)
            with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text_out)
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(text_out)
    return 1 if (args.threshold is not None and report["totals"]["files_with_gaps"]) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
