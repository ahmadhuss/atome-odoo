"""Endpoint wrapper: request id, authentication, method check, JSON body parsing and uniform
error -> envelope mapping. Internals are never exposed to clients."""

import functools
import json
import logging
import re

from psycopg2 import errors as pg_errors

from odoo.exceptions import AccessDenied, AccessError, MissingError, UserError, ValidationError
from odoo.http import request

from .envelope import ApiError, Outcome, respond, resolve_request_id

_logger = logging.getLogger(__name__)

SALES_GROUP = "sales_team.group_sale_salesman"
MAX_BODY_BYTES = 1_000_000


def authenticate():
    """Bearer API key -> runs the rest of the request as that user (so Odoo access rights apply)."""
    header = request.httprequest.headers.get("Authorization", "")
    match = re.match(r"^bearer\s+(.+)$", header, re.IGNORECASE)
    if not match:
        raise ApiError(401, "Authentication is required.", "UNAUTHENTICATED")
    key = match.group(1).strip()
    # 'rpc' is the scope used by Odoo's own JSON-2 API: any global (unscoped) key works.
    uid = request.env["res.users.apikeys"]._check_credentials(scope="rpc", key=key) if key else None
    if not uid:
        raise ApiError(401, "The API key is invalid or has expired.", "INVALID_API_KEY")
    request.update_env(user=uid)
    request.session.can_save = False  # stateless: no session cookie is created
    if not request.env.user.has_group(SALES_GROUP):
        raise ApiError(403, "The API user needs the Sales (User) access right.", "FORBIDDEN")
    return request.env.user


def read_json_body():
    raw = request.httprequest.get_data(cache=True)
    if len(raw) > MAX_BODY_BYTES:
        raise ApiError(413, "The request body is too large.", "PAYLOAD_TOO_LARGE")
    try:
        body = json.loads(raw.decode("utf-8") or "null")
    except (UnicodeDecodeError, ValueError):
        raise ApiError(400, "Request body must be valid JSON.", "INVALID_JSON") from None
    if not isinstance(body, dict):
        raise ApiError(400, "Request body must be a JSON object.", "INVALID_JSON")
    return body


def api_endpoint(methods, *, auth=True):
    """Wraps a handler that returns an Outcome (or raises ApiError)."""

    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(self, **kwargs):
            request_id = resolve_request_id(request.httprequest.headers.get("X-Request-Id"))
            try:
                if request.httprequest.method not in methods:
                    raise ApiError(405, f"Use {' or '.join(methods)} for this endpoint.", "METHOD_NOT_ALLOWED")
                if auth:
                    authenticate()
                outcome = handler(self, **kwargs)
                assert isinstance(outcome, Outcome)
                return respond(outcome.http_status, outcome.message, outcome.code, request_id, outcome.data)
            except ApiError as error:
                return respond(error.http_status, error.message, error.code, request_id, error.data)
            except (AccessError, AccessDenied):
                return respond(403, "You do not have access to this resource.", "FORBIDDEN", request_id)
            except MissingError:
                return respond(404, "The record no longer exists.", "NOT_FOUND", request_id)
            except (ValidationError, UserError) as error:
                # Odoo's own business-rule messages are written for end users, so they are safe to return.
                return respond(422, str(error.args[0]) if error.args else "The request violates a rule.", "BUSINESS_RULE_VIOLATED", request_id)
            except (pg_errors.SerializationFailure, pg_errors.DeadlockDetected):
                raise  # let Odoo retry the request transparently
            except Exception:  # noqa: BLE001 - last resort: log server-side, never leak details
                _logger.exception("Unhandled error in Atome API (%s)", request_id)
                return respond(500, "An unexpected error occurred.", "INTERNAL_ERROR", request_id)

        return wrapper

    return decorator
