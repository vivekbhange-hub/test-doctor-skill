"""Tests for skills/testdoc-lint/weak_tests.py."""
import io
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from _load import ROOT, load, write

wt = load("testdoc-lint", "weak_tests")
SCRIPT = ROOT / "skills" / "testdoc-lint" / "weak_tests.py"


def found(ext, code):
    """Return sorted [(rule, line)] for a code snippet; line 1 is the first line of `code`."""
    text = textwrap.dedent(code).lstrip("\n")
    findings, _count, warning = wt.analyse_file("sample/" + ext, text)
    assert warning is None, warning
    return sorted((f["rule"], f["line"]) for f in findings)


def rules(ext, code):
    return [r for r, _ in found(ext, code)]


class PythonTests(unittest.TestCase):
    def test_no_assertion(self):
        self.assertEqual(found("test_x.py", """
            def test_runs():
                run()
        """), [("WT001", 1)])

    def test_assertion_forms_that_count(self):
        code = """
            import unittest, pytest
            class T(unittest.TestCase):
                def test_a(self):
                    self.assertEqual(f(), 1)
                def test_b(self):
                    assert f() == 1
                def test_c(self):
                    with self.assertRaises(ValueError):
                        f()
                def test_d(self):
                    with pytest.raises(ValueError):
                        f()
                def test_e(self):
                    m = make()
                    m.assert_called_once_with(1)
                def test_f(self):
                    check_total(f(), 1)
                def test_g(self):
                    self.fail("never")
                def test_h(self):
                    raise AssertionError("no")
                def test_i(self):
                    np.testing.assert_allclose(f(), 1)
        """
        self.assertEqual(found("test_x.py", code), [])

    def test_helpers_defined_in_the_same_file_that_assert_count(self):
        code = """
            import unittest
            def assert_ok(x):
                assert x
            class T(unittest.TestCase):
                def _roundtrip(self, value):
                    self.assertEqual(decode(encode(value)), value)
                def _outer(self, value):
                    self._roundtrip(value)
                def _quiet(self, value):
                    encode(value)
                def test_a(self):
                    self._roundtrip(1)
                def test_b(self):
                    self._outer(1)
                def test_c(self):
                    assert_ok(f())
                def test_d(self):
                    eq = self.assertEqual
                    eq(f(), 1)
                def test_e(self):
                    self._quiet(1)
        """
        self.assertEqual(found("test_x.py", code), [("WT001", 20)])

    def test_tautologies(self):
        code = """
            import unittest
            class T(unittest.TestCase):
                def test_a(self):
                    self.assertTrue(True)
                def test_b(self):
                    assert True
                def test_c(self):
                    assert 1 == 1
                def test_d(self):
                    x = f()
                    self.assertEqual(x, x)
                def test_e(self):
                    self.assertEqual(1, 1)
                def test_f(self):
                    self.assertFalse(False)
                def test_g(self):
                    assert not False
        """
        self.assertEqual(rules("test_x.py", code), ["WT002"] * 7)

    def test_equal_calls_are_not_tautologies(self):
        code = """
            def test_stable():
                assert f() == f()
        """
        self.assertEqual(found("test_x.py", code), [])

    def test_only_not_none(self):
        code = """
            def test_a():
                x = f()
                assert x is not None
            def test_b():
                self.assertIsNotNone(f())
            def test_c():
                x = f()
                assert x is not None
                assert x.id == 3
            def test_d():
                assert f() != None
        """
        self.assertEqual(found("test_x.py", code), [("WT003", 1), ("WT003", 4), ("WT003", 10)])

    def test_empty_bodies(self):
        code = """
            def test_pass():
                pass
            def test_doc():
                '''TODO'''
            def test_dots():
                ...
            def test_doc_and_pass():
                "later"
                pass
        """
        self.assertEqual(found("test_x.py", code), [("WT004", 1), ("WT004", 3), ("WT004", 5), ("WT004", 7)])

    def test_skips_without_reason(self):
        code = """
            import unittest, pytest
            @unittest.skip("flaky on CI, ticket 7")
            def test_a(): assert f()
            @unittest.skip("")
            def test_b(): assert f()
            @pytest.mark.skip
            def test_c(): assert f()
            @pytest.mark.skip(reason="not ready")
            def test_d(): assert f()
            @pytest.mark.xfail
            def test_e(): assert f()
            @pytest.mark.xfail(reason="bug 12")
            def test_f(): assert f()
            @pytest.mark.skipif(sys.platform == "win32", reason="posix only")
            def test_g(): assert f()
            @unittest.skipIf(sys.platform == "win32", "posix only")
            def test_h(): assert f()
            @unittest.expectedFailure
            def test_i(): assert f()
        """
        self.assertEqual(found("test_x.py", code), [("WT006", 4), ("WT006", 6), ("WT006", 10), ("WT006", 18)])

    def test_comment_counts_as_a_reason(self):
        code = """
            import pytest
            # waiting on the tax sandbox, ticket 118
            @pytest.mark.skip
            def test_a(): assert f()
            @pytest.mark.skip  # see ticket 5
            def test_b(): assert f()
        """
        self.assertEqual(found("test_x.py", code), [])

    def test_skip_calls_in_body(self):
        code = """
            import pytest
            def test_a():
                pytest.skip()
                assert f()
            def test_b():
                pytest.skip("needs gpu")
                assert f()
            def test_c(self):
                self.skipTest("")
                assert f()
        """
        self.assertEqual(found("test_x.py", code), [("WT006", 3), ("WT006", 9)])

    def test_class_level_skip(self):
        code = """
            import pytest
            @pytest.mark.skip
            class TestAll:
                def test_a(self):
                    assert f()
        """
        self.assertEqual(found("test_x.py", code), [("WT006", 2)])

    def test_sleep(self):
        code = """
            import time, asyncio
            def test_a():
                time.sleep(1)
                assert f()
            async def test_b():
                await asyncio.sleep(0.5)
                assert f()
            def test_c(client):
                client.sleep(1)
                assert f()
        """
        self.assertEqual(found("test_x.py", code), [("WT007", 3), ("WT007", 6)])

    def test_broad_except(self):
        code = """
            def test_a():
                try:
                    f()
                except Exception:
                    pass
                assert g()
            def test_b():
                try:
                    f()
                except:
                    log()
                assert g()
            def test_c():
                try:
                    f()
                except ValueError:
                    pass
                assert g()
            def test_d():
                try:
                    f()
                except Exception:
                    raise
                assert g()
            def test_e():
                try:
                    f()
                except Exception as e:
                    self.fail(str(e))
            def test_f():
                try:
                    f()
                except (KeyError, Exception):
                    assert False
        """
        self.assertEqual(found("test_x.py", code), [("WT008", 4), ("WT008", 10)])

    def test_commented_out_assertions(self):
        code = """
            def test_a():
                # assert f() == 1
                # self.assertEqual(f(), 1)
                # assert that the totals match
                assert g()
                x = 1  # assert x == 1
        """
        self.assertEqual(found("test_x.py", code), [("WT009", 2), ("WT009", 3)])

    def test_snapshot_only(self):
        code = """
            def test_a(snapshot):
                assert render() == snapshot
            def test_b(snapshot):
                snapshot.assert_match(render())
            def test_c(snapshot):
                assert render() == snapshot
                assert len(render()) > 3
        """
        self.assertEqual(found("test_x.py", code), [("WT010", 1), ("WT010", 3)])

    def test_discovery_rules(self):
        code = """
            import unittest
            class Helper:
                def test_looks_like_one(self):
                    pass
            class TestPlain:
                def test_a(self):
                    pass
                def helper(self):
                    pass
            class FooTests(unittest.TestCase):
                def test_b(self):
                    pass
                def setUp(self):
                    pass
            def helper_test():
                pass
            async def test_c():
                pass
        """
        self.assertEqual([line for _, line in found("test_x.py", code)], [6, 11, 17])

    def test_test_count(self):
        text = "def test_a():\n    assert 1 == f()\n\nclass TestB:\n    def test_c(self):\n        assert f()\n"
        _, count, _ = wt.analyse_file("test_x.py", text)
        self.assertEqual(count, 2)

    def test_syntax_error_is_a_warning_not_a_crash(self):
        findings, count, warning = wt.analyse_file("test_x.py", "def test_a(:\n")
        self.assertEqual((findings, count), ([], 0))
        self.assertIn("not parsed", warning)

    def test_python3_nine_syntax_still_parses(self):
        self.assertEqual(found("test_x.py", """
            from __future__ import annotations
            def test_a(x: int | None = None) -> None:
                assert x is None
        """), [])


