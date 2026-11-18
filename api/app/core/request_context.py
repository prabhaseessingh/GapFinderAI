"""Per-request correlation ID shared by logs, audit events, AI runs and queued jobs."""

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

from fastapi import Request, Response

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{8,80}$")
logger = logging.getLogger("gapfinder.request")


def new_request_id() -> str:
    return f"req_{uuid4().hex}"


def current_request_id() -> str:
    value = _request_id.get()
    if value is None:
        value = new_request_id()
        _request_id.set(value)
    return value


def bind_request_id(value: str | None) -> str:
    request_id = value if value and _SAFE_ID.match(value) else new_request_id()
    _request_id.set(request_id)
    return request_id


async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = bind_request_id(request.headers.get("x-request-id"))
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    # Path templates only; never query strings, bodies or headers (may contain secrets/PII).
    route = request.scope.get("route")
    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "route": getattr(route, "path", "unmatched"),
                "status": response.status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        )
    )
    return response
