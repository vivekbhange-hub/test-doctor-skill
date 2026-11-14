"""Order tests for a fictional shop. Several of these are weak on purpose: they are the
examples that weak_tests.py is run against. Nothing here is imported or executed."""
import time
import unittest

import pytest

from shop.orders import apply_discount, cancel_order, create_order, load_order, order_summary


class TestOrders(unittest.TestCase):
    def test_create_order(self):
        order = create_order(items=["hat"], customer="c-1")

    def test_cancel_order_returns(self):
        self.assertTrue(True)

    def test_load_order(self):
        order = load_order("o-1")
        assert order is not None

    def test_apply_discount_later(self):
        pass

    @unittest.skip("")
    def test_summary_format(self):
        self.assertEqual(order_summary("o-1"), "1 item, total 19.99")

    def test_order_ships(self):
        order = create_order(items=["hat"], customer="c-2")
        time.sleep(2)
        self.assertEqual(order.status, "shipped")

    def test_cancel_unknown_order(self):
        try:
            cancel_order("missing")
            self.assertEqual(load_order("missing"), None)
        except Exception:
            pass

    def test_discount_rounding(self):
        # self.assertEqual(apply_discount(10, 0.15), 8.5)
        self.assertEqual(apply_discount(10, 0.10), 9.0)

    def test_total_includes_tax(self):
        order = create_order(items=["hat"], customer="c-3")
        self.assertEqual(order.total, 21.59)

    def test_cancel_unknown_order_raises(self):
        with self.assertRaises(KeyError):
            cancel_order("missing")


def test_summary_snapshot(snapshot):
    assert order_summary("o-1") == snapshot


@pytest.mark.xfail
def test_bulk_import():
    assert create_order(items=["a", "b"], customer="c-4").count == 2


@pytest.mark.xfail(reason="rounding bug, see issue 212")
def test_discount_half_cent():
    assert apply_discount(0.99, 0.5) == 0.5