class IgnoreDirectiveTests(unittest.TestCase):
    def test_ignore_on_same_line_or_line_above(self):
        code = """
            def test_a():  # testdoc: ignore WT001
                run()
            # testdoc: ignore
            def test_b():
                run()
            # testdoc: ignore WT007
            def test_c():
                run()
        """
        self.assertEqual(found("test_x.py", code), [("WT001", 7)])

    def test_ignore_in_js_and_go(self):
        self.assertEqual(found("a.test.js", """
            // testdoc: ignore WT001
            it('boots', () => { boot(); });
        """), [])
        self.assertEqual(found("a_test.go", """
            // testdoc: ignore WT001,WT007
            func TestBoot(t *testing.T) { Boot() }
        """), [])


class JavaScriptTests(unittest.TestCase):
    def test_no_assertion_and_matchers_that_count(self):
        code = """
            describe('x', () => {
              it('a', () => { run(); });
              it('b', () => { expect(run()).toBe(1); });
              it('c', () => { expect(run()).to.equal(1); });
              it('d', () => { assert.equal(run(), 1); });
              it('e', () => request(app).get('/').expect(200));
              it('f', async () => { await expect(run()).rejects.toThrow(); });
              it('g', () => { run().should.equal(1); });
              it('h', () => { verifyTotals(run()); });
              test('i', async function () { expect(await run()).toEqual({ a: 1 }); });
            });
        """
        self.assertEqual(found("a.test.js", code), [("WT001", 2)])

    def test_tautologies(self):
        code = """
            it('a', () => { expect(true).toBe(true); });
            it('b', () => { expect(1).toBe(1); });
            it('c', () => { expect('a').toEqual('a'); });
            it('d', () => { expect(true).toBeTruthy(); });
            it('e', () => { assert.equal(1, 1); });
            it('f', () => { assert(true); });
            it('g', () => { expect(run()).toBe(true); });
            it('h', () => { expect(1).toBe(2); });
        """
        self.assertEqual(rules("a.test.js", code), ["WT002"] * 6)

    def test_only_defined_checks(self):
        code = """
            it('a', () => { expect(run()).toBeDefined(); });
            it('b', () => { expect(run()).not.toBeNull(); });
            it('c', () => { expect(run()).toBeDefined(); expect(run().id).toBe(3); });
            it('d', () => { expect(run()).not.toBe(undefined); });
        """
        self.assertEqual(found("a.test.js", code), [("WT003", 1), ("WT003", 2), ("WT003", 4)])

    def test_expect_without_matcher(self):
        code = """
            it('a', () => {
              expect(run());
            });
            it('b', () => {
              expect(run()).not;
            });
            it('c', () => {
              expect(run())
                .toBe(1);
            });
            it('d', () => {
              expect(run()).toBe(1);
              expect(other());
            });
        """
        self.assertEqual(found("a.test.js", code), [("WT005", 2), ("WT005", 5), ("WT005", 13)])

    def test_empty_bodies(self):
        code = """
            it('a', () => {});
            it('b', function () { });
            it('c', async () => {
              // TODO
            });
            it('d', () => { run(); expect(1).toBe(1 + run()); });
        """
        self.assertEqual(found("a.test.js", code), [("WT004", 1), ("WT004", 2), ("WT004", 3)])

    def test_skips(self):
        code = """
            it.skip('a', () => { expect(run()).toBe(1); });
            xit('b', () => { expect(run()).toBe(1); });
            describe.skip('c', () => {});
            // flaky until the sandbox exists (ticket 9)
            it.skip('d', () => { expect(run()).toBe(1); });
            it.skip('e', () => { expect(run()).toBe(1); }); // see ticket 12
            test.skip(isWindows, 'posix only');
            const s = "it.skip('x', () => {})";
        """
        self.assertEqual(found("a.test.js", code), [("WT006", 1), ("WT006", 2), ("WT006", 3)])

    def test_sleeps(self):
        code = """
            it('a', async () => {
              await new Promise((r) => setTimeout(r, 500));
              expect(run()).toBe(1);
            });
            it('b', async () => { await sleep(100); expect(run()).toBe(1); });
            it('c', () => { cy.wait(500); expect(run()).toBe(1); });
            it('d', async () => { await page.waitForTimeout(100); expect(run()).toBe(1); });
            it('e', async () => { jest.advanceTimersByTime(500); expect(run()).toBe(1); });
        """
        self.assertEqual(found("a.test.js", code), [("WT007", 2), ("WT007", 5), ("WT007", 6), ("WT007", 7)])

    def test_swallowed_errors(self):
        code = """
            it('a', () => {
              try { run(); } catch (e) { console.log(e); }
              expect(1).toBe(1 + 0);
            });
            it('b', () => {
              try { run(); expect.fail('no'); } catch (e) { expect(e.message).toMatch(/bad/); }
            });
            it('c', async () => {
              await run().catch(() => {});
            });
            it('d', () => {
              try { run(); } catch (e) { throw new Error('wrapped'); }
            });
            it('e', async () => {
              await run().catch(() => {});
              expect(handler).toHaveBeenCalled();
            });
        """
        self.assertEqual(found("a.test.js", code), [("WT001", 8), ("WT008", 2), ("WT008", 9)])

    def test_commented_out_assertions(self):
        code = """
            it('a', () => {
              // expect(run()).toBe(1);
              /* expect(run()).toBe(2); */
              // this expects the total
              expect(run()).toBeGreaterThan(0);
            });
        """
        self.assertEqual(found("a.test.js", code), [("WT009", 2), ("WT009", 3)])

    def test_snapshot_only(self):
        code = """
            it('a', () => { expect(render()).toMatchSnapshot(); });
            it('b', () => { expect(render()).toMatchInlineSnapshot(`"x"`); });
            it('c', () => { expect(render()).toMatchSnapshot(); expect(render()).toContain('x'); });
        """
        self.assertEqual(found("a.test.js", code), [("WT010", 1), ("WT010", 2)])

    def test_each_expression_bodies_and_typescript(self):
        code = """
            test.each([[1, 2], [2, 3]])('adds %i', (a, b) => { expect(a + 1).toBe(b); });
            it('x', () => expect(1 + 1).toBe(2));
            it('y', () => foo());
            it('z', async (): Promise<void> => { expect(await run()).toBe(1); });
        """
        self.assertEqual(found("a.test.ts", code), [("WT001", 3)])

    def test_braces_and_quotes_inside_strings_and_comments(self):
        code = """
            it('a } b', () => {
              const s = '}{"';  // a brace } in a comment
              /* { */
              expect(f(s)).toBe(`}`);
            });
            it('b', () => { run(); });
        """
        self.assertEqual(found("a.test.js", code), [("WT001", 6)])

    def test_tests_inside_a_tests_folder_are_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp) / "__tests__" / "cart.js", "it('x', () => { run(); });\n")
            write(Path(tmp) / "src" / "cart.js", "it('x', () => { run(); });\n")
            files = wt.collect_files([tmp])
            self.assertEqual([Path(f).name for f in files], ["cart.js"])
            self.assertIn("__tests__", files[0])


