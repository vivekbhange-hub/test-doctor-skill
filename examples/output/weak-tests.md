# Weak test scan

Scanned 4 test file(s) and 43 tests. 40 finding(s): 21 high, 13 medium, 6 low.

## By rule

| Rule | Severity | Count | Meaning |
|---|---|---:|---|
| WT001 | high | 8 | No assertion |
| WT002 | high | 4 | Assertion that cannot fail |
| WT003 | medium | 4 | Only a not-None / defined check |
| WT004 | high | 4 | Empty test body |
| WT005 | high | 1 | expect() with no matcher |
| WT006 | medium | 5 | Skipped or xfail without a reason |
| WT007 | low | 4 | Sleep in a test |
| WT008 | high | 4 | Broad exception swallowed |
| WT009 | medium | 4 | Commented-out assertion |
| WT010 | low | 2 | Snapshot is the only assertion |

## Findings

| Location | Rule | Severity | Test | Problem |
|---|---|---|---|---|
| `examples/weak/OrderServiceTest.java:14` | WT001 | high | `createsOrder` | no assertion; this test only fails if the code under test raises |
| `examples/weak/OrderServiceTest.java:20` | WT002 | high | `alwaysTrue` | assertion can never fail: assertTrue(true) |
| `examples/weak/OrderServiceTest.java:29` | WT004 | high | `cancelsLater` | empty test body |
| `examples/weak/OrderServiceTest.java:46` | WT001 | high | `cancelUnknown` | no assertion; this test only fails if the code under test raises |
| `examples/weak/OrderServiceTest.java:49` | WT008 | high | `cancelUnknown` | catches a broad exception and carries on, so failures are hidden |
| `examples/weak/cart.test.js:5` | WT001 | high | `adds an item` | no assertion; this test only fails if the code under test raises |
| `examples/weak/cart.test.js:11` | WT002 | high | `is always true` | assertion can never fail: expect(true).toBe(true) |
| `examples/weak/cart.test.js:21` | WT005 | high | `has a total` | expect(...) has no matcher, so nothing is asserted |
| `examples/weak/cart.test.js:24` | WT004 | high | `removes an item` | empty test body |
| `examples/weak/cart.test.js:42` | WT001 | high | `rejects a negative price` | no assertion; this test only fails if the code under test raises |
| `examples/weak/cart.test.js:45` | WT008 | high | `rejects a negative price` | catch block swallows the error, so failures are hidden |
| `examples/weak/pricing_test.go:12` | WT001 | high | `TestApplyTax` | no assertion; this test only fails if the code under test raises |
| `examples/weak/pricing_test.go:17` | WT002 | high | `TestAlwaysTrue` | assertion can never fail: assert.True(t, true) |
| `examples/weak/pricing_test.go:25` | WT004 | high | `TestRoundingLater` | empty test body |
| `examples/weak/pricing_test.go:28` | WT001 | high | `TestVatRefund` | no assertion; this test only fails if the code under test raises |
| `examples/weak/pricing_test.go:40` | WT001 | high | `TestParsePrice` | no assertion; this test only fails if the code under test raises |
| `examples/weak/pricing_test.go:42` | WT008 | high | `TestParsePrice` | recover() result is discarded, so a panic is hidden |
| `examples/weak/test_orders.py:12` | WT001 | high | `TestOrders.test_create_order` | no assertion; this test only fails if the code under test raises |
| `examples/weak/test_orders.py:16` | WT002 | high | `TestOrders.test_cancel_order_returns` | assertion can never fail: self.assertTrue(True) |
| `examples/weak/test_orders.py:22` | WT004 | high | `TestOrders.test_apply_discount_later` | empty test body |
| `examples/weak/test_orders.py:38` | WT008 | high | `TestOrders.test_cancel_unknown_order` | catches a broad exception and carries on, so failures are hidden |
| `examples/weak/OrderServiceTest.java:24` | WT003 | medium | `loadsOrder` | the only assertion checks that a value exists; it does not say what it is |
| `examples/weak/OrderServiceTest.java:32` | WT006 | medium | `(disabled)` | @Disabled/@Ignore without a reason |
| `examples/weak/OrderServiceTest.java:56` | WT009 | medium | `rounds` | commented-out assertion: the test checks less than it appears to |
| `examples/weak/cart.test.js:14` | WT003 | medium | `creates a cart` | the only assertion checks that a value exists; it does not say what it is |
| `examples/weak/cart.test.js:26` | WT006 | medium | `(skipped)` | skipped without a reason (add a comment saying why) |
| `examples/weak/cart.test.js:53` | WT009 | medium | `rounds the total` | commented-out assertion: the test checks less than it appears to |
| `examples/weak/pricing_test.go:20` | WT003 | medium | `TestLookupExists` | the only assertion checks that a value exists; it does not say what it is |
| `examples/weak/pricing_test.go:29` | WT006 | medium | `TestVatRefund` | skipped without a reason |
| `examples/weak/pricing_test.go:48` | WT009 | medium | `TestRoundHalfUp` | commented-out assertion: the test checks less than it appears to |
| `examples/weak/test_orders.py:18` | WT003 | medium | `TestOrders.test_load_order` | the only assertion checks that a value exists; it does not say what it is |
| `examples/weak/test_orders.py:25` | WT006 | medium | `TestOrders.test_summary_format` | skipped or xfail without a reason |
| `examples/weak/test_orders.py:42` | WT009 | medium | `TestOrders.test_discount_rounding` | commented-out assertion: the test checks less than it appears to |
| `examples/weak/test_orders.py:58` | WT006 | medium | `test_bulk_import` | skipped or xfail without a reason |
| `examples/weak/OrderServiceTest.java:41` | WT007 | low | `ships` | sleep in a test: slow, and a timing guess that goes flaky |
| `examples/weak/cart.test.js:38` | WT007 | low | `empties after checkout` | sleep in a test: slow, and a timing guess that goes flaky |
| `examples/weak/cart.test.js:57` | WT010 | low | `renders the summary` | the only assertion is a snapshot; a snapshot approved without review can lock in a bug |
| `examples/weak/pricing_test.go:34` | WT007 | low | `TestRateCache` | sleep in a test: slow, and a timing guess that goes flaky |
| `examples/weak/test_orders.py:31` | WT007 | low | `TestOrders.test_order_ships` | sleep in a test: slow, and a timing guess that goes flaky |
| `examples/weak/test_orders.py:54` | WT010 | low | `test_summary_snapshot` | the only assertion is a snapshot; a snapshot approved without review can lock in a bug |
