from django.db import models
from apps.products.models import Product


class Store(models.Model):
    name = models.CharField(max_length=500)
    location = models.CharField(max_length=500)

    class Meta:
        indexes = [models.Index(fields=["name"])]

    def __str__(self):
        return self.name


class Inventory(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="inventory_items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="inventory_items")
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        # DB-level constraint: one inventory row per (store, product) pair
        unique_together = [("store", "product")]
        indexes = [
            models.Index(fields=["store", "product"]),
            models.Index(fields=["quantity"]),
        ]

    def __str__(self):
        return f"{self.store.name} — {self.product.title}: {self.quantity}"