class GoTests(unittest.TestCase):
    def test_no_assertion_and_assertions_that_count(self):
        code = """
            package p
            func TestA(t *testing.T) {
                Run()
            }
            func TestB(t *testing.T) {
                if got := Run(); got != 1 {
                    t.Errorf("got %d", got)
                }
            }
            func TestC(t *testing.T) {
                assert.Equal(t, 1, Run())
            }
            func TestD(t *testing.T) {
                checkTotal(t, Run())
            }
            func TestE(t *testing.T) {
                for _, tc := range cases {
                    t.Run(tc.name, func(st *testing.T) {
                        if Run(tc.in) != tc.want {
                            st.Fatalf("bad %v", tc)
                        }
                    })
                }
            }
            func TestF(t *testing.T) {
                msg := err.Error()
                _ = msg
            }
            func TestG(t *testing.T) {
                RegisterFailHandler(Fail)
                RunSpecs(t, "Suite")
            }
        """
        self.assertEqual(found("a_test.go", code), [("WT001", 2), ("WT001", 25)])

    def test_tautology_notnil_empty(self):
        code = """
            package p
            func TestA(t *testing.T) {
                assert.True(t, true)
            }
            func TestB(t *testing.T) {
                v := Run()
                assert.NotNil(t, v)
            }
            func TestC(t *testing.T) {
            }
            func TestD(t *testing.T) {
                assert.Equal(t, 1, 1)
            }
            func TestE(t *testing.T) {
                v := Run()
                assert.NotNil(t, v)
                assert.Equal(t, 3, v.ID)
            }
        """
        self.assertEqual(found("a_test.go", code), [("WT002", 3), ("WT002", 12), ("WT003", 5), ("WT004", 9)])

    def test_skip_sleep_recover_and_comments(self):
        code = """
            package p
            func TestA(t *testing.T) {
                t.Skip()
            }
            func TestB(t *testing.T) {
                t.Skip("needs docker, ticket 3")
                assert.True(t, Run())
            }
            func TestC(t *testing.T) {
                // sandbox is down, ticket 4
                t.Skip()
                assert.True(t, Run())
            }
            func TestD(t *testing.T) {
                time.Sleep(time.Second)
                assert.True(t, Run())
            }
            func TestE(t *testing.T) {
                defer func() {
                    recover()
                }()
                Run()
                assert.True(t, Ok())
            }
            func TestF(t *testing.T) {
                // assert.Equal(t, 1, Run())
                assert.True(t, Ok())
            }
        """
        self.assertEqual(found("a_test.go", code), [
            ("WT001", 2), ("WT006", 3), ("WT007", 15), ("WT008", 20), ("WT009", 26)])

    def test_only_real_test_functions_are_scanned(self):
        code = """
            package p
            func TestMain(m *testing.M) {
                os.Exit(m.Run())
            }
            func Testfoo(t *testing.T) {
            }
            func helper(t *testing.T) {
            }
            func Test_Under(t *testing.T) {
            }
        """
        self.assertEqual(found("a_test.go", code), [("WT004", 9)])


