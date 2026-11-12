"""Atome REST API (v1).

Base path: ``/atome/api/v1``. Authenticate with ``Authorization: Bearer <Odoo API key>`` and select
the database with the ``X-Odoo-Database`` header. Every response uses the standard envelope
(see ``envelope.py``). Quotations are only ever created as DRAFT; nothing here confirms an order.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

import psycopg2

from odoo import Command, http, release
from odoo.http import request

from .api import api_endpoint, read_json_body
from .envelope import ApiError, ValidationFailed, created, ok, paginated
from .validation import DOOR_CATEGORIES, Errors, parse_page_params, parse_quotation_payload

BASE = "/atome/api/v1"


def _money(value):
    return f"{Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _escape_like(value):
    return re.sub(r"([%_\\])", r"\\\1", value)


def serialize_order(order):
    lines = [
        {
            "id": line.id,
            "product_id": line.product_id.id,
            "product_name": line.product_id.display_name,
            "description": line.name,
            "qty": int(line.product_uom_qty),
            "unit_price": _money(line.price_unit),
            "subtotal": _money(line.price_subtotal),
        }
        for line in order.order_line
        if not line.display_type
    ]
    return {
        "id": order.id,
        "name": order.name,
        "atome_reference": order.atome_reference,
        "state": order.state,  # always "draft" for orders created through this API
        "customer": {"id": order.partner_id.id, "name": order.partner_id.name},
        "currency": order.currency_id.name,
        "amount_untaxed": _money(order.amount_untaxed),
        "amount_total": _money(order.amount_total),
        "created_at": order.create_date.isoformat() + "Z" if order.create_date else None,
        "lines": lines,
    }


def serialize_product(product):
    return {
        "id": product.id,
        "name": product.display_name,
        "code": product.default_code or None,
        "price": _money(product.list_price),
        "door_category": product.product_tmpl_id.atome_door_category or None,
    }


def _resolve_partner(env, payload, errors):
    """Returns an existing partner, an empty recordset (error recorded) or None (create inside the transaction)."""
    Partner = env["res.partner"]
    if payload["customer_partner_id"]:
        partner = Partner.browse(payload["customer_partner_id"]).exists()
        if not partner:
            errors.add("customer.partner_id", "No customer with this ID exists in Odoo")
        return partner
    name = payload["customer_name"]
    partner = Partner.search([("name", "=", name)], limit=1) or Partner.search([("name", "=ilike", _escape_like(name))], limit=1)
    if partner:
        return partner
    if not payload["create_customer"]:
        errors.add("customer.name", "Customer not found in Odoo. Create it first, or send create_customer_if_missing: true")
        return Partner.browse()
    if not Partner.has_access("create"):
        raise ApiError(
            403,
            "The API user is not allowed to create customers. Create the customer in Odoo first, or give the API user the 'Contact Creation' access right.",
            "FORBIDDEN",
        )
    return None


def _resolve_products(env, lines, errors):
    """One sellable product per line: an explicit product_id, else the product tagged with the door category."""
    Product = env["product.product"]
    products = []
    for line in lines:
        prefix = f"lines.{line['index']}"
        product = Product.browse()
        if line["product_id"]:
            product = Product.browse(line["product_id"]).exists()
            if not product or not product.sale_ok:
                errors.add(f"{prefix}.product_id", "No sellable product with this ID exists in Odoo")
                product = Product.browse()
        else:
            product = Product.search(
                [("sale_ok", "=", True), ("product_tmpl_id.atome_door_category", "=", line["door_category"])], order="id", limit=1
            )
            if not product:
                errors.add(f"{prefix}.door_category", f"No Odoo product is tagged for {line['door_category']}. Tag one, or send product_id")
        products.append(product)
    return products


class AtomeApi(http.Controller):
    # ------------------------------------------------------------------ health (public)
    @http.route(f"{BASE}/health", type="http", auth="public", csrf=False, save_session=False)
    @api_endpoint(("GET",), auth=False)
    def health(self, **kwargs):
        module = request.env["ir.module.module"].sudo().search([("name", "=", "atome_connector")], limit=1)
        return ok(
            "Service is healthy",
            "HEALTH_OK",
            {"database": request.env.cr.dbname, "odooVersion": release.version, "moduleVersion": module.installed_version or None},
        )

    # ------------------------------------------------------------------ products
    @http.route(f"{BASE}/products", type="http", auth="public", csrf=False, save_session=False)
    @api_endpoint(("GET",))
    def products(self, q=None, category=None, **kwargs):
        """GET /products?q=&category= : sellable products (array, max 50), with their Atome door category."""
        errors = Errors()
        if category is not None and category not in DOOR_CATEGORIES:
            errors.add("category", f"Must be one of {', '.join(DOOR_CATEGORIES)}")
        if errors:
            raise ValidationFailed(dict(errors))
        domain = [("sale_ok", "=", True)]
        if category:
            domain.append(("product_tmpl_id.atome_door_category", "=", category))
        if q and q.strip():
            domain += ["|", ("name", "ilike", q.strip()[:80]), ("default_code", "ilike", q.strip()[:80])]
        found = request.env["product.product"].search(domain, order="id", limit=50)
        return ok("Products retrieved successfully", "PRODUCTS_RETRIEVED", [serialize_product(p) for p in found])

    # ------------------------------------------------------------------ quotations
    @http.route(f"{BASE}/quotations", type="http", auth="public", csrf=False, save_session=False)
    @api_endpoint(("GET", "POST"))
    def quotations(self, **kwargs):
        if request.httprequest.method == "POST":
            return self._create_quotation()
        return self._list_quotations(kwargs)

    @http.route(f"{BASE}/quotations/<string:atome_reference>", type="http", auth="public", csrf=False, save_session=False)
    @api_endpoint(("GET",))
    def quotation(self, atome_reference, **kwargs):
        order = request.env["sale.order"].search([("atome_reference", "=", atome_reference)], limit=1)
        if not order:
            raise ApiError(404, "Quotation not found", "QUOTATION_NOT_FOUND")
        return ok("Quotation retrieved successfully", "QUOTATION_RETRIEVED", serialize_order(order))

    def _list_quotations(self, args):
        """Cursor-paginated (newest first): { items, pagination: { nextCursor, hasMore } }."""
        limit, cursor = parse_page_params(args)
        domain = [("atome_reference", "!=", False)]
        if cursor:
            domain.append(("id", "<", cursor))
        rows = request.env["sale.order"].search(domain, order="id desc", limit=limit + 1)
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = str(page[-1].id) if has_more and page else None
        return ok("Quotations retrieved successfully", "QUOTATIONS_RETRIEVED", paginated([serialize_order(o) for o in page], next_cursor, has_more))

    def _create_quotation(self):
        """Creates the customer (optional), the order and all lines in ONE transaction.

        Idempotent on ``atome_reference``: sending the same reference again returns the existing order
        (HTTP 200) instead of creating a duplicate. The order is left as a DRAFT quotation.
        """
        payload = parse_quotation_payload(read_json_body())
        env = request.env
        Order = env["sale.order"]

        existing = Order.search([("atome_reference", "=", payload["reference"])], limit=1)
        if existing:
            return ok("A quotation with this reference already exists", "QUOTATION_ALREADY_EXISTS", serialize_order(existing))

        errors = Errors()
        partner = _resolve_partner(env, payload, errors)
        products = _resolve_products(env, payload["lines"], errors)
        if errors:
            raise ValidationFailed(dict(errors))

        try:
            with env.cr.savepoint():  # all-or-nothing: a failure rolls back the customer and the order together
                if partner is None:
                    partner = env["res.partner"].create({"name": payload["customer_name"]})
                order = Order.create(
                    {
                        "partner_id": partner.id,
                        "client_order_ref": payload["reference"],
                        "atome_reference": payload["reference"],
                        "order_line": [
                            Command.create(
                                {
                                    "product_id": product.id,
                                    "product_uom_qty": line["qty"],
                                    "price_unit": float(line["unit_price"]),
                                    **({"name": line["description"]} if line["description"] else {}),
                                }
                            )
                            for line, product in zip(payload["lines"], products, strict=True)
                        ],
                    }
                )
                order.flush_recordset()  # surfaces constraint violations (e.g. the unique reference) here
        except psycopg2.IntegrityError:
            # Lost a race with an identical request: return the winner instead of failing.
            env.invalidate_all()
            winner = Order.search([("atome_reference", "=", payload["reference"])], limit=1)
            if winner:
                return ok("A quotation with this reference already exists", "QUOTATION_ALREADY_EXISTS", serialize_order(winner))
            raise ApiError(409, "The quotation conflicts with existing data.", "CONFLICT") from None

        return created("Draft quotation created", "QUOTATION_CREATED", serialize_order(order))
