from rest_framework import serializers
from apps.products.models import Product


class ProductSearchSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source="category.name")
    # inventory_quantity is annotated on the queryset when store_id is supplied
    inventory_quantity = serializers.IntegerField(default=None, allow_null=True)

    class Meta:
        model = Product
        fields = ["id", "title", "description", "price", "category", "created_at", "inventory_quantity"]
