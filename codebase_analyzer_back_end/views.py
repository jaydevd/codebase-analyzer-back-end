import os
import time
import django
from django.db import connection, connections
from django.http import JsonResponse
from django.conf import settings


def health_check(request):
    start = time.time()

    checks = {}
    all_ok = True

    # Database check
    try:
        connections["default"].cursor().execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        all_ok = False

    # Redis cache check (if configured)
    cache_location = getattr(settings, "CACHES", {}).get("default", {}).get("LOCATION")
    if cache_location:
        try:
            import redis
            client = redis.from_url(cache_location if isinstance(cache_location, str) else cache_location[0])
            client.ping()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {e}"
            all_ok = False

    elapsed = time.time() - start

    return JsonResponse(
        {
            "status": "healthy" if all_ok else "unhealthy",
            "checks": checks,
            "uptime": time.time() - django_start_time,
            "response_time_ms": round(elapsed * 1000, 2),
        },
        status=200 if all_ok else 503,
    )


django_start_time = time.time()
