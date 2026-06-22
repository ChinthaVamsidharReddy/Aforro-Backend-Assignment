"""
Order service — all business logic lives here, views stay thin.

Key design decisions:
- select_for_update() on Inventory rows prevents race conditions (pessimistic locking).
  Two concurrent orders for the same product+store will serialize at the DB level.
- The entire flow runs inside transaction.atomic() so any unexpected exception rolls
  back both Order creation and any Inventory deductions atomically.
- We intentionally create the Order before checking stock so we always have a
  persistent record (REJECTED or CONFIRMED) regardless of outcome.
"""
from django.db import transaction
from django.shortcuts import get_object_or_404

from apps.stores.models import Store, Inventory
from apps.products.models import Product
from .models import Order, OrderItem


def create_order(store_id: int, items: list[dict]) -> Order:
    """
    Create an order for `store_id` with the given list of
    {"product_id": int, "quantity_requested": int} dicts.

    Returns the saved Order instance (CONFIRMED or REJECTED).
    """
    store = get_object_or_404(Store, pk=store_id)

    with transaction.atomic():
        # 1. Lock inventory rows for all requested products in deterministic order
        #    (ordered by product_id to avoid deadlocks with concurrent requests).
        product_ids = sorted({item["product_id"] for item in items})

        inventory_qs = (
            Inventory.objects.select_for_update()
            .filter(store=store, product_id__in=product_ids)
            .select_related("product")
        )
        inventory_map: dict[int, Inventory] = {inv.product_id: inv for inv in inventory_qs}

        # 2. Validate all products exist and belong to the store
        missing_products = [pid for pid in product_ids if pid not in inventory_map]
        if missing_products:
            # Create REJECTED order — products not stocked in this store
            order = Order.objects.create(store=store, status=Order.Status.REJECTED)
            _create_order_items(order, items)
            return order

        # 3. Check stock sufficiency
        insufficient = []
        for item in items:
            inv = inventory_map[item["product_id"]]
            if inv.quantity < item["quantity_requested"]:
                insufficient.append(item["product_id"])

        if insufficient:
            # REJECTED: create order + items, do NOT deduct stock
            order = Order.objects.create(store=store, status=Order.Status.REJECTED)
            _create_order_items(order, items)
            return order

        # 4. All good — deduct stock and confirm
        order = Order.objects.create(store=store, status=Order.Status.CONFIRMED)
        _create_order_items(order, items)

        for item in items:
            inv = inventory_map[item["product_id"]]
            inv.quantity -= item["quantity_requested"]
            inv.save(update_fields=["quantity"])

        return order


def _create_order_items(order: Order, items: list[dict]) -> None:
    """Bulk-create OrderItem rows."""
    OrderItem.objects.bulk_create([
        OrderItem(
            order=order,
            product_id=item["product_id"],
            quantity_requested=item["quantity_requested"],
        )
        for item in items
    ])
