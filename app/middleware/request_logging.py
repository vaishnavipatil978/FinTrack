import re
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_context import set_request_id

logger = structlog.get_logger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_QUIET_PATHS = frozenset({"/health", "/ready"})


class RequestContextMiddleware:
    """Assigns a request id, binds it to the log context, and emits one access log per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = MutableHeaders(scope=scope).get(REQUEST_ID_HEADER)
        is_valid = bool(incoming and _VALID_REQUEST_ID.match(incoming))
        request_id = incoming if is_valid and incoming else uuid.uuid4().hex
        set_request_id(request_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope["path"]
            log = logger.debug if path in _QUIET_PATHS else logger.info
            log(
                "request_completed",
                method=scope["method"],
                path=path,
                status_code=status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
