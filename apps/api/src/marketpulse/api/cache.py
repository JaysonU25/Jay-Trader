from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

READ_CACHE = "public, s-maxage=3600"
NO_STORE = "no-store"


class CacheControlMiddleware(BaseHTTPMiddleware):
    """Apply the edge-cache policy in one place.

    Data updates at most daily, so an hour of Cloudflare edge cache is free
    performance. Anything under /internal/ is never cached, and only successful
    GETs are — caching an error would pin it at the edge for an hour.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/internal/"):
            response.headers["Cache-Control"] = NO_STORE
        elif request.method == "GET" and response.status_code == 200:
            response.headers["Cache-Control"] = READ_CACHE
        return response