class JavaTests(unittest.TestCase):
    def test_no_assertion_and_assertions_that_count(self):
        code = """
            class T {
                @Test void a() { run(); }
                @Test void b() { assertEquals(1, run()); }
                @Test void c() { assertThrows(Boom.class, () -> run()); }
                @Test void d() { verify(mock).call(); }
                @Test(expected = Boom.class) void e() { run(); }
                @Test void f() throws Exception { assertThat(run()).isEqualTo(1); }
                @Test void g() { mockMvc.perform(get("/")).andExpect(status().isOk()); }
                @ParameterizedTest @ValueSource(ints = {1, 2}) void h(int n) { assertEquals(n, run(n)); }
                void helper() { run(); }
            }
        """
        self.assertEqual(found("OrderTest.java", code), [("WT001", 2)])

    def test_tautology_notnull_empty(self):
        code = """
            class T {
                @Test void a() { assertTrue(true); }
                @Test void b() { assertEquals(1, 1); }
                @Test void c() { assertNotNull(run()); }
                @Test void d() { }
                @Test void e() { assertNotNull(run()); assertEquals(3, run().id()); }
                @Test void f() { assertThat(true).isTrue(); }
            }
        """
        self.assertEqual(found("OrderTest.java", code), [("WT002", 2), ("WT002", 3), ("WT002", 7), ("WT003", 4),
                                                         ("WT004", 5)])

    def test_disabled(self):
        code = """
            class T {
                @Disabled
                @Test void a() { assertEquals(1, run()); }
                @Disabled("flaky, ticket 5")
                @Test void b() { assertEquals(1, run()); }
                // waiting on the vendor sandbox
                @Ignore
                @Test void c() { assertEquals(1, run()); }
                @Disabled("")
                @Test void d() { assertEquals(1, run()); }
            }
        """
        self.assertEqual(found("OrderTest.java", code), [("WT006", 2), ("WT006", 9)])

    def test_sleep_catch_and_comments(self):
        code = """
            class T {
                @Test void a() throws Exception {
                    Thread.sleep(100);
                    assertEquals(1, run());
                }
                @Test void b() {
                    try { run(); } catch (Exception e) { }
                    assertEquals(1, 1 + 0);
                }
                @Test void c() {
                    try { run(); fail("no"); } catch (Exception e) { assertEquals("bad", e.getMessage()); }
                }
                @Test void d() {
                    try { run(); } catch (IOException e) { }
                    assertEquals(1, 1 + 0);
                }
                @Test void e() {
                    // assertEquals(1, run());
                    assertTrue(run() > 0);
                }
            }
        """
        self.assertEqual(found("OrderTest.java", code), [("WT007", 3), ("WT008", 7), ("WT009", 18)])

    def test_file_naming(self):
        self.assertTrue(wt.is_test_file("OrderTest.java", set()))
        self.assertTrue(wt.is_test_file("OrderTests.java", set()))
        self.assertTrue(wt.is_test_file("TestOrder.java", set()))
        self.assertTrue(wt.is_test_file("OrderIT.java", set()))
        self.assertFalse(wt.is_test_file("Order.java", set()))
        self.assertTrue(wt.is_test_file("test_a.py", set()))
        self.assertTrue(wt.is_test_file("a_test.py", set()))
        self.assertFalse(wt.is_test_file("conftest.py", set()))
        self.assertTrue(wt.is_test_file("a.spec.tsx", set()))
        self.assertFalse(wt.is_test_file("a.tsx", set()))
        self.assertTrue(wt.is_test_file("a_test.go", set()))
        self.assertFalse(wt.is_test_file("a.go", set()))


