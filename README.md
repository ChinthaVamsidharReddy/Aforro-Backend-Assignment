# Aforro Backend Assignment — Round 2

A production-ready backend built with **Django 5 · DRF · PostgreSQL · Redis · Celery · Docker**.

---

## Quick Start (Docker)

```bash
git clone https://github.com/ChinthaVamsidharReddy/Aforro-Backend-Assignment.git && cd Aforro-Backend-Assignment

# Start all services (API, PostgreSQL, Redis, Celery worker, Celery beat)
docker-compose up --build

# Seed the database with 1000+ products, 25 stores, inventory data
docker-compose exec api python manage.py seed_data
```

The API is available at **http://localhost:8000**.

---

## Interactive API Documentation (Swagger)

Once the server is running, open your browser:

| URL | What it is |
|-----|------------|
| **http://localhost:8000/api/docs/** | Swagger UI — interactive, try every endpoint in the browser |
| **http://localhost:8000/api/redoc/** | ReDoc — clean, readable reference documentation |
| **http://localhost:8000/api/schema/** | Raw OpenAPI 3.0 schema (JSON/YAML download) |

> **Tip:** Use Swagger UI (`/api/docs/`) to test all APIs directly — every endpoint has example request bodies, query parameters, and response schemas pre-filled. No Postman needed.

---

## Project Structure

```
aforro/
├── config/                  # Django project config
│   ├── settings.py
│   ├── urls.py              # includes /api/docs/, /api/redoc/, /api/schema/
│   ├── celery.py
│   └── wsgi.py
├── apps/
│   ├── products/            # Category + Product models, seed_data command
│   ├── stores/              # Store + Inventory models, inventory listing API
│   ├── orders/              # Order + OrderItem models, order creation/listing, Celery tasks
│   └── search/              # Product search API, autocomplete, Redis rate limiting, signals
├── tests/
│   └── test_core.py         # 19 test cases
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## API Reference

### POST /orders/
Create an order. All-or-nothing: CONFIRMED (stock deducted) or REJECTED (no deduction).

**Request:**
```json
{
  "store_id": 1,
  "items": [
    { "product_id": 42, "quantity_requested": 3 },
    { "product_id": 17, "quantity_requested": 1 }
  ]
}
```

**Response (CONFIRMED — all items in stock):**
```json
{
  "id": 101,
  "store_id": 1,
  "status": "CONFIRMED",
  "created_at": "2024-06-01T10:00:00Z",
  "items": [
    { "product_id": 42, "product_title": "Widget Pro", "quantity_requested": 3 },
    { "product_id": 17, "product_title": "Gadget X",   "quantity_requested": 1 }
  ]
}
```

**Response (REJECTED — insufficient stock or product not in store):**
```json
{
  "id": 102,
  "store_id": 1,
  "status": "REJECTED",
  "created_at": "2024-06-01T10:01:00Z",
  "items": [...]
}
```

> **Note:** To get a CONFIRMED order you must first run `seed_data` — without it the Inventory table is empty and every order is rejected.

---

### GET /stores/\<store_id\>/orders/
List all orders for a store, newest first.

```json
[
  { "id": 101, "status": "CONFIRMED", "created_at": "2024-06-01T10:00:00Z", "total_items": 2 },
  { "id": 98,  "status": "REJECTED",  "created_at": "2024-06-01T09:45:00Z", "total_items": 1 }
]
```

---

### GET /stores/\<store_id\>/inventory/
List inventory for a store, alphabetically by product title.

```json
[
  { "product_title": "Apple Watch",       "price": "299.99", "category": "Electronics", "quantity": 15 },
  { "product_title": "Bluetooth Speaker", "price": "49.99",  "category": "Electronics", "quantity": 40 }
]
```

---

### GET /api/search/products/
Full-featured product search with filters, sorting, and pagination.

**Query params:**
| Param       | Type   | Description                                      |
|-------------|--------|--------------------------------------------------|
| `q`         | string | Keyword (searches title, description, category)  |
| `category`  | string | Exact category name (case-insensitive)           |
| `min_price` | float  | Minimum price                                    |
| `max_price` | float  | Maximum price                                    |
| `store_id`  | int    | If set, adds `inventory_quantity` to each result |
| `in_stock`  | bool   | `true` = in-stock only, `false` = out-of-stock   |
| `sort`      | string | `price`, `-price`, `newest`, `relevance`         |
| `page`      | int    | Page number (default: 1)                         |
| `page_size` | int    | Results per page (default: 20, max: 100)         |

**Example:**
```
GET /api/search/products/?q=mobile&store_id=3&sort=price&page=1
```

**Response:**
```json
{
  "count": 12,
  "next": "http://localhost:8000/api/search/products/?page=2",
  "previous": null,
  "results": [
    {
      "id": 42,
      "title": "Bluetooth Speaker",
      "description": "High quality wireless speaker",
      "price": "49.99",
      "category": "Electronics",
      "created_at": "2024-05-15T08:00:00Z",
      "inventory_quantity": 40
    }
  ]
}
```

---

### GET /api/search/suggest/?q=\<query\>
Autocomplete — min 3 chars, max 10 suggestions, prefix matches first.

**Rate limited:** 20 requests/minute per IP (Redis).

```
GET /api/search/suggest/?q=adv
```
```json
{ 
  "suggestions": 

       ["Advanced bandwidth-monitored hardware",
        "Advanced bifurcated product",
        "Advanced content-based parallelism",
        "Advanced empowering moderator",
        "Advanced even-keeled budgetary management",
        "Advanced exuding extranet"
        ]
}
```

**429 response when rate limited:**
```json
{ "detail": "Rate limit exceeded. Max 20 requests/minute." }
```

---

## Running Tests

```bash
# With Docker
docker-compose exec api python manage.py test tests

