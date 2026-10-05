import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.metrics import HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL


class MetricsMiddleware:
    """Records request count/latency labelled by the route *template* (e.g. "/accounts/{id}"),
    never the raw path, so path parameters never create unbounded label cardinality - see
    docs/architecture/observability.md §4.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)

        route = scope.get("route")
        path_template = getattr(route, "path", scope.get("path", "unknown"))
        method = scope.get("method", "UNKNOWN")
        duration = time.perf_counter() - start
        HTTP_REQUESTS_TOTAL.labels(method=method, path=path_template, status_code=status_code).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=path_template).observe(duration)
