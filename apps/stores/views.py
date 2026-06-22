from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Store, Inventory
from .serializers import InventoryItemSerializer


class InventoryListView(APIView):
    """
    GET /stores/<store_id>/inventory/
    Returns inventory for a store sorted alphabetically by product title.
    Uses select_related to join products + categories in a single query (no N+1).
    """

    @extend_schema(
        tags=["Stores"],
        summary="List inventory for a store",
        description=(
            "Returns all inventory items for the specified store, sorted alphabetically by product title.\n\n"
            "**Performance:** Uses `select_related('product__category')` — fetches inventory, "
            "product, and category in a single SQL JOIN query. No N+1 problem."
        ),
        responses={
            200: OpenApiResponse(
                response=InventoryItemSerializer(many=True),
                description="Inventory list sorted by product title",
                examples=[
                    OpenApiExample(
                        "Inventory response",
                        value=[
                            {"product_title": "Apple Watch",       "price": "299.99", "category": "Electronics", "quantity": 15},
                            {"product_title": "Bluetooth Speaker", "price": "49.99",  "category": "Electronics", "quantity": 40},
                            {"product_title": "Python Book",       "price": "29.99",  "category": "Books",       "quantity": 0},
                        ],
                        response_only=True,
                    )
                ],
            ),
            404: OpenApiResponse(description="Store not found"),
        },
    )
    def get(self, request, store_id):
        get_object_or_404(Store, pk=store_id)

        inventory = (
            Inventory.objects.filter(store_id=store_id)
            .select_related("product", "product__category")
            .order_by("product__title")
        )

        serializer = InventoryItemSerializer(inventory, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
