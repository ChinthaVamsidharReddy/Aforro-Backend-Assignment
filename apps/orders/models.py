from django.db import models
from apps.stores.models import Store
from apps.products.models import Product


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        REJECTED = "REJECTED", "Rejected"

    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["store", "-created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"Order #{self.pk} [{self.status}]"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    quantity_requested = models.PositiveIntegerField()

    class Meta:
        indexes = [models.Index(fields=["order"])]

    def __str__(self):
        return f"OrderItem: {self.product.title} x{self.quantity_requested}"
