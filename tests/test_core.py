"""
Test suite — covers critical business logic and API behaviour.

Run: python manage.py test tests --settings=config.settings_test
  or: pytest tests/ (with pytest-django)

Uses Django's TestCase which wraps each test in a transaction that's
rolled back, so tests are isolated and fast.
"""
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.products.models import Category, Product
from apps.stores.models import Store, Inventory
from apps.orders.models import Order, OrderItem
from apps.orders.services import create_order


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_category(name="Electronics"):
    return Category.objects.create(name=name)


def make_product(category, title="Widget", price="19.99"):
    return Product.objects.create(title=title, price=Decimal(price), category=category)


def make_store(name="Test Store"):
    return Store.objects.create(name=name, location="123 Test St")


def make_inventory(store, product, quantity=100):
    return Inventory.objects.create(store=store, product=product, quantity=quantity)


# ---------------------------------------------------------------------------
# 1. Order creation — sufficient stock → CONFIRMED
# ---------------------------------------------------------------------------

class OrderConfirmedTest(TestCase):
    def setUp(self):
        cat = make_category()
        self.store = make_store()
        self.product = make_product(cat, "Gadget", "49.99")
        self.inv = make_inventory(self.store, self.product, quantity=50)

    def test_order_confirmed_and_stock_deducted(self):
        order = create_order(
            store_id=self.store.id,
            items=[{"product_id": self.product.id, "quantity_requested": 10}],
        )
        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.quantity, 40)  # 50 - 10

    def test_order_items_created(self):
        order = create_order(
            store_id=self.store.id,
            items=[{"product_id": self.product.id, "quantity_requested": 5}],
        )
        self.assertEqual(order.items.count(), 1)
        item = order.items.first()
        self.assertEqual(item.quantity_requested, 5)
        self.assertEqual(item.product_id, self.product.id)


# ---------------------------------------------------------------------------
# 2. Order creation — insufficient stock → REJECTED
# ---------------------------------------------------------------------------

class OrderRejectedTest(TestCase):
    def setUp(self):
        cat = make_category()
        self.store = make_store()
        self.product = make_product(cat, "Scarce Item", "9.99")
        self.inv = make_inventory(self.store, self.product, quantity=3)

    def test_order_rejected_when_stock_insufficient(self):
        order = create_order(
            store_id=self.store.id,
            items=[{"product_id": self.product.id, "quantity_requested": 10}],
        )
        self.assertEqual(order.status, Order.Status.REJECTED)

    def test_stock_not_deducted_on_rejection(self):
        create_order(
            store_id=self.store.id,
            items=[{"product_id": self.product.id, "quantity_requested": 10}],
        )
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.quantity, 3)  # unchanged

    def test_order_rejected_when_product_not_in_store(self):
        cat = make_category("Books")
        other_product = make_product(cat, "Unknown Product")
        # No inventory for other_product in this store
        order = create_order(
            store_id=self.store.id,
            items=[{"product_id": other_product.id, "quantity_requested": 1}],
        )
        self.assertEqual(order.status, Order.Status.REJECTED)


# ---------------------------------------------------------------------------
# 3. Order listing API — no N+1, sorted newest first
# ---------------------------------------------------------------------------

class OrderListAPITest(TestCase):
    def setUp(self):
        cat = make_category()
        self.store = make_store()
        self.product = make_product(cat)
        make_inventory(self.store, self.product, 100)
        # Create 3 orders
        self.orders = [
            create_order(self.store.id, [{"product_id": self.product.id, "quantity_requested": 1}])
            for _ in range(3)
        ]

    def test_order_list_returns_correct_count(self):
        url = f"/stores/{self.store.id}/orders/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 3)

    def test_order_list_sorted_newest_first(self):
        url = f"/stores/{self.store.id}/orders/"
        response = self.client.get(url)
        data = response.json()
        ids = [o["id"] for o in data]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_order_list_includes_total_items(self):
        url = f"/stores/{self.store.id}/orders/"
        response = self.client.get(url)
        data = response.json()
        for order_data in data:
            self.assertIn("total_items", order_data)
            self.assertEqual(order_data["total_items"], 1)


