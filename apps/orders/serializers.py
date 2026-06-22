from rest_framework import serializers
from .models import Order, OrderItem


class OrderItemInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity_requested = serializers.IntegerField(min_value=1)


class OrderCreateSerializer(serializers.Serializer):
    store_id = serializers.IntegerField(min_value=1)
    items = OrderItemInputSerializer(many=True, min_length=1)


class OrderItemDetailSerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source="product.title")

    class Meta:
        model = OrderItem
        fields = ["product_id", "product_title", "quantity_requested"]


class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemDetailSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ["id", "store_id", "status", "created_at", "items"]


class OrderListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing: includes total item count."""
    total_items = serializers.IntegerField(read_only=True)

    class Meta:
        model = Order
        fields = ["id", "status", "created_at", "total_items"]
