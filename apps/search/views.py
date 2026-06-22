"""
Search views.

ProductSearchView — full-featured search with filtering, sorting, pagination, caching.
AutocompleteView  — ultra-fast suggest endpoint with Redis rate limiting.

Caching strategy (ProductSearchView):
- Cache key encodes all query params so different filter combos get distinct cache entries.
- TTL: 5 minutes (300s). Short enough to stay fresh, long enough to absorb traffic bursts.
- Invalidation: Django signals on post_save/post_delete of Product/Category/Inventory
  call cache.delete_pattern("product_search:*") to clear stale entries.
"""
import hashlib
import json

from django.core.cache import cache
from django.db.models import Q, OuterRef, Subquery, IntegerField, Value
from drf_spectacular.utils import (
    extend_schema, OpenApiParameter, OpenApiResponse, OpenApiExample
)
from drf_spectacular.types import OpenApiTypes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from apps.products.models import Product
from apps.stores.models import Inventory
from .serializers import ProductSearchSerializer
from .services import check_autocomplete_rate_limit, get_client_ip

SEARCH_CACHE_PREFIX = "product_search:"
SEARCH_CACHE_TTL = 300  # 5 minutes


class ProductSearchPaginator(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data,
        })


class ProductSearchView(APIView):
    """
    GET /api/search/products/
    Full-text product search with filters, sorting, pagination, and caching.
    """

    @extend_schema(
        tags=["Search"],
        summary="Search products",
        description=(
            "Keyword search across product title, description, and category name.\n\n"
            "**Caching:** Results are cached in Redis for 5 minutes per unique query combination. "
            "Cache is invalidated automatically when products or inventory change.\n\n"
            "**Performance:** When `store_id` is provided, inventory quantity is fetched via a "
            "SQL subquery (no extra round-trips). Supports pagination up to 100 results per page."
        ),
        parameters=[
            OpenApiParameter("q",        OpenApiTypes.STR,   description="Keyword to search in title, description, category"),
            OpenApiParameter("category", OpenApiTypes.STR,   description="Filter by exact category name (case-insensitive)"),
            OpenApiParameter("min_price",OpenApiTypes.FLOAT, description="Minimum product price"),
            OpenApiParameter("max_price",OpenApiTypes.FLOAT, description="Maximum product price"),
            OpenApiParameter("store_id", OpenApiTypes.INT,   description="If provided, includes inventory quantity for that store"),
            OpenApiParameter("in_stock", OpenApiTypes.STR,   description="'true' to show only in-stock products, 'false' for out-of-stock"),
            OpenApiParameter("sort",     OpenApiTypes.STR,   description="Sort order: 'price', '-price', 'newest', 'relevance'"),
            OpenApiParameter("page",     OpenApiTypes.INT,   description="Page number (default: 1)"),
            OpenApiParameter("page_size",OpenApiTypes.INT,   description="Results per page (default: 20, max: 100)"),
        ],
        responses={
            200: OpenApiResponse(
                description="Paginated search results",
                examples=[
                    OpenApiExample(
                        "Search results with store inventory",
                        value={
                            "count": 5,
                            "next": "http://localhost:8000/api/search/products/?page=2",
                            "previous": None,
                            "results": [
                                {
                                    "id": 42,
                                    "title": "Bluetooth Speaker Pro",
                                    "description": "High quality wireless speaker",
                                    "price": "49.99",
                                    "category": "Electronics",
                                    "created_at": "2024-05-15T08:00:00Z",
                                    "inventory_quantity": 40,
                                }
                            ]
                        },
                        response_only=True,
                    )
                ],
            ),
        },
    )
    def get(self, request):
        params = request.query_params
        cache_key = self._make_cache_key(params)

        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        qs = Product.objects.select_related("category")

        # --- Keyword search ---
        q = params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q) |
                Q(description__icontains=q) |
                Q(category__name__icontains=q)
            )

        # --- Filters ---
        category = params.get("category", "").strip()
        if category:
            qs = qs.filter(category__name__iexact=category)

        min_price = params.get("min_price")
        if min_price:
            qs = qs.filter(price__gte=min_price)

        max_price = params.get("max_price")
        if max_price:
            qs = qs.filter(price__lte=max_price)

        store_id = params.get("store_id")
        if store_id:
            # Annotate inventory quantity for the given store via a subquery
            # (single extra column, no extra round-trip)
            inv_subquery = Inventory.objects.filter(
                store_id=store_id,
                product=OuterRef("pk"),
            ).values("quantity")[:1]
            qs = qs.annotate(inventory_quantity=Subquery(inv_subquery, output_field=IntegerField()))
        else:
            # No store_id — annotate with NULL so serializer field is consistent
            qs = qs.annotate(inventory_quantity=Value(None, output_field=IntegerField()))

        in_stock = params.get("in_stock", "").lower()
        if in_stock == "true":
            if store_id:
                qs = qs.filter(inventory_quantity__gt=0)
            else:
                qs = qs.filter(inventory_items__quantity__gt=0).distinct()
        elif in_stock == "false":
            if store_id:
                qs = qs.filter(inventory_quantity=0)

        # --- Sorting ---
        sort = params.get("sort", "relevance")
        sort_map = {
            "price": "price",
            "-price": "-price",
            "newest": "-created_at",
            "relevance": "-created_at",
        }
        qs = qs.order_by(sort_map.get(sort, "-created_at"))

        # --- Pagination ---
        paginator = ProductSearchPaginator()
        page = paginator.paginate_queryset(qs, request)
        serializer = ProductSearchSerializer(page, many=True)

        response = paginator.get_paginated_response(serializer.data)
        cache.set(cache_key, response.data, SEARCH_CACHE_TTL)
        return response

    @staticmethod
    def _make_cache_key(params) -> str:
        """Deterministic cache key from sorted query params."""
        param_str = json.dumps(sorted(params.items()), sort_keys=True)
        digest = hashlib.md5(param_str.encode()).hexdigest()
        return f"{SEARCH_CACHE_PREFIX}{digest}"


