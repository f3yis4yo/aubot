"""Request guards shared by the API routers."""
import time

from django.conf import settings
from django.core.cache import cache
from django.middleware.csrf import CsrfViewMiddleware
from ninja.errors import HttpError

SPECIALIST_GROUP = "Specialists"
OWNER_GROUP = "Owners"


def client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "unknown")


async def rate_limit(key: str, limit: int | None = None):
    """Fixed one-minute window per key, shared across workers through the cache (Redis)."""
    limit = limit or settings.AUBOT["RATE_LIMIT_PER_MINUTE"]
    bucket = f"rl:{key}:{int(time.time() // 60)}"
    if await cache.aadd(bucket, 1, 70):
        count = 1
    else:
        try:
            count = await cache.aincr(bucket)
        except ValueError:  # expired between add and incr
            await cache.aset(bucket, 1, 70)
            count = 1
    if count > limit:
        raise HttpError(429, "Too many requests. Please wait a moment and try again.")


def check_csrf(request):
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    rejected = CsrfViewMiddleware(lambda r: None).process_view(request, None, (), {})
    if rejected is not None:
        raise HttpError(403, "CSRF check failed. Refresh the page and try again.")


async def _user_groups(user) -> set[str]:
    return {name async for name in user.groups.values_list("name", flat=True)}


async def current_staff(request, owner: bool = False):
    """Return the logged-in staff user or raise 401/403. Also enforces CSRF on writes."""
    user = await request.auser()
    if not user.is_authenticated or not user.is_active:
        raise HttpError(401, "Please sign in.")
    groups = await _user_groups(user)
    is_owner = user.is_superuser or OWNER_GROUP in groups
    if owner and not is_owner:
        raise HttpError(403, "Only the business owner can change this.")
    if not (is_owner or user.is_staff or SPECIALIST_GROUP in groups):
        raise HttpError(403, "This account does not have specialist access.")
    check_csrf(request)
    user.aubot_is_owner = is_owner
    return user


def display_name(user) -> str:
    return user.get_full_name() or user.username
