#!/usr/bin/env python3
"""weak_tests: static scan for tests that cannot fail, or that hide failures.

Reads test files (Python unittest/pytest, JavaScript/TypeScript Jest/Vitest/Mocha, Go, Java JUnit)
and reports, with file:line, severity and a rule id:

  WT001 high    no assertion at all
  WT002 high    assertion that cannot fail (assertTrue(True), expect(1).toBe(1), assertEqual(x, x))
  WT003 medium  the only assertion is "is not None / defined"
  WT004 high    empty test body
  WT005 high    expect(...) with no matcher
  WT006 medium  skipped or xfail with no reason
  WT007 low     sleep inside a test
  WT008 high    broad exception caught and swallowed inside a test
  WT009 medium  commented-out assertion
  WT010 low     the only assertion is a snapshot

Python is analysed with the `ast` module. The other languages use bracket matching and regular
expressions, so they can miss things and can very occasionally misfire on unusual code; the
report is a list of places to look, not a verdict. Suppress a finding with a comment containing
`testdoc: ignore WT007` on the reported line or the line above it. Standard library only.
"""
from __future__ import annotations

import argparse
import ast
import bisect
import io
import json
import os
import re
import sys
import tokenize
from pathlib import Path

RULES = {
    "WT001": ("high", "No assertion"),
    "WT002": ("high", "Assertion that cannot fail"),
    "WT003": ("medium", "Only a not-None / defined check"),
    "WT004": ("high", "Empty test body"),
    "WT005": ("high", "expect() with no matcher"),
    "WT006": ("medium", "Skipped or xfail without a reason"),
    "WT007": ("low", "Sleep in a test"),
    "WT008": ("high", "Broad exception swallowed"),
    "WT009": ("medium", "Commented-out assertion"),
    "WT010": ("low", "Snapshot is the only assertion"),
}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
LANGS = {".py": "python", ".js": "js", ".jsx": "js", ".ts": "js", ".tsx": "js", ".mjs": "js", ".cjs": "js",
         ".go": "go", ".java": "java"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", "vendor", "target",
             ".tox", ".mypy_cache", ".pytest_cache", "site-packages"}
MAX_BYTES = 2_000_000
IGNORE_RE = re.compile(r"testdoc:\s*ignore(?P<ids>(?:[\s,]+WT\d{3})*)")


def is_test_file(name: str, parts) -> bool:
    suffix = os.path.splitext(name)[1]
    lang = LANGS.get(suffix)
    if lang == "python":
        return (name.startswith("test_") or name.endswith("_test.py")) and name != "conftest.py"
    if lang == "js":
        stem = name[: -len(suffix)]
        return bool(re.search(r"\.(?:test|spec)$", stem)) or "__tests__" in parts
    if lang == "go":
        return name.endswith("_test.go")
    if lang == "java":
        return bool(re.search(r"(?:Tests?|IT|TestCase)\.java$|^Test\w*\.java$", name))
    return False


def collect_files(paths) -> list:
    found = []
    for raw in paths:
        if os.path.isfile(raw):
            if os.path.splitext(raw)[1] in LANGS:
                found.append(raw)
        elif os.path.isdir(raw):
            for root, dirs, names in os.walk(raw):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                parts = set(Path(root).parts)
                for name in sorted(names):
                    if is_test_file(name, parts):
                        found.append(os.path.join(root, name))
    seen, unique = set(), []
    for f in found:
        shown = os.path.normpath(f).replace("\\", "/")
        if shown not in seen:
            seen.add(shown)
            unique.append(shown)
    return sorted(unique)


class Collector:
    """Accumulates findings for one file and tracks comment lines for the reason/ignore checks."""

    def __init__(self, path: str, lines: list, comment_lines: set, comment_only: set):
        self.path, self.lines = path, lines
        self.comment_lines, self.comment_only = comment_lines, comment_only
        self.findings = []

    def add(self, rule: str, line: int, test: str, message: str) -> None:
        if self.ignored(rule, line):
            return
        item = {"rule": rule, "severity": RULES[rule][0], "file": self.path, "line": line,
                "test": test, "message": message}
        if item not in self.findings:
            self.findings.append(item)

    def ignored(self, rule: str, line: int) -> bool:
        for n in (line, line - 1):
            if 1 <= n <= len(self.lines):
                m = IGNORE_RE.search(self.lines[n - 1])
                if m:
                    ids = re.findall(r"WT\d{3}", m.group("ids") or "")
                    if not ids or rule in ids:
                        return True
        return False

    def has_reason_comment(self, line: int) -> bool:
        return line in self.comment_lines or (line - 1) in self.comment_only


def unit_findings(col: Collector, units: list, test: str, test_line: int, nomatcher: bool = False) -> None:
    """Turn a test's assertion units [(kind, line, snippet)] into WT001/WT002/WT003/WT010 findings."""
    if not units:
        if not nomatcher:
            col.add("WT001", test_line, test, "no assertion; this test only fails if the code under test raises")
        return
    for kind, line, snippet in units:
        if kind == "taut":
            col.add("WT002", line, test, f"assertion can never fail: {snippet}")
    rest = [k for k, _, _ in units if k != "taut"]
    if rest and all(k == "notnone" for k in rest):
        col.add("WT003", test_line, test, "the only assertion checks that a value exists; it does not say what it is")
    if rest and all(k == "snapshot" for k in rest):
        col.add("WT010", test_line, test, "the only assertion is a snapshot; a snapshot approved without "
                                          "review can lock in a bug")