class AutocompleteView(APIView):
    """
    GET /api/search/suggest/?q=xxx
    Ultra-fast product title suggestions with Redis rate limiting and caching.
    """

    @extend_schema(
        tags=["Search"],
        summary="Product title autocomplete",
        description=(
            "Returns up to 10 product title suggestions for a query prefix.\n\n"
            "**Rules:**\n"
            "- Minimum 3 characters required.\n"
            "- Prefix matches appear before general partial matches.\n"
            "- Results cached in Redis for 60 seconds per query term.\n\n"
            "**Rate limiting:** 20 requests/minute per IP address (Redis-backed fixed-window counter). "
            "Exceeding the limit returns HTTP 429."
        ),
        parameters=[
            OpenApiParameter(
                "q", OpenApiTypes.STR, required=True,
                description="Search prefix (minimum 3 characters)"
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="List of matching product titles",
                examples=[
                    OpenApiExample(
                        "Suggestions",
                        value={"suggestions": ["Speaker Deluxe 2000", "Speaker Mini", "Spectrum Analyzer"]},
                        response_only=True,
                    )
                ],
            ),
            400: OpenApiResponse(description="Query too short (less than 3 characters)"),
            429: OpenApiResponse(description="Rate limit exceeded — 20 requests/minute per IP"),
        },
    )
    def get(self, request):
        ip = get_client_ip(request)
        if not check_autocomplete_rate_limit(ip):
            return Response(
                {"detail": "Rate limit exceeded. Max 20 requests/minute."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        q = request.query_params.get("q", "").strip()
        if len(q) < 3:
            return Response(
                {"detail": "Query must be at least 3 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache_key = f"autocomplete:{q.lower()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response({"suggestions": cached})

        # Prefix matches first (title starts with q)
        prefix_matches = list(
            Product.objects.filter(title__istartswith=q)
            .values_list("title", flat=True)
            .order_by("title")[:10]
        )

        # Fill remaining slots with partial matches (contains q but doesn't start with it)
        remaining = 10 - len(prefix_matches)
        if remaining > 0:
            partial_matches = list(
                Product.objects.filter(title__icontains=q)
                .exclude(title__istartswith=q)
                .values_list("title", flat=True)
                .order_by("title")[:remaining]
            )
        else:
            partial_matches = []

        suggestions = prefix_matches + partial_matches
        cache.set(cache_key, suggestions, 60)

        return Response({"suggestions": suggestions})
