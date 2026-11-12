"""Standard API response envelope, identical to the one used by the Atome (Next.js) API.

Seven mandatory fields plus an optional ``data``:

    {
      "http_status_code": 422,
      "status_code": 422,
      "status": "UNPROCESSABLE_ENTITY",
      "status_message": "error",
      "message": "Validation failed",
      "code": "VALIDATION_FAILED",
      "requestId": "req_ab12cd34ef56ab78",
      "data": {"fields": {"lines.0.qty": ["Must be at least 1"]}}
    }

Rules: real HTTP status codes (errors are never HTTP 200); ``data`` is omitted when there is no
payload; a paginated list is ``{"items": [...], "pagination": {"nextCursor": ..., "hasMore": ...}}``;
validation details live in ``data.fields``; the ``X-Request-Id`` header equals ``requestId``;
stack traces and internals are never returned.
"""

import re
import secrets

from odoo.http import request

STATUS_NAMES = {
    200: "OK",
    201: "CREATED",
    202: "ACCEPTED",
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "UNPROCESSABLE_ENTITY",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_SERVER_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def new_request_id():
    return "req_" + secrets.token_hex(8)


def resolve_request_id(incoming):
    """Accept a caller-supplied id only if it is short and safe; otherwise generate one."""
    if incoming and _SAFE_REQUEST_ID.match(incoming):
        return incoming
    return new_request_id()


def build_envelope(http_status, message, code, request_id, data=None):
    if http_status in STATUS_NAMES:
        status = STATUS_NAMES[http_status]
    elif http_status >= 500:
        status = "SERVER_ERROR"
    elif http_status >= 400:
        status = "CLIENT_ERROR"
    else:
        status = "OK"
    envelope = {
        "http_status_code": http_status,
        "status_code": http_status,  # equal to the HTTP status
        "status": status,
        "status_message": "success" if http_status < 400 else "error",
        "message": message,
        "code": str(code).upper(),
        "requestId": request_id,
    }
    if data is not None:  # `data` is omitted when there is nothing to send
        envelope["data"] = data
    return envelope


def paginated(items, next_cursor, has_more):
    return {"items": items, "pagination": {"nextCursor": next_cursor, "hasMore": has_more}}


class Outcome:
    """What a handler returns; the endpoint wrapper turns it into the envelope."""

    def __init__(self, http_status, message, code, data=None):
        self.http_status = http_status
        self.message = message
        self.code = code
        self.data = data


def ok(message, code, data=None):
    return Outcome(200, message, code, data)


def created(message, code, data=None):
    return Outcome(201, message, code, data)


class ApiError(Exception):
    """An expected failure with a real HTTP status. The message must be safe to show to clients."""

    def __init__(self, http_status, message, code, data=None):
        super().__init__(message)
        self.http_status = http_status
        self.message = message
        self.code = code
        self.data = data


class ValidationFailed(ApiError):
    """HTTP 422 with field-level messages in ``data.fields``."""

    def __init__(self, fields):
        super().__init__(422, "Validation failed", "VALIDATION_FAILED", {"fields": fields})


def respond(http_status, message, code, request_id, data=None):
    body = build_envelope(http_status, message, code, request_id, data)
    headers = [("X-Request-Id", request_id), ("Cache-Control", "no-store")]
    return request.make_json_response(body, headers=headers, status=http_status)
