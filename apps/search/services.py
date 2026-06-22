"""
Search service helpers.

Rate limiting strategy for autocomplete:
- Uses Redis as a sliding window counter per IP.
- Key: autocomplete:ratelimit:<ip>  (expires after WINDOW seconds)
- On each request: INCR the counter; if > LIMIT → reject with 429.
- This is a fixed-window approach (simple, low overhead, acceptable for UX-level limiting).
  A sliding window or token bucket could be used for stricter enforcement.
"""
import redis
from django.conf import settings
from django.core.cache import cache

_redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def check_autocomplete_rate_limit(ip: str) -> bool:
    """
    Returns True if the request is allowed, False if rate-limited.
    Limit: AUTOCOMPLETE_RATE_LIMIT requests per AUTOCOMPLETE_RATE_WINDOW seconds per IP.
    """
    limit = settings.AUTOCOMPLETE_RATE_LIMIT  # default 20
    window = settings.AUTOCOMPLETE_RATE_WINDOW  # default 60s

    key = f"autocomplete:ratelimit:{ip}"
    pipe = _redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, window)
    count, _ = pipe.execute()

    return count <= limit


def get_client_ip(request) -> str:
    """Extract real client IP, respecting X-Forwarded-For header."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")