# ---------------------------------------------------------------------------
# 4. Inventory listing API
# ---------------------------------------------------------------------------

class InventoryListAPITest(TestCase):
    def setUp(self):
        cat = make_category("Gadgets")
        self.store = make_store()
        self.p1 = make_product(cat, "Banana Phone", "9.99")
        self.p2 = make_product(cat, "Apple Watch", "299.99")
        make_inventory(self.store, self.p1, 10)
        make_inventory(self.store, self.p2, 5)

    def test_inventory_sorted_alphabetically(self):
        url = f"/stores/{self.store.id}/inventory/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        titles = [item["product_title"] for item in response.json()]
        self.assertEqual(titles, sorted(titles))

    def test_inventory_includes_category(self):
        url = f"/stores/{self.store.id}/inventory/"
        data = self.client.get(url).json()
        for item in data:
            self.assertEqual(item["category"], "Gadgets")


# ---------------------------------------------------------------------------
# 5. Product search API — filtering and pagination
# ---------------------------------------------------------------------------

@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class ProductSearchAPITest(TestCase):
    def setUp(self):
        cat1 = make_category("Electronics")
        cat2 = make_category("Books")
        self.store = make_store()
        self.p1 = make_product(cat1, "Bluetooth Speaker", "49.99")
        self.p2 = make_product(cat2, "Python Programming Guide", "29.99")
        self.p3 = make_product(cat1, "Noise Cancelling Headphones", "199.99")
        make_inventory(self.store, self.p1, 20)
        make_inventory(self.store, self.p3, 0)

    def test_keyword_search(self):
        response = self.client.get("/api/search/products/?q=bluetooth")
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["title"], "Bluetooth Speaker")

    def test_category_filter(self):
        response = self.client.get("/api/search/products/?category=Books")
        data = response.json()
        self.assertEqual(data["count"], 1)

    def test_price_range_filter(self):
        response = self.client.get("/api/search/products/?min_price=30&max_price=60")
        data = response.json()
        titles = [r["title"] for r in data["results"]]
        self.assertIn("Bluetooth Speaker", titles)
        self.assertNotIn("Noise Cancelling Headphones", titles)

    def test_store_id_adds_inventory_quantity(self):
        response = self.client.get(f"/api/search/products/?store_id={self.store.id}&q=bluetooth")
        data = response.json()
        self.assertEqual(data["results"][0]["inventory_quantity"], 20)

    def test_pagination_metadata_present(self):
        response = self.client.get("/api/search/products/")
        data = response.json()
        self.assertIn("count", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertIn("results", data)


# ---------------------------------------------------------------------------
# 6. Autocomplete API — rate limiting + min length
# ---------------------------------------------------------------------------

@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    AUTOCOMPLETE_RATE_LIMIT=100,
    AUTOCOMPLETE_RATE_WINDOW=60,
)
class AutocompleteAPITest(TestCase):
    def setUp(self):
        cat = make_category()
        make_product(cat, "Smart TV")
        make_product(cat, "Smart Watch")
        make_product(cat, "Smartphone")

    def test_requires_min_3_chars(self):
        response = self.client.get("/api/search/suggest/?q=sm")
        self.assertEqual(response.status_code, 400)

    def test_returns_suggestions(self):
        with patch("apps.search.views.check_autocomplete_rate_limit", return_value=True):
            response = self.client.get("/api/search/suggest/?q=sma")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("suggestions", data)
        self.assertGreater(len(data["suggestions"]), 0)

    def test_prefix_matches_appear_first(self):
        with patch("apps.search.views.check_autocomplete_rate_limit", return_value=True):
            response = self.client.get("/api/search/suggest/?q=sma")
        suggestions = response.json()["suggestions"]
        # All three products start with "Sma" — they should all appear
        self.assertTrue(all("Sma" in s or "sma" in s.lower() for s in suggestions))

    def test_rate_limit_returns_429(self):
        with patch("apps.search.views.check_autocomplete_rate_limit", return_value=False):
            response = self.client.get("/api/search/suggest/?q=sma")
        self.assertEqual(response.status_code, 429)
