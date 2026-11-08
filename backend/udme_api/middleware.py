from django.db import connection
from django.http import JsonResponse


class HealthCheckMiddleware:
    """Answers /api/v1/health BEFORE host validation and the HTTPS redirect, so platform health checks
    (which may use an internal Host header and plain HTTP) never fail with 400/301. No data is exposed."""
    def __init__(self, get_response): self.get_response = get_response

    def __call__(self, request):
        if request.path == "/api/v1/health" and request.method in ("GET", "HEAD"):
            try: connection.ensure_connection(); return JsonResponse({"status": "ok"})
            except Exception: return JsonResponse({"status": "database_unavailable"}, status=503)
        return self.get_response(request)
