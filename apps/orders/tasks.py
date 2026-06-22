"""
Asynchronous Celery tasks for the orders app.

How it works:
- When an order is created, OrderCreateView calls send_order_notification.delay(order_id).
- Celery picks this up from the Redis broker and executes it in a worker process.
- This keeps the HTTP response fast — notification logic doesn't block the request.

Starting workers:
    celery -A config worker --loglevel=info

For scheduled tasks (e.g. daily inventory summary):
    celery -A config beat --loglevel=info
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_order_notification(self, order_id: int) -> dict:
    """
    Simulate sending an order confirmation notification.
    In production this would call an email/SMS/push service.
    Retries up to 3 times on failure with 60-second backoff.
    """
    try:
        from apps.orders.models import Order
        order = Order.objects.select_related("store").get(pk=order_id)

        # Simulate notification dispatch
        logger.info(
            "Notification sent for Order #%s [%s] at store '%s'",
            order.id,
            order.status,
            order.store.name,
        )
        return {"order_id": order_id, "status": order.status, "notified": True}

    except Exception as exc:
        logger.error("Failed to send notification for order #%s: %s", order_id, exc)
        raise self.retry(exc=exc)


@shared_task
def generate_daily_inventory_summary() -> dict:
    """
    Celery Beat scheduled task (runs daily).
    Aggregates low-stock inventory items across all stores.
    Configure in settings:
        CELERY_BEAT_SCHEDULE = {
            'daily-inventory-summary': {
                'task': 'apps.orders.tasks.generate_daily_inventory_summary',
                'schedule': crontab(hour=8, minute=0),
            }
        }
    """
    from django.db.models import Sum
    from apps.stores.models import Inventory

    low_stock = (
        Inventory.objects.filter(quantity__lt=10)
        .select_related("store", "product")
        .values("store__name", "product__title", "quantity")
        .order_by("quantity")[:50]
    )

    items = list(low_stock)
    logger.info("Daily inventory summary: %d low-stock items found", len(items))
    return {"low_stock_count": len(items), "items": items}