# ---------------------------------------------------------------- Python

ASSERT_PREFIXES = ("assert", "check", "verify", "validate", "ensure", "expect")
ASSERT_NAMES = {"fail", "raises", "warns", "deprecated_call"}
SKIP_DECORATORS = {
    "unittest.skip": 0, "skip": 0, "unittest.skipIf": 1, "skipIf": 1, "unittest.skipUnless": 1,
    "skipUnless": 1, "unittest.expectedFailure": None, "expectedFailure": None,
    "pytest.mark.skip": "kw", "pytest.mark.skipif": "kw", "pytest.mark.xfail": "kw",
    "mark.skip": "kw", "mark.skipif": "kw", "mark.xfail": "kw",
}
COMMENTED_ASSERT_PY = re.compile(
    r"^#\s*(?:assert(?!\s+(?:that|the|a|an|this|it|is|are)\b)\b|self\.assert\w*\(|assert_\w+\(|"
    r"pytest\.raises|expect\()")


def dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def call_name(call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def is_assert_name(name: str) -> bool:
    low = name.lower()
    return name in ASSERT_NAMES or low.startswith(ASSERT_PREFIXES)


def const_truth(node):
    """Return (True, bool) if node is a constant, else (False, None)."""
    if isinstance(node, ast.Constant):
        return True, bool(node.value)
    return False, None


def has_call(node) -> bool:
    return any(isinstance(n, ast.Call) for n in ast.walk(node))


def same_expr(a, b) -> bool:
    return ast.dump(a) == ast.dump(b) and not has_call(a)


def is_none(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def classify_py_assert(test) -> str:
    if "snapshot" in ast.dump(test).lower():
        return "snapshot"
    known, truth = const_truth(test)
    if known and truth:
        return "taut"
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        known, truth = const_truth(test.operand)
        if known and not truth:
            return "taut"
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op, left, right = test.ops[0], test.left, test.comparators[0]
        if isinstance(op, (ast.IsNot, ast.NotEq)) and is_none(right):
            return "notnone"
        if isinstance(op, (ast.Eq, ast.Is, ast.LtE, ast.GtE)) and same_expr(left, right):
            return "taut"
        if isinstance(left, ast.Constant) and isinstance(right, ast.Constant) and isinstance(op, ast.Eq) \
                and left.value == right.value:
            return "taut"
    return "plain"


def classify_py_call(call) -> str:
    name = call_name(call)
    if "snapshot" in ast.dump(call.func).lower() or "snapshot" in name.lower():
        return "snapshot"
    args = call.args
    if name in ("assertTrue", "assertFalse") and args:
        known, truth = const_truth(args[0])
        if known and truth == (name == "assertTrue"):
            return "taut"
    if name in ("assertEqual", "assertEquals", "assertIs", "assertIn", "assert_equal") and len(args) >= 2:
        if same_expr(args[0], args[1]):
            return "taut"
        if isinstance(args[0], ast.Constant) and isinstance(args[1], ast.Constant) and args[0].value == args[1].value:
            return "taut"
    if name == "assertIsNotNone" or (name in ("assertNotEqual", "assertIsNot") and len(args) >= 2
                                      and is_none(args[1])):
        return "notnone"
    return "plain"


def snippet_of(node, text_lines) -> str:
    line = text_lines[node.lineno - 1].strip() if 0 < node.lineno <= len(text_lines) else ""
    return line[:80]


def py_comments(text: str):
    comments = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                comments[tok.start[0]] = tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return comments


def python_tests(body, cls=None):
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if cls is not None and node.name.startswith("test"):
                yield node, cls
            elif cls is None and (node.name.startswith("test_") or node.name == "test"):
                yield node, None
        elif isinstance(node, ast.ClassDef):
            test_like = node.name.startswith("Test") or node.name.endswith(("Test", "Tests")) or any(
                dotted(b).split(".")[-1].endswith(("TestCase", "Test")) for b in node.bases)
            if test_like:
                for item in python_tests(node.body, node):
                    yield item


def collect_helpers(tree) -> dict:
    """Map function and method names defined in the file to their definitions (for one-file helper lookup)."""
    helpers = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            helpers.setdefault(node.name, []).append(node)
    return helpers


def helper_asserts(name: str, helpers: dict, depth: int = 3, seen=None) -> bool:
    """True if a function defined in this file asserts, directly or through other helpers it calls."""
    seen = set() if seen is None else seen
    if name in seen or name not in helpers:
        return False
    seen.add(name)
    for fn in helpers[name]:
        for node in ast.walk(fn):
            if isinstance(node, ast.Assert):
                return True
            if isinstance(node, ast.Raise) and node.exc is not None and                     dotted(node.exc.func if isinstance(node.exc, ast.Call) else node.exc) == "AssertionError":
                return True
            if isinstance(node, ast.Call):
                cname = call_name(node)
                if is_assert_name(cname):
                    return True
                if depth > 0 and helper_asserts(cname, helpers, depth - 1, seen):
                    return True
    return False


def skip_reason_missing(dec) -> bool:
    call = dec if isinstance(dec, ast.Call) else None
    name = dotted(dec.func if call else dec)
    if name not in SKIP_DECORATORS:
        return False
    want = SKIP_DECORATORS[name]
    if want is None:
        return True
    if call is None:
        return True
    reason = None
    for kw in call.keywords:
        if kw.arg == "reason":
            reason = kw.value
    if reason is None and isinstance(want, int) and len(call.args) > want:
        reason = call.args[want]
    if reason is None and want == 0 and call.args:
        reason = call.args[0]
    if reason is None:
        return True
    return isinstance(reason, ast.Constant) and not str(reason.value or "").strip()


def analyse_python(path: str, text: str):
    lines = text.split("\n")
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        return [], 0, f"{path}: not parsed as Python ({exc})"
    comments = py_comments(text)
    comment_only = {n for n in comments if lines[n - 1].lstrip().startswith("#")}
    col = Collector(path, lines, set(comments), comment_only)
    tests = list(python_tests(tree.body))
    helpers = collect_helpers(tree)
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for dec in cls.decorator_list:
            if skip_reason_missing(dec) and not col.has_reason_comment(dec.lineno):
                col.add("WT006", dec.lineno, cls.name, "skipped or xfail without a reason")
    for func, cls in tests:
        name = f"{cls.name}.{func.name}" if cls else func.name
        for dec in func.decorator_list:
            if skip_reason_missing(dec) and not col.has_reason_comment(dec.lineno):
                col.add("WT006", dec.lineno, name, "skipped or xfail without a reason")
        body = list(func.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        if all(isinstance(s, ast.Pass) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
               for s in body):
            col.add("WT004", func.lineno, name, "empty test body")
            continue
        units = []
        aliases = {t.id for n in ast.walk(func) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Attribute)
                   and is_assert_name(n.value.attr) for t in n.targets if isinstance(t, ast.Name)}
        for node in ast.walk(func):
            if isinstance(node, ast.Assert):
                units.append((classify_py_assert(node.test), node.lineno, snippet_of(node, lines)))
            elif isinstance(node, ast.Raise) and node.exc is not None and \
                    dotted(node.exc.func if isinstance(node.exc, ast.Call) else node.exc) == "AssertionError":
                units.append(("plain", node.lineno, ""))
            elif isinstance(node, ast.Call):
                cname = call_name(node)
                if is_assert_name(cname):
                    units.append((classify_py_call(node), node.lineno, snippet_of(node, lines)))
                elif isinstance(node.func, ast.Name) and cname in aliases:  # eq = self.assertEqual; eq(a, b)
                    units.append(("plain", node.lineno, ""))
                elif cname != func.name and cname in helpers and helper_asserts(cname, helpers):
                    units.append(("plain", node.lineno, ""))
                elif cname in ("sleep",) and (isinstance(node.func, ast.Name) or
                                              dotted(node.func.value) in ("time", "asyncio", "anyio", "trio", "gevent")):
                    col.add("WT007", node.lineno, name, "sleep in a test: slow, and a timing guess that goes flaky")
                elif cname in ("skip", "skipTest", "xfail") and dotted(node.func) in (
                        "pytest.skip", "self.skipTest", "pytest.xfail", "unittest.SkipTest"):
                    arg = node.args[0] if node.args else None
                    for kw in node.keywords:
                        if kw.arg == "reason":
                            arg = kw.value
                    if (arg is None or (isinstance(arg, ast.Constant) and not str(arg.value or "").strip())) \
                            and not col.has_reason_comment(node.lineno):
                        col.add("WT006", node.lineno, name, "skipped or xfail without a reason")
            elif isinstance(node, ast.Try):
                for handler in node.handlers:
                    t = handler.type
                    names = [dotted(e) for e in (t.elts if isinstance(t, ast.Tuple) else [t])] if t else [""]
                    if "" in names or any(n.split(".")[-1] in ("Exception", "BaseException") for n in names):
                        rescued = any(
                            isinstance(n, (ast.Raise, ast.Assert))
                            or (isinstance(n, ast.Call) and is_assert_name(call_name(n)))
                            for h in handler.body for n in ast.walk(h))
                        if not rescued:
                            col.add("WT008", handler.lineno, name,
                                    "catches a broad exception and carries on, so failures are hidden")
        unit_findings(col, units, name, func.lineno)
        end = getattr(func, "end_lineno", func.lineno)
        for ln, comment in comments.items():
            if func.lineno <= ln <= end and ln in comment_only and COMMENTED_ASSERT_PY.match(comment):
                col.add("WT009", ln, name, "commented-out assertion: the test checks less than it appears to")
    return col.findings, len(tests), None


# ---------------------------------------------------------------- bracket languages

def blank(chars: list, a: int, b: int) -> None:
    for k in range(a, min(b, len(chars))):
        if chars[k] != "\n":
            chars[k] = " "


def mask_source(text: str, lang: str):
    """Return (no_comments, masked): comments blanked; masked also blanks string contents."""
    n = len(text)
    nc, mk = list(text), list(text)
    i = 0
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j == -1 else j
            blank(nc, i, j)
            blank(mk, i, j)
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            blank(nc, i, j)
            blank(mk, i, j)
            i = j
        elif c in "\"'`":
            if lang == "java" and text.startswith('"""', i):
                j = text.find('"""', i + 3)
                j = n if j == -1 else j + 3
                blank(mk, i + 3, j - 3)
                i = j
                continue
            j = i + 1
            while j < n:
                ch = text[j]
                if ch == "\\" and not (lang == "go" and c == "`"):
                    j += 2
                    continue
                if ch == c or (ch == "\n" and c != "`"):
                    break
                j += 1
            blank(mk, i + 1, j)
            i = j + 1
        else:
            i += 1
    return "".join(nc), "".join(mk)


def match_close(masked: str, open_idx: int) -> int:
    pairs = {"(": ")", "{": "}", "[": "]"}
    open_ch = masked[open_idx]
    close_ch = pairs[open_ch]
    depth = 0
    for i in range(open_idx, len(masked)):
        ch = masked[i]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


class Source:
    """A bracket-language file: raw/no-comment/masked text, line lookup and comment line sets."""

    def __init__(self, path: str, text: str, lang: str):
        self.path, self.lang, self.text = path, lang, text
        self.nc, self.mk = mask_source(text, lang)
        self.lines = text.split("\n")
        self.newlines = [i for i, ch in enumerate(text) if ch == "\n"]
        nc_lines = self.nc.split("\n")
        comment_lines, comment_only = set(), set()
        for i, (o, n) in enumerate(zip(self.lines, nc_lines), 1):
            if o.rstrip() != n.rstrip():
                comment_lines.add(i)
                if not n.strip():
                    comment_only.add(i)
        self.col = Collector(path, self.lines, comment_lines, comment_only)

    def line(self, offset: int) -> int:
        return bisect.bisect_left(self.newlines, offset) + 1


JS_CHAIN = re.compile(r"(?:\s*\.\s*[A-Za-z_$][\w$]*(?:\s*\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\))?)*")
CHAI_WORDS = {"equal", "equals", "eql", "eq", "ok", "true", "false", "null", "undefined", "exist", "empty",
              "include", "contain", "contains", "match", "throw", "above", "below", "least", "most",
              "lengthOf", "property", "keys", "members", "satisfy", "closeTo", "instanceOf", "a", "an"}
SNAPSHOT_MATCHERS = {"toMatchSnapshot", "toMatchInlineSnapshot", "toMatchFileSnapshot",
                     "toThrowErrorMatchingSnapshot", "toThrowErrorMatchingInlineSnapshot"}
JS_LITERAL = r"(?:true|false|null|undefined|-?\d+(?:\.\d+)?|'[^']*'|\"[^\"]*\")"
JS_TAUT = [
    re.compile(r"^expect\s*\(\s*(?P<v>" + JS_LITERAL + r")\s*\)\s*\.\s*(?:toBe|toEqual|toStrictEqual)"
               r"\s*\(\s*(?P=v)\s*\)"),
    re.compile(r"^expect\s*\(\s*true\s*\)\s*\.\s*(?:toBeTruthy\s*\(\s*\)|to\s*\.\s*(?:be\s*\.\s*)?(?:true|ok))"),
    re.compile(r"^expect\s*\(\s*false\s*\)\s*\.\s*(?:toBeFalsy\s*\(\s*\)|to\s*\.\s*(?:be\s*\.\s*)?false)"),
]
JS_NOT_NONE = re.compile(r"\.\s*(?:toBeDefined\s*\(|not\s*\.\s*(?:toBeNull|toBeUndefined)\s*\(|"
                         r"not\s*\.\s*(?:toBe|toEqual|toStrictEqual)\s*\(\s*(?:null|undefined)\s*\)|"
                         r"to\s*\.\s*exist\b|not\s*\.\s*to\s*\.\s*be\s*\.\s*(?:null|undefined)\b)")
JS_ASSERT_TAUT = [
    re.compile(r"^assert(?:\s*\.\s*ok)?\s*\(\s*true\s*\)"),
    re.compile(r"^assert\s*\.\s*(?:equal|strictEqual|deepEqual|deepStrictEqual)\s*\(\s*(?P<v>" + JS_LITERAL
               + r")\s*,\s*(?P=v)\s*[,)]"),
]
JS_PLAIN = [
    re.compile(r"(?<![\w$])assert\b"), re.compile(r"\.\s*should\b"), re.compile(r"\.\s*expect\s*\("),
    re.compile(r"(?<![\w$])(?:check|verify|validate|ensure|fail)\w*\s*\("), re.compile(r"\bthrow\b"),
    re.compile(r"\bsinon\s*\.\s*assert\b"),
]
JS_SLEEP = [re.compile(r"(?<![\w$.])sleep\s*\("), re.compile(r"\.\s*waitForTimeout\s*\("),
            re.compile(r"\bcy\s*\.\s*wait\s*\(\s*\d"), re.compile(r"new\s+Promise\s*\([^;]*?setTimeout\s*\(")]
JS_CATCH = re.compile(r"\bcatch\s*(?:\(\s*[\w$]*\s*\))?\s*\{")
JS_PROMISE_CATCH = re.compile(r"\.\s*catch\s*\(\s*(?:\(\s*[\w$]*\s*\)|[\w$]+)?\s*=>\s*"
                              r"(?:\{\s*\}|null|undefined|void 0)\s*\)")
JS_COMMENTED = re.compile(r"^\s*(?://|/\*+|\*)\s*(?:await\s+)?(?:expect\s*\(|assert\b|[\w$.]+\.should\b|"
                          r"[\w$.]*\.(?:toBe|toEqual|toHave\w+|toMatch\w*|toThrow\w*)\()")
JS_SKIP = re.compile(r"(?<![\w$.])(?:(?:it|test|describe)\s*\.\s*skip|x(?:it|test|describe))\s*\(")
JS_OPENER = re.compile(r"(?<![\w$.])(?P<fn>it|test|fit|xit|xtest)(?P<mods>(?:\s*\.\s*\w+)*)\s*(?=[(])")


def js_callback_body(mk: str, open_idx: int, close_idx: int):
    """Return (start, end) of the callback body inside the call parens, or None."""
    m = re.compile(r"=>|\bfunction\b").search(mk, open_idx, close_idx)
    if not m:
        return None
    pos = m.end()
    if m.group() == "function":
        p = mk.find("(", pos, close_idx)
        if p == -1:
            return None
        pc = match_close(mk, p)
        if pc == -1:
            return None
        pos = pc + 1
    b = pos
    while b < close_idx and mk[b].isspace():
        b += 1
    if m.group() == "=>" and (b >= close_idx or mk[b] != "{"):
        return (pos, close_idx)
    b = mk.find("{", pos, close_idx)
    if b == -1:
        return None
    e = match_close(mk, b)
    return (b + 1, e) if e != -1 else None


def js_tests(src: Source):
    mk = src.mk
    for m in JS_OPENER.finditer(mk):
        pos = m.end()
        mods = re.findall(r"\w+", m.group("mods"))
        if "each" in mods and mk[pos] == "(":
            ec = match_close(mk, pos)
            if ec == -1:
                continue
            pos = ec + 1
            while pos < len(mk) and mk[pos].isspace():
                pos += 1
        if pos >= len(mk) or mk[pos] != "(":
            continue
        close = match_close(mk, pos)
        if close == -1:
            continue
        title = re.match(r"\s*(['\"`])(.*?)\1", src.nc[pos + 1:close], re.S)
        name = title.group(2) if title else "(unnamed)"
        body = js_callback_body(mk, pos + 1, close)
        if body:
            yield name, src.line(m.start()), body[0], body[1]


def analyse_js(src: Source):
    mk, nc, col = src.mk, src.nc, src.col
    count = 0
    for m in JS_SKIP.finditer(mk):
        first = re.match(r"\s*['\"`]", nc[m.end():m.end() + 80])
        line = src.line(m.start())
        if first and not col.has_reason_comment(line):
            col.add("WT006", line, "(skipped)", "skipped without a reason (add a comment saying why)")
    for name, tline, start, end in js_tests(src):
        count += 1
        if not mk[start:end].strip():
            col.add("WT004", tline, name, "empty test body")
            continue
        units, nomatcher = [], 0
        for em in re.finditer(r"(?<![\w$.])expect\s*\(", mk[:end]):
            if em.start() < start:
                continue
            close = match_close(mk, em.end() - 1)
            if close == -1:
                continue
            chain_end = JS_CHAIN.match(mk, close + 1).end()
            names = re.findall(r"\.\s*([A-Za-z_$][\w$]*)", mk[close + 1:chain_end])
            line = src.line(em.start())
            if not any((n.startswith("to") and len(n) > 2 and n[2].isupper()) or n in CHAI_WORDS for n in names):
                nomatcher += 1
                col.add("WT005", line, name, "expect(...) has no matcher, so nothing is asserted")
                continue
            statement = " ".join(nc[em.start():chain_end].split())
            if any(rx.search(statement) for rx in JS_TAUT):
                units.append(("taut", line, statement[:80]))
            elif any(n in SNAPSHOT_MATCHERS for n in names):
                units.append(("snapshot", line, ""))
            elif JS_NOT_NONE.search(statement):
                units.append(("notnone", line, ""))
            else:
                units.append(("plain", line, ""))
        for am in re.finditer(r"(?<![\w$.])assert\b", mk[start:end]):
            stmt_start = start + am.start()
            stmt = " ".join(nc[stmt_start:stmt_start + 160].split())
            if any(rx.search(stmt) for rx in JS_ASSERT_TAUT):
                units.append(("taut", src.line(stmt_start), stmt[:80]))
            elif not any(u[1] == src.line(stmt_start) for u in units):
                units.append(("plain", src.line(stmt_start), ""))
        for rx in JS_PLAIN:
            for _ in rx.finditer(mk, start, end):
                if not any(u[0] == "plain" for u in units):
                    units.append(("plain", tline, ""))
                break
        unit_findings(col, units, name, tline, nomatcher=bool(nomatcher))
        for rx in JS_SLEEP:
            for sm in rx.finditer(mk, start, end):
                col.add("WT007", src.line(sm.start()), name, "sleep in a test: slow, and a timing guess that goes flaky")
        for cm in JS_CATCH.finditer(mk, start, end):
            ob = cm.end() - 1
            cb = match_close(mk, ob)
            if cb != -1 and not re.search(r"\b(?:throw|expect|assert|fail|reject|done)\b", nc[ob:cb]):
                col.add("WT008", src.line(cm.start()), name, "catch block swallows the error, so failures are hidden")
        for cm in JS_PROMISE_CATCH.finditer(mk, start, end):
            if not units:  # with real assertions present, ignoring an expected rejection is common and fine
                col.add("WT008", src.line(cm.start()), name, ".catch() swallows the error, so failures are hidden")
        for ln in range(src.line(start), src.line(end) + 1):
            if ln in col.comment_only and JS_COMMENTED.match(src.lines[ln - 1]):
                col.add("WT009", ln, name, "commented-out assertion: the test checks less than it appears to")
    return col.findings, count


GO_FUNC = re.compile(r"(?m)^func\s+(Test(?:[A-Z_0-9]\w*)?)\s*\(\s*(\w+)\s+\*testing\.T\s*\)\s*\{")
GO_TAUT = [
    re.compile(r"(?:assert|require)\s*\.\s*True\s*\(\s*\w+\s*,\s*true\s*\)"),
    re.compile(r"(?:assert|require)\s*\.\s*False\s*\(\s*\w+\s*,\s*false\s*\)"),
    re.compile(r"(?:assert|require)\s*\.\s*Equal\s*\(\s*\w+\s*,\s*(?P<v>[\w.\"'-]+)\s*,\s*(?P=v)\s*\)"),
]
GO_SNAPSHOT = re.compile(r"\b(?:cupaloy|snaps|goldie|autogold)\b|\.MatchSnapshot\b")
GO_PLAIN = [re.compile(r"\b(?:assert|require)\s*\.\s*\w+\s*\("),
            re.compile(r"(?<![\w$])(?:check|verify|assert|require|expect|validate)\w*\s*\("),
            re.compile(r"\bpanic\s*\("), re.compile(r"\b(?:suite\s*\.\s*Run|RunSpecs\w*)\s*\(")]
GO_COMMENTED = re.compile(r"^\s*//\s*(?:(?:assert|require)\s*\.\s*\w+\s*\(|\w+\s*\.\s*(?:Error|Errorf|Fatal|Fatalf)\s*\()")


def analyse_go(src: Source):
    mk, nc, col = src.mk, src.nc, src.col
    count = 0
    for m in GO_FUNC.finditer(mk):
        count += 1
        name, tvar = m.group(1), m.group(2)
        ob = m.end() - 1
        cb = match_close(mk, ob)
        if cb == -1:
            continue
        start, end = ob + 1, cb
        tline = src.line(m.start())
        if not mk[start:end].strip():
            col.add("WT004", tline, name, "empty test body")
            continue
        tnames = {tvar} | set(re.findall(r"(\w+)\s+\*testing\.(?:T|B)\b", mk[start:end]))
        tn = "|".join(sorted(re.escape(t) for t in tnames))
        t_assert = re.compile(r"\b(?:" + tn + r")\s*\.\s*(?:Errorf?|Fatalf?|Fail|FailNow)\s*\(")
        units = []
        for tm in t_assert.finditer(mk, start, end):
            units.append(("plain", src.line(tm.start()), ""))
        for rx in GO_PLAIN:
            for pm in rx.finditer(mk, start, end):
                line = src.line(pm.start())
                stmt = " ".join(nc[pm.start():].split("\n", 1)[0].split())
                if any(r.match(stmt) for r in GO_TAUT):
                    units.append(("taut", line, stmt.split(")")[0][:80] + ")"))
                elif re.match(r"(?:assert|require)\s*\.\s*NotNil\s*\(", stmt):
                    units.append(("notnone", line, ""))
                elif GO_SNAPSHOT.search(stmt):
                    units.append(("snapshot", line, ""))
                else:
                    units.append(("plain", line, ""))
        if GO_SNAPSHOT.search(mk[start:end]) and not any(u[0] == "snapshot" for u in units):
            units.append(("snapshot", tline, ""))
        # one entry per line is enough
        seen, dedup = set(), []
        for u in units:
            key = (u[1], u[0] == "taut")
            if key not in seen:
                seen.add(key)
                dedup.append(u)
        unit_findings(col, dedup, name, tline)
        for sm in re.finditer(r"\btime\s*\.\s*Sleep\s*\(", mk[start:end]):
            col.add("WT007", src.line(start + sm.start()), name, "sleep in a test: slow, and a timing guess that goes flaky")
        for rm in re.finditer(r"(?m)^[ \t]*(?:_\s*=\s*)?recover\s*\(\s*\)\s*$", mk[start:end]):
            col.add("WT008", src.line(start + rm.start()), name, "recover() result is discarded, so a panic is hidden")
        skip_rx = re.compile(r"\b(?:" + tn + r")\s*\.\s*(Skip|Skipf|SkipNow)\s*\(")
        for sm in skip_rx.finditer(mk, start, end):
            args = ""
            if sm.group(1) != "SkipNow":
                pc = match_close(mk, sm.end() - 1)
                args = nc[sm.end():pc].strip() if pc != -1 else ""
            line = src.line(sm.start())
            if args in ("", '""', "``") and not col.has_reason_comment(line):
                col.add("WT006", line, name, "skipped without a reason")
        for ln in range(src.line(start), src.line(end) + 1):
            if ln in col.comment_only and GO_COMMENTED.match(src.lines[ln - 1]):
                col.add("WT009", ln, name, "commented-out assertion: the test checks less than it appears to")
    return col.findings, count


JAVA_TEST = re.compile(r"@(?:Test|ParameterizedTest|RepeatedTest|TestFactory)\b")
JAVA_ASSERT = re.compile(r"(?<![\w$])assert\w*\s*\(")
JAVA_PLAIN = [re.compile(r"(?<![\w$])(?:fail|verify\w*|check\w*|validate\w*|ensure\w*)\s*\("),
              re.compile(r"\.\s*andExpect\s*\("), re.compile(r"\b(?:Assertions|Assert)\s*\."),
              re.compile(r"\bthrown\s*\.\s*expect\b|\bexpectedException\b|@Test\s*\(\s*expected\b"),
              re.compile(r"\bthen\s*\(")]
JAVA_TAUT = [
    re.compile(r"^assertTrue\s*\(\s*true\s*\)"), re.compile(r"^assertFalse\s*\(\s*false\s*\)"),
    re.compile(r"^assertNull\s*\(\s*null\s*\)"),
    re.compile(r"^assertThat\s*\(\s*true\s*\)\s*\.\s*isTrue\s*\(\s*\)"),
    re.compile(r"^assert(?:Equals|Same)\s*\(\s*(?P<v>[\w.\"'-]+)\s*,\s*(?P=v)\s*[,)]"),
]
JAVA_SNAPSHOT = re.compile(r"toMatchSnapshot|Approvals\s*\.\s*verify|matchesSnapshot", re.I)
JAVA_CATCH = re.compile(r"\bcatch\s*\(\s*(?:final\s+)?(?:Exception|Throwable|RuntimeException|Error)\s+\w+\s*\)\s*\{")
JAVA_COMMENTED = re.compile(r"^\s*//\s*(?:assert\w*\s*\(|verify\w*\s*\(|Assert\w*\s*\.|\w+\s*\.\s*(?:isEqualTo|isTrue)\b)")


def analyse_java(src: Source):
    mk, nc, col = src.mk, src.nc, src.col
    count = 0
    for m in re.finditer(r"@(?:Disabled|Ignore)\b(?:\s*\(([^)]*)\))?", nc):
        reason = re.search(r"\"[^\"]+\"", m.group(1) or "")
        line = src.line(m.start())
        if not reason and not col.has_reason_comment(line):
            col.add("WT006", line, "(disabled)", "@Disabled/@Ignore without a reason")
    for m in JAVA_TEST.finditer(mk):
        vm = re.compile(r"\bvoid\s+(\w+)\s*\(").search(mk, m.end(), m.end() + 600)
        if not vm or re.search(r"[;{}]", mk[m.end():vm.start()].replace("(", " ")) and \
                re.search(r"[;{}]", mk[m.end():vm.start()]):
            continue
        name = vm.group(1)
        pc = match_close(mk, vm.end() - 1)
        if pc == -1:
            continue
        bm = re.compile(r"\s*(?:throws\s+[\w.,\s<>]+?)?\s*\{").match(mk, pc + 1)
        if not bm:
            continue
        ob = bm.end() - 1
        cb = match_close(mk, ob)
        if cb == -1:
            continue
        count += 1
        start, end = ob + 1, cb
        tline = src.line(vm.start())
        if not mk[start:end].strip():
            col.add("WT004", tline, name, "empty test body")
            continue
        units = []
        if re.match(r"@Test\s*\(\s*(?:[^)]*\b)?expected\b", nc[m.start():m.start() + 120]):
            units.append(("plain", tline, ""))
        for am in JAVA_ASSERT.finditer(mk, start, end):
            semi = mk.find(";", am.start(), end)
            stmt = " ".join(nc[am.start():(semi if semi != -1 else end)].split())
            line = src.line(am.start())
            if any(rx.search(stmt) for rx in JAVA_TAUT):
                units.append(("taut", line, stmt[:80]))
            elif stmt.startswith("assertNotNull") or re.search(r"\.\s*isNotNull\s*\(", stmt):
                units.append(("notnone", line, ""))
            elif JAVA_SNAPSHOT.search(stmt):
                units.append(("snapshot", line, ""))
            else:
                units.append(("plain", line, ""))
        for rx in JAVA_PLAIN:
            hit = rx.search(mk, start, end)
            if hit:
                units.append(("snapshot" if JAVA_SNAPSHOT.search(nc[hit.start():hit.start() + 60]) else "plain",
                              src.line(hit.start()), ""))
        unit_findings(col, units, name, tline)
        for sm in re.finditer(r"\bThread\s*\.\s*sleep\s*\(|\bTimeUnit\s*\.\s*\w+\s*\.\s*sleep\s*\(", mk[start:end]):
            col.add("WT007", src.line(start + sm.start()), name, "sleep in a test: slow, and a timing guess that goes flaky")
        for cm in JAVA_CATCH.finditer(mk, start, end):
            ob2 = cm.end() - 1
            cb2 = match_close(mk, ob2)
            if cb2 != -1 and not re.search(r"\b(?:throw|fail|assert\w*|verify)\b", nc[ob2:cb2]):
                col.add("WT008", src.line(cm.start()), name, "catches a broad exception and carries on, so failures are hidden")
        for ln in range(src.line(start), src.line(end) + 1):
            if ln in col.comment_only and JAVA_COMMENTED.match(src.lines[ln - 1]):
                col.add("WT009", ln, name, "commented-out assertion: the test checks less than it appears to")
    return col.findings, count


def analyse_file(path: str, text: str):
    """Return (findings, test_count, warning or None)."""
    text = text.replace("\r\n", "\n")
    lang = LANGS.get(os.path.splitext(path)[1])
    if lang == "python":
        return analyse_python(path, text)
    src = Source(path, text, lang)
    fn = {"js": analyse_js, "go": analyse_go, "java": analyse_java}[lang]
    findings, count = fn(src)
    return findings, count, None


def scan(paths, ignore=(), min_severity="low"):
    files = collect_files(paths)
    findings, warnings, tests = [], [], 0
    for f in files:
        try:
            if os.path.getsize(f) > MAX_BYTES:
                warnings.append(f"{f}: skipped, larger than {MAX_BYTES} bytes")
                continue
            with open(f, "rb") as handle:
                text = handle.read().decode("utf-8", errors="replace")
        except OSError as exc:
            warnings.append(f"{f}: cannot read ({exc})")
            continue
        found, count, warn = analyse_file(f, text)
        if warn:
            warnings.append(warn)
        tests += count
        findings.extend(found)
    findings = [f for f in findings if f["rule"] not in ignore
                and SEVERITY_RANK[f["severity"]] >= SEVERITY_RANK[min_severity]]
    findings.sort(key=lambda f: (-SEVERITY_RANK[f["severity"]], f["file"], f["line"], f["rule"]))
    counts_rule, counts_sev = {}, {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts_rule[f["rule"]] = counts_rule.get(f["rule"], 0) + 1
        counts_sev[f["severity"]] += 1
    return {"summary": {"files": len(files), "tests": tests, "findings": len(findings),
                        "by_severity": counts_sev, "by_rule": dict(sorted(counts_rule.items()))},
            "findings": findings, "warnings": warnings}


def render_markdown(report: dict) -> str:
    s = report["summary"]
    sev = s["by_severity"]
    out = ["# Weak test scan", "",
           f"Scanned {s['files']} test file(s) and {s['tests']} tests. {s['findings']} finding(s): "
           f"{sev['high']} high, {sev['medium']} medium, {sev['low']} low."]
    if not report["findings"]:
        out += ["", "No weak tests found by these rules. That does not prove the tests are good."]
        return "\n".join(out) + "\n"
    out += ["", "## By rule", "", "| Rule | Severity | Count | Meaning |", "|---|---|---:|---|"]
    for rule, count in s["by_rule"].items():
        out.append(f"| {rule} | {RULES[rule][0]} | {count} | {RULES[rule][1]} |")
    out += ["", "## Findings", "", "| Location | Rule | Severity | Test | Problem |", "|---|---|---|---|---|"]
    for f in report["findings"]:
        test = f["test"].replace("|", "\\|")
        out.append(f"| `{f['file']}:{f['line']}` | {f['rule']} | {f['severity']} | `{test}` | {f['message']} |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="weak_tests.py",
        description="Find tests that cannot fail or that hide failures: no assertions, tautologies, "
                    "empty bodies, unexplained skips, sleeps, swallowed exceptions and more.")
    parser.add_argument("paths", nargs="+", help="test files or directories to scan")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    parser.add_argument("--fail-on", choices=("high", "medium", "low"),
                        help="exit 1 if any finding is at or above this severity")
    parser.add_argument("--min-severity", choices=("low", "medium", "high"), default="low",
                        help="hide findings below this severity")
    parser.add_argument("--ignore", default="", help="comma-separated rule ids to skip, e.g. WT007,WT010")
    parser.add_argument("-o", "--out", help="write the report to this file instead of stdout")
    args = parser.parse_args(argv)

    ignore = {r.strip().upper() for r in args.ignore.split(",") if r.strip()}
    unknown = ignore - set(RULES)
    if unknown:
        print(f"error: unknown rule id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    if not collect_files(args.paths):
        print("error: no test files found (looked for test_*.py, *.test.js, *_test.go, *Test.java)", file=sys.stderr)
        return 2
    report = scan(args.paths, ignore, args.min_severity)
    for w in report["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    text = (json.dumps(report, indent=2, sort_keys=True) + "\n") if args.json else render_markdown(report)
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
    if args.fail_on:
        floor = SEVERITY_RANK[args.fail_on]
        if any(SEVERITY_RANK[f["severity"]] >= floor for f in report["findings"]):
            return 1
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
