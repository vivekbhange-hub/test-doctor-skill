# JUnit report

5 run(s), 24 distinct tests, 115 executions. 6 flaky, 2 consistently failing.

## Runs

| Run | Tests | Failed | Skipped | Time (s) |
|---|---:|---:|---:|---:|
| run1.xml | 24 | 3 | 1 | 14.96 |
| run2.xml | 24 | 4 | 1 | 20.16 |
| run3.xml | 24 | 6 | 1 | 14.51 |
| run4.xml | 24 | 5 | 1 | 16.16 |
| run5.xml | 24 | 3 | 1 | 19.47 |

## Flaky tests (6)

Flake rate is failing runs divided by runs executed. Likely cause is a keyword match on the failure text, so treat it as a place to start reading.

| Test | Pass | Fail | Flake rate | Failed in | Likely cause |
|---|---:|---:|---:|---|---|
| `tests.test_inventory.TestInventory::test_reserve_stock` | 2 | 3 | 60% | run1.xml, run3.xml, run4.xml | ordering/shared state |
| `tests.test_api.TestPricingApi::test_fetch_exchange_rate` | 3 | 2 | 40% | run2.xml, run3.xml | network |
| `tests.test_checkout.TestCheckout::test_order_confirmation_email` | 3 | 2 | 40% | run2.xml, run5.xml | timing |
| `tests.test_inventory.TestInventory::test_release_stock` | 3 | 2 | 40% | run3.xml, run4.xml | ordering/shared state |
| `tests.test_recommendations.TestRecommender::test_top_pick_is_stable` | 4 | 1 | 20% | run3.xml | unknown |
| `tests.test_reports.TestDailyReport::test_report_covers_today` | 4 | 1 | 20% | run4.xml | time-zone/date |

## Consistently failing (2)

| Test | Runs | Sample message |
|---|---:|---|
| `tests.test_cart.TestCart::test_apply_coupon_expired` | 5 | AssertionError: assert Decimal('9.99') == Decimal('10.00') |
| `tests.test_shipping.TestShipping::test_zone_lookup` | 5 | KeyError: 'ZZ' |

## Slowest tests (mean of 5 run(s), 17.05s total)

| Test | Mean (s) | Max (s) | % of total |
|---|---:|---:|---:|
| `tests.test_checkout.TestCheckout::test_full_checkout_flow` | 8.53 | 9.07 | 50.1% |
| `tests.test_reports.TestDailyReport::test_report_covers_today` | 3.15 | 3.35 | 18.5% |
| `tests.test_checkout.TestCheckout::test_order_confirmation_email` | 2.27 | 5.06 | 13.3% |
| `tests.test_reports.TestDailyReport::test_weekly_summary` | 1.22 | 1.30 | 7.2% |
| `tests.test_reports.TestDailyReport::test_csv_export` | 0.41 | 0.43 | 2.4% |
| `tests.test_api.TestPricingApi::test_fetch_exchange_rate` | 0.33 | 0.35 | 1.9% |
| `tests.test_api.TestPricingApi::test_price_list_pagination` | 0.30 | 0.32 | 1.8% |
| `tests.test_checkout.TestCheckout::test_payment_declined` | 0.21 | 0.23 | 1.3% |
| `tests.test_api.TestPricingApi::test_unknown_currency` | 0.10 | 0.11 | 0.6% |
| `tests.test_recommendations.TestRecommender::test_top_pick_is_stable` | 0.07 | 0.08 | 0.4% |

## Slowest files and classes

| File or class | Tests | Mean (s) | % of total |
|---|---:|---:|---:|
| `tests/test_checkout.py` | 4 | 11.06 | 64.8% |
| `tests/test_reports.py` | 3 | 4.78 | 28.0% |
| `tests/test_api.py` | 3 | 0.73 | 4.3% |
| `tests/test_inventory.py` | 3 | 0.16 | 1.0% |
| `tests/test_cart.py` | 5 | 0.13 | 0.8% |
| `tests/test_recommendations.py` | 2 | 0.13 | 0.8% |
| `tests/test_shipping.py` | 3 | 0.06 | 0.4% |

## Failure clusters (7)

Numbers, ids, addresses, paths, URLs and timestamps are replaced before grouping.

| # | Count | Tests | Pattern | Sample |
|---:|---:|---:|---|---|
| 1 | 5 | 1 | `AssertionError: assert Decimal('N') == Decimal('N')` | AssertionError: assert Decimal('9.99') == Decimal('10.00') |
| 2 | 5 | 1 | `KeyError: 'ZZ'` | KeyError: 'ZZ' |
| 3 | 5 | 2 | `sqlite3.IntegrityError: UNIQUE constraint failed: reservations.sku (row N)` | sqlite3.IntegrityError: UNIQUE constraint failed: reservations.sku (row 17) |
| 4 | 2 | 1 | `TimeoutError: timed out after Ns waiting for mailbox to receive N message` | TimeoutError: timed out after 5.0s waiting for mailbox to receive 1 message |
| 5 | 2 | 1 | `requests.exceptions.ConnectionError: HTTPSConnectionPool(host='rates.shop.example', port=N): Max ...` | requests.exceptions.ConnectionError: HTTPSConnectionPool(host='rates.shop.example', port=443): Ma... |
| 6 | 1 | 1 | `AssertionError: 'socks' != 'hat'` | AssertionError: 'socks' != 'hat' |
| 7 | 1 | 1 | `AssertionError: datetime.date(N, N, N) != datetime.date(N, N, N)` | AssertionError: datetime.date(2026, 11, 13) != datetime.date(2026, 11, 12) |

Tests per cluster:

1. tests.test_cart.TestCart::test_apply_coupon_expired
2. tests.test_shipping.TestShipping::test_zone_lookup
3. tests.test_inventory.TestInventory::test_release_stock, tests.test_inventory.TestInventory::test_reserve_stock
4. tests.test_checkout.TestCheckout::test_order_confirmation_email
5. tests.test_api.TestPricingApi::test_fetch_exchange_rate
6. tests.test_recommendations.TestRecommender::test_top_pick_is_stable
7. tests.test_reports.TestDailyReport::test_report_covers_today