# Locally (requires PostgreSQL + env vars)
python manage.py test tests
```

All 19 tests pass. Coverage includes:

1. Order CONFIRMED + stock deducted correctly
2. Order REJECTED when stock is insufficient
3. Stock unchanged on rejection
4. Order rejected when product not stocked in that store
5. Order list — correct count, sorted newest first
6. Order list — `total_items` annotation present
7. Inventory list — alphabetical order
8. Inventory list — category name included
9. Product search — keyword filter
10. Product search — category filter
11. Product search — price range filter
12. Product search — `inventory_quantity` annotation when `store_id` provided
13. Product search — pagination metadata present
14. Autocomplete — min-length enforcement returns 400
15. Autocomplete — suggestions returned for valid query
16. Autocomplete — prefix matches appear before partial matches
17. Autocomplete — rate limit returns 429

---

## Engineering Notes

### Concurrency & Race Conditions
`select_for_update()` is applied to Inventory rows inside `transaction.atomic()`. Concurrent requests for the same store/product are serialized at the PostgreSQL row level — no overselling is possible.

Product IDs are locked in **deterministic ascending order** to prevent deadlocks between two concurrent transactions that might otherwise try to acquire the same locks in opposite order.

### Query Optimization
- **Order listing**: uses `.annotate(total_items=Count("items"))` — single query, zero N+1.
- **Inventory listing**: uses `select_related("product__category")` — one JOIN across three tables.
- **Product search**: uses a `Subquery` for inventory annotation — one extra SQL column, no extra round-trip.
- **Autocomplete**: two indexed queries (`istartswith` + `icontains`), results cached in Redis.

### Redis — Dual Role
| Feature | Approach | TTL |
|---------|----------|-----|
| Product search cache | django-redis, MD5-keyed by all query params | 5 min |
| Autocomplete cache | Per-query-term key | 1 min |
| Autocomplete rate limit | Redis INCR + EXPIRE (fixed-window counter per IP) | 60 s |

**Cache invalidation**: Django signals on `post_save` / `post_delete` of `Product`, `Category`, and `Inventory` call `cache.delete_pattern("product_search:*")` to clear stale entries automatically.

### Celery — Async Processing
- **Broker**: Redis (`redis://redis:6379/0`)
- **`send_order_notification`**: fires after every order creation. Non-blocking — HTTP response returns immediately. Retries up to 3× with 60s backoff.
- **`generate_daily_inventory_summary`**: Celery Beat scheduled task (8 AM UTC) that reports low-stock items.

**Starting workers:**
```bash
# Inside Docker (via docker-compose)
docker-compose up worker beat

# Manually
celery -A config worker --loglevel=info
celery -A config beat   --loglevel=info
```

### Scalability Considerations
- **Horizontal API scaling**: stateless Django + gunicorn workers. Add more `api` replicas behind a load balancer.
- **Read scaling**: Read replicas for search-heavy workloads — Django supports multiple DB routing.
- **Search scaling**: Replace `icontains` with PostgreSQL full-text search (`SearchVector` / `SearchQuery` + GIN index) for 10M+ products.
- **Cache warming**: Pre-populate popular search queries on deploy to avoid cold-start latency spikes.
- **Celery scaling**: Multiple worker containers with dedicated queues (e.g. `notifications`, `reporting`) for prioritized processing.

### Future Improvements
- Full-text search with `django.contrib.postgres.search` and GIN indexes.
- Sliding-window rate limiting (vs. current fixed-window) for stricter autocomplete enforcement.
- API authentication (JWT / OAuth2).
- Structured logging + Sentry integration.
- CI/CD pipeline (GitHub Actions).
#   A f o r r o - B a c k e n d - A s s i g n m e n t  
 