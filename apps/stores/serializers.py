from rest_framework import serializers
from .models import Inventory


class InventoryItemSerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source="product.title")
    price = serializers.DecimalField(source="product.price", max_digits=10, decimal_places=2)
    category = serializers.CharField(source="product.category.name")

    class Meta:
        model = Inventory
        fields = ["product_title", "price", "category", "quantity"]
