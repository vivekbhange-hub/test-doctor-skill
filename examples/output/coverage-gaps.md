# Where to write tests first

Source: `examples/coverage/lcov.info` (lcov). Scope: all files.
Lines: 372/522 covered (71.3%). Branches: 33/41 covered (80.5%). Files with gaps: 6 of 7.

## Ranked files

Priority is uncovered lines multiplied by the share of the file that is uncovered.

| # | File | Line coverage | Uncovered lines | Branches missed | Functions never called | Priority |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `src/shop/checkout.py` | 54.9% | 69 | 4 | 1 | 31.1 |
| 2 | `src/shop/reports.py` | 67.6% | 33 | 1 | 1 | 10.7 |
| 3 | `src/shop/shipping.py` | 64.7% | 18 | 1 | 1 | 6.4 |
| 4 | `src/shop/inventory.py` | 68.3% | 19 | 1 | 1 | 6.0 |
| 5 | `src/shop/cart.py` | 88.8% | 9 | 1 | 0 | 1.0 |
| 6 | `src/shop/recommend.py` | 95.2% | 2 | 0 | 0 | 0.1 |

## Details

### 1. `src/shop/checkout.py` (54.9%, 69 uncovered lines)

- Uncovered lines: 41-47, 78-90, 92-139, 160-171
- Branches never taken: 45 (2/2 untaken), 76 (2/3 untaken)
- Functions never called: `refund` (line 92)
- Largest untested block: lines 92-139 (42 uncovered, inside `refund`)

### 2. `src/shop/reports.py` (67.6%, 33 uncovered lines)

- Uncovered lines: 56-60, 84-88, 94-120
- Branches never taken: 50 (1/2 untaken)
- Functions never called: `export_pdf` (line 94)
- Largest untested block: lines 94-120 (24 uncovered, inside `export_pdf`)

### 3. `src/shop/shipping.py` (64.7%, 18 uncovered lines)

- Uncovered lines: 25-30, 46-60
- Branches never taken: 20 (1/2 untaken)
- Functions never called: `customs_surcharge` (line 46)
- Largest untested block: lines 46-60 (13 uncovered, inside `customs_surcharge`)

### 4. `src/shop/inventory.py` (68.3%, 19 uncovered lines)

- Uncovered lines: 30-31, 52-70
- Branches never taken: 15 (1/2 untaken)
- Functions never called: `restock_from_supplier` (line 52)
- Largest untested block: lines 52-70 (17 uncovered, inside `restock_from_supplier`)

### 5. `src/shop/cart.py` (88.8%, 9 uncovered lines)

- Uncovered lines: 70-79
- Branches never taken: 68 (1/2 untaken)
- Largest untested block: lines 70-79 (9 uncovered, inside `apply_coupon`)

### 6. `src/shop/recommend.py` (95.2%, 2 uncovered lines)

- Uncovered lines: 44-45
- Largest untested block: lines 44-45 (2 uncovered, inside `cold_start`)
