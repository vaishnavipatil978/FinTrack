from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}
_DOCS_PATHS = frozenset({"/docs", "/redoc"})
_HSTS = "max-age=63072000; includeSubDomains"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, enable_hsts: bool) -> None:
        self.app = app
        self.enable_hsts = enable_hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_docs = scope["path"] in _DOCS_PATHS

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _HEADERS.items():
                    if name == "Content-Security-Policy" and is_docs:
                        continue  # Swagger UI / ReDoc load scripts that a strict CSP would block
                    headers.setdefault(name, value)
                if self.enable_hsts:
                    headers.setdefault("Strict-Transport-Security", _HSTS)
            await send(message)

        await self.app(scope, receive, send_wrapper)
