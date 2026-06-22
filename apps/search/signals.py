"""
Cache invalidation via Django signals.
When products or inventory change, relevant search cache entries are cleared.
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache

from apps.products.models import Product, Category
from apps.stores.models import Inventory

SEARCH_CACHE_PREFIX = "product_search:"


def _clear_search_cache():
    """
    Clear all product search cache entries.
    django-redis supports delete_pattern for wildcard deletion.
    Falls back to a no-op if the backend doesn't support it.
    """
    try:
        cache.delete_pattern(f"{SEARCH_CACHE_PREFIX}*")
    except AttributeError:
        # Non-Redis backend (e.g. LocMemCache in tests) — skip
        pass


@receiver([post_save, post_delete], sender=Product)
def invalidate_on_product_change(sender, instance, **kwargs):
    _clear_search_cache()
    # Also clear autocomplete cache for words in this product title
    for word in instance.title.split():
        cache.delete(f"autocomplete:{word[:3].lower()}")


@receiver([post_save, post_delete], sender=Category)
def invalidate_on_category_change(sender, instance, **kwargs):
    _clear_search_cache()


@receiver([post_save, post_delete], sender=Inventory)
def invalidate_on_inventory_change(sender, instance, **kwargs):
    _clear_search_cache()