class MaskingTests(unittest.TestCase):
    def test_mask_blanks_comments_and_strings_but_keeps_offsets(self):
        text = "a('x // y'); // tail\n/* b\nc */ d(\"q'r\");\n"
        nc, mk = wt.mask_source(text, "js")
        self.assertEqual(len(nc), len(text))
        self.assertEqual(len(mk), len(text))
        self.assertEqual(nc.count("\n"), text.count("\n"))
        self.assertIn("'x // y'", nc)
        self.assertNotIn("tail", nc)
        self.assertNotIn("x // y", mk)
        self.assertNotIn("q'r", mk)

    def test_go_raw_strings_and_java_text_blocks(self):
        nc, mk = wt.mask_source("x := `a\\` + y // c\n", "go")
        self.assertNotIn("// c", nc)
        _, mk = wt.mask_source('String s = """\n  { not a brace }\n  """; int x;', "java")
        self.assertNotIn("{", mk)

    def test_match_close(self):
        masked = "f(a(b), c) { }"
        self.assertEqual(wt.match_close(masked, 1), 9)
        self.assertEqual(wt.match_close(masked, 11), 13)
        self.assertEqual(wt.match_close("f(a", 1), -1)


class ScanAndCliTests(unittest.TestCase):
    def make_tree(self, tmp):
        root = Path(tmp)
        write(root / "tests" / "test_a.py", "def test_a():\n    run()\n\ndef test_b():\n    time.sleep(1)\n    assert f()\n")
        write(root / "tests" / "b.test.js", "it('x', () => { expect(true).toBe(true); });\n")
        write(root / "node_modules" / "dep" / "x.test.js", "it('x', () => {});\n")
        write(root / "tests" / "helper.py", "def test_not_a_test_file():\n    pass\n")
        return str(root / "tests"), str(root)

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = wt.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_scan_counts_sorting_and_skipped_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir, root = self.make_tree(tmp)
            report = wt.scan([root])
            s = report["summary"]
            self.assertEqual((s["files"], s["tests"], s["findings"]), (2, 3, 3))
            self.assertEqual(s["by_severity"], {"high": 2, "medium": 0, "low": 1})
            self.assertEqual(s["by_rule"], {"WT001": 1, "WT002": 1, "WT007": 1})
            severities = [f["severity"] for f in report["findings"]]
            self.assertEqual(severities, ["high", "high", "low"])
            self.assertTrue(all("node_modules" not in f["file"] for f in report["findings"]))

    def test_ignore_and_min_severity(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir, _ = self.make_tree(tmp)
            self.assertEqual(wt.scan([tests_dir], ignore={"WT007"})["summary"]["findings"], 2)
            self.assertEqual(wt.scan([tests_dir], min_severity="high")["summary"]["findings"], 2)
            self.assertEqual(wt.scan([tests_dir], ignore={"WT001", "WT002", "WT007"})["summary"]["findings"], 0)

    def test_explicit_file_is_scanned_even_if_not_named_like_a_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(Path(tmp) / "checks.py", "def test_x():\n    pass\n")
            self.assertEqual(wt.scan([str(path)])["summary"]["findings"], 1)

    def test_cli_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir, _ = self.make_tree(tmp)
            code, out, err = self.run_main([tests_dir])
            self.assertEqual((code, err), (0, ""))
            for needle in ("# Weak test scan", "## By rule", "## Findings", "WT001", "WT002", "WT007",
                           "Scanned 2 test file(s) and 3 tests. 3 finding(s): 2 high, 0 medium, 1 low."):
                self.assertIn(needle, out)
            code, out, _ = self.run_main([tests_dir, "--json"])
            data = json.loads(out)
            self.assertEqual(data["summary"]["findings"], 3)
            self.assertEqual([f["rule"] for f in data["findings"]], ["WT002", "WT001", "WT007"])  # severity, then file, then line
            self.assertTrue({"rule", "severity", "file", "line", "test", "message"} <= set(data["findings"][0]))

    def test_fail_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir, _ = self.make_tree(tmp)
            self.assertEqual(self.run_main([tests_dir, "--fail-on", "high"])[0], 1)
            self.assertEqual(self.run_main([tests_dir, "--fail-on", "low"])[0], 1)
            self.assertEqual(self.run_main([tests_dir, "--fail-on", "high", "--ignore", "WT001,WT002"])[0], 0)
            self.assertEqual(self.run_main([tests_dir, "--fail-on", "medium", "--ignore", "WT001,WT002"])[0], 0)
            self.assertEqual(self.run_main([tests_dir])[0], 0)

    def test_clean_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(Path(tmp) / "test_ok.py", "def test_ok():\n    assert 1 + 1 == 2\n")
            code, out, _ = self.run_main([str(path), "--fail-on", "low"])
            self.assertEqual(code, 0)
            self.assertIn("No weak tests found", out)

    def test_bad_arguments_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = self.run_main([tmp])
            self.assertEqual((code, out), (2, ""))
            self.assertIn("no test files", err)
            tests_dir, _ = self.make_tree(tmp)
            code, _, err = self.run_main([tests_dir, "--ignore", "WT999"])
            self.assertEqual(code, 2)
            self.assertIn("WT999", err)

    def test_out_file_uses_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir, _ = self.make_tree(tmp)
            target = Path(tmp) / "report.md"
            code, out, _ = self.run_main([tests_dir, "-o", str(target)])
            self.assertEqual((code, out), (0, ""))
            self.assertNotIn(b"\r\n", target.read_bytes())

    def test_out_creates_missing_folders_and_reports_unwritable_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir, _ = self.make_tree(tmp)
            nested = Path(tmp) / "testdoc" / "weak.md"
            self.assertEqual(self.run_main([tests_dir, "-o", str(nested)])[0], 0)
            self.assertTrue(nested.exists())
            blocker = write(Path(tmp) / "afile", "x")
            code, _, err = self.run_main([tests_dir, "-o", str(blocker / "r.md")])
            self.assertEqual(code, 2)
            self.assertIn("cannot write", err)

    def test_crlf_sources_give_the_same_lines(self):
        lf = "def test_a():\n    run()\n"
        crlf = lf.replace("\n", "\r\n")
        self.assertEqual(wt.analyse_file("test_x.py", lf)[0][0]["line"], wt.analyse_file("test_x.py", crlf)[0][0]["line"])
        js = "it('a', () => {\r\n  run();\r\n});\r\n"
        self.assertEqual(wt.analyse_file("a.test.js", js)[0][0]["line"], 1)

    def test_unreadable_binary_file_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test_bin.py"
            path.write_bytes(b"\xff\xfe\x00def test_x():\n    pass\n")
            report = wt.scan([str(path)])
            self.assertTrue(report["warnings"] or report["summary"]["findings"] >= 0)

    def test_every_rule_has_a_severity_and_title(self):
        self.assertEqual(sorted(wt.RULES), [f"WT{n:03d}" for n in range(1, 11)])
        for rule, (severity, title) in wt.RULES.items():
            self.assertIn(severity, ("low", "medium", "high"))
            self.assertTrue(title)

    def test_runs_as_a_script(self):
        proc = subprocess.run([sys.executable, "-I", str(SCRIPT), str(ROOT / "examples" / "weak"), "--fail-on", "high"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("# Weak test scan", proc.stdout)


class ExampleCoverageTests(unittest.TestCase):
    """The shipped weak examples must exercise every rule in every language."""

    @classmethod
    def setUpClass(cls):
        cls.report = wt.scan([str(ROOT / "examples" / "weak")])

    def test_every_rule_appears(self):
        self.assertEqual(sorted(self.report["summary"]["by_rule"]), sorted(wt.RULES))

    def test_every_file_has_findings_and_good_tests_are_not_flagged(self):
        files = {Path(f["file"]).name for f in self.report["findings"]}
        self.assertEqual(files, {"test_orders.py", "cart.test.js", "pricing_test.go", "OrderServiceTest.java"})
        flagged = {f["test"] for f in self.report["findings"]}
        for good in ("TestOrders.test_total_includes_tax", "TestOrders.test_cancel_unknown_order_raises",
                     "test_discount_half_cent", "sums two items", "TestTotal", "totalIncludesTax"):
            self.assertNotIn(good, flagged)


if __name__ == "__main__":
    unittest.main()
