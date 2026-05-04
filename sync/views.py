import logging

from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def health(request):
    """
    GET /health/
    Returns {"status": "ok", "connections": <int>}

    Uses synchronous redis-py so this works as a plain Django view
    (no async overhead, no channel layer dependency).
    """
    try:
        import redis as sync_redis

        r = sync_redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=2)
        count_raw = r.get("jinka:conn_count")
        connections = max(0, int(count_raw)) if count_raw else 0
        r.close()
    except Exception as exc:
        logger.warning("Health check Redis error: %s", exc)
        connections = -1  # signal that Redis is unreachable

    return JsonResponse({"status": "ok", "connections": connections})
