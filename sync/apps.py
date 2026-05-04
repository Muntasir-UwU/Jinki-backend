from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class SyncConfig(AppConfig):
    name = "sync"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """
        Reset the Redis connection counter to 0 every time the process starts.
        This prevents a stale count persisting after a crash or redeploy.
        """
        import os

        # Skip during management commands that don't serve HTTP (migrations, etc.)
        if os.environ.get("RUN_MAIN") != "true" and not os.environ.get("DAPHNE_RUN"):
            # Only run once — daphne sets no special env var, so we just always try.
            pass

        try:
            import redis as sync_redis
            from django.conf import settings

            r = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
            r.set("jinka:conn_count", 0)
            r.close()
            logger.info("jinka:conn_count reset to 0 on startup.")
        except Exception as exc:
            logger.warning("Could not reset conn_count on startup: %s", exc)
