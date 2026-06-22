from django.db.models import Count
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.stores.models import Store
from .models import Order
from .serializers import OrderCreateSerializer, OrderDetailSerializer, OrderListSerializer
from .services import create_order
from .tasks import send_order_notification


class OrderCreateView(APIView):
    """
    POST /orders/
    Creates an order atomically. All items must have sufficient stock for CONFIRMED status.
    If any item is out of stock, the entire order is REJECTED (no stock is deducted).
    After creation, fires an async Celery task to send a confirmation notification.
    """

    @extend_schema(
        tags=["Orders"],
        summary="Create a new order",
        description=(
            "Creates an order for a store with a list of products and quantities.\n\n"
            "**Business rules:**\n"
            "- All operations run inside `transaction.atomic()` for full consistency.\n"
            "- Inventory rows are locked with `SELECT FOR UPDATE` to prevent race conditions.\n"
            "- If **all** products have sufficient stock → order status = `CONFIRMED`, stock deducted.\n"
            "- If **any** product has insufficient stock → order status = `REJECTED`, no stock deducted.\n"
            "- After creation, an async Celery task sends a notification (non-blocking)."
        ),
        request=OrderCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=OrderDetailSerializer,
                description="Order created (CONFIRMED or REJECTED)",
                examples=[
                    OpenApiExample(
                        "CONFIRMED order",
                        value={
                            "id": 1, "store_id": 1, "status": "CONFIRMED",
                            "created_at": "2024-06-01T10:00:00Z",
                            "items": [
                                {"product_id": 42, "product_title": "Bluetooth Speaker", "quantity_requested": 3}
                            ]
                        },
                        response_only=True,
                    ),
                    OpenApiExample(
                        "REJECTED order (insufficient stock)",
                        value={
                            "id": 2, "store_id": 1, "status": "REJECTED",
                            "created_at": "2024-06-01T10:01:00Z",
                            "items": [
                                {"product_id": 99, "product_title": "Rare Item", "quantity_requested": 500}
                            ]
                        },
                        response_only=True,
                    ),
                ],
            ),
            400: OpenApiResponse(description="Invalid request body"),
            404: OpenApiResponse(description="Store not found"),
        },
        examples=[
            OpenApiExample(
                "Order request",
                value={
                    "store_id": 1,
                    "items": [
                        {"product_id": 42, "quantity_requested": 3},
                        {"product_id": 17, "quantity_requested": 1},
                    ]
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = create_order(
            store_id=serializer.validated_data["store_id"],
            items=serializer.validated_data["items"],
        )

        send_order_notification.delay(order.id)

        output = OrderDetailSerializer(order)
        return Response(output.data, status=status.HTTP_201_CREATED)


class OrderListView(APIView):
    """
    GET /stores/<store_id>/orders/
    Returns all orders for a store, newest first.
    Uses annotation (COUNT) to avoid N+1 queries — single SQL query.
    """

    @extend_schema(
        tags=["Stores"],
        summary="List orders for a store",
        description=(
            "Returns all orders belonging to the specified store, sorted by newest first.\n\n"
            "**Performance:** Uses `annotate(Count)` — fetches order + item count in a single SQL query. No N+1."
        ),
        responses={
            200: OpenApiResponse(
                response=OrderListSerializer(many=True),
                description="List of orders with item count",
                examples=[
                    OpenApiExample(
                        "Order list",
                        value=[
                            {"id": 10, "status": "CONFIRMED", "created_at": "2024-06-01T10:00:00Z", "total_items": 3},
                            {"id": 9,  "status": "REJECTED",  "created_at": "2024-06-01T09:45:00Z", "total_items": 1},
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

        orders = (
            Order.objects.filter(store_id=store_id)
            .annotate(total_items=Count("items"))
            .order_by("-created_at")
        )

        serializer = OrderListSerializer(orders, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
