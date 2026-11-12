from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

API = "/atome/api/v1"
ENVELOPE_FIELDS = {"http_status_code", "status_code", "status", "status_message", "message", "code", "requestId"}


@tagged("post_install", "-at_install")
class TestAtomeApi(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_user = cls.env.ref("base.group_user")
        sales = cls.env.ref("sales_team.group_sale_salesman")
        cls.sales_user = cls.env["res.users"].create(
            {"name": "Atome API", "login": "atome_api", "group_ids": [Command.set([group_user.id, sales.id])]}
        )
        cls.plain_user = cls.env["res.users"].create(
            {"name": "No Sales", "login": "atome_nosales", "group_ids": [Command.set([group_user.id])]}
        )
        keys = cls.env["res.users.apikeys"]
        cls.api_key = keys.with_user(cls.sales_user).sudo()._generate(None, "atome test", None)
        cls.plain_key = keys.with_user(cls.plain_user).sudo()._generate(None, "atome test", None)
        cls.fire = cls.env.ref("atome_connector.product_door_fire_rated")
        cls.customer = cls.env["res.partner"].create({"name": "Harbourline Construction Ltd"})

    # ------------------------------------------------------------------ helpers
    def api(self, method, path, *, json=None, data=None, key="default", headers=None):
        h = {}
        if key == "default":
            key = self.api_key
        if key:
            h["Authorization"] = f"Bearer {key}"
        h.update(headers or {})
        return self.url_open(f"{API}{path}", method=method, json=json, data=data, headers=h)

    def assert_envelope(self, response, http_status, code):
        self.assertEqual(response.status_code, http_status)
        body = response.json()
        self.assertTrue(ENVELOPE_FIELDS <= set(body), f"missing envelope fields in {body}")
        self.assertEqual(body["http_status_code"], http_status)
        self.assertEqual(body["status_code"], http_status)
        self.assertEqual(body["status_message"], "success" if http_status < 400 else "error")
        self.assertEqual(body["code"], code)
        self.assertRegex(body["requestId"], r"^[A-Za-z0-9_-]{8,64}$")
        self.assertEqual(response.headers["X-Request-Id"], body["requestId"])
        self.assertNotIn("Traceback", response.text)
        return body

    def allow_customer_creation(self):
        """Odoo's Sales role cannot create contacts; this adds the 'Contact Creation' right to the API user."""
        self.sales_user.group_ids = [Command.link(self.env.ref("base.group_partner_manager").id)]

    def payload(self, reference="ATM-1001", **overrides):
        body = {
            "atome_reference": reference,
            "customer": {"name": "Harbourline Construction Ltd"},
            "lines": [
                {"door_category": "FIRE_RATED", "description": "D-101 - Fire-rated door, 2100 x 900 mm", "qty": 4, "unit_price": "125.50"},
                {"product_id": self.fire.product_variant_id.id, "qty": 1, "unit_price": 99},
            ],
        }
        body.update(overrides)
        return body

    # ------------------------------------------------------------------ seed data
    def test_one_product_per_door_category_is_created(self):
        for xmlid, category in [
            ("product_door_fire_rated", "FIRE_RATED"),
            ("product_door_smoke_rated", "SMOKE_RATED"),
            ("product_door_standard", "STANDARD"),
            ("product_door_other", "OTHER"),
        ]:
            product = self.env.ref(f"atome_connector.{xmlid}")
            self.assertEqual(product.atome_door_category, category)
            self.assertTrue(product.sale_ok)

    # ------------------------------------------------------------------ envelope, auth, errors
    def test_health_is_public_and_uses_the_envelope(self):
        body = self.assert_envelope(self.api("GET", "/health", key=None), 200, "HEALTH_OK")
        self.assertEqual(body["data"]["database"], self.env.cr.dbname)

    def test_missing_key_is_401(self):
        body = self.assert_envelope(self.api("GET", "/products", key=None), 401, "UNAUTHENTICATED")
        self.assertNotIn("data", body)  # `data` is omitted when there is no payload

    def test_invalid_key_is_401(self):
        self.assert_envelope(self.api("GET", "/products", key="not-a-real-key"), 401, "INVALID_API_KEY")

    def test_user_without_sales_access_is_403(self):
        self.assert_envelope(self.api("GET", "/products", key=self.plain_key), 403, "FORBIDDEN")

    def test_wrong_method_is_405(self):
        self.assert_envelope(self.api("DELETE", "/products"), 405, "METHOD_NOT_ALLOWED")

    def test_invalid_json_is_400(self):
        h = {"Content-Type": "application/json"}
        self.assert_envelope(self.api("POST", "/quotations", data="{bad json", headers=h), 400, "INVALID_JSON")
        self.assert_envelope(self.api("POST", "/quotations", data="[1, 2]", headers=h), 400, "INVALID_JSON")

    def test_request_id_is_echoed_only_when_safe(self):
        ok = self.api("GET", "/health", key=None, headers={"X-Request-Id": "req_clientsupplied1"})
        self.assertEqual(ok.json()["requestId"], "req_clientsupplied1")
        bad = self.api("GET", "/health", key=None, headers={"X-Request-Id": "bad id<script>"})
        self.assertRegex(bad.json()["requestId"], r"^req_[0-9a-f]{16}$")

    def test_validation_errors_are_collected_in_data_fields(self):
        body = self.assert_envelope(self.api("POST", "/quotations", json={}), 422, "VALIDATION_FAILED")
        fields = body["data"]["fields"]
        self.assertEqual(body["message"], "Validation failed")
        self.assertIn("atome_reference", fields)
        self.assertIn("customer", fields)
        self.assertIn("lines", fields)

        bad = self.payload(
            reference="x",
            lines=[
                {"door_category": "NOPE", "qty": 0, "unit_price": "abc"},
                {"qty": "2", "unit_price": "1.234"},
                {"door_category": "STANDARD", "qty": 1.5, "unit_price": -5},
            ],
        )
        fields = self.assert_envelope(self.api("POST", "/quotations", json=bad), 422, "VALIDATION_FAILED")["data"]["fields"]
        self.assertIn("atome_reference", fields)
        self.assertEqual(fields["lines.0.door_category"], ["Must be one of FIRE_RATED, SMOKE_RATED, STANDARD, OTHER"])
        self.assertEqual(fields["lines.0.qty"], ["Must be at least 1"])
        self.assertIn("lines.0.unit_price", fields)
        self.assertEqual(fields["lines.1.door_category"], ["Provide door_category or product_id"])
        self.assertEqual(fields["lines.1.unit_price"], ["Use at most 2 decimal places"])
        self.assertEqual(fields["lines.2.qty"], ["Must be a whole number"])
        self.assertEqual(fields["lines.2.unit_price"], ["Must not be negative"])
        self.assertFalse(self.env["sale.order"].search([("atome_reference", "=", "x")]))

    # ------------------------------------------------------------------ create
    def test_create_quotation_is_a_draft_with_all_lines(self):
        body = self.assert_envelope(self.api("POST", "/quotations", json=self.payload()), 201, "QUOTATION_CREATED")
        data = body["data"]
        self.assertEqual(data["state"], "draft")  # never confirmed
        self.assertEqual(data["atome_reference"], "ATM-1001")
        self.assertEqual(data["customer"]["name"], "Harbourline Construction Ltd")
        self.assertEqual(len(data["lines"]), 2)
        first = data["lines"][0]
        self.assertEqual((first["qty"], first["unit_price"], first["subtotal"]), (4, "125.50", "502.00"))
        self.assertEqual(first["description"], "D-101 - Fire-rated door, 2100 x 900 mm")
        self.assertEqual(first["product_id"], self.fire.product_variant_id.id)  # resolved from the category tag
        self.assertEqual(data["amount_untaxed"], "601.00")

        order = self.env["sale.order"].search([("atome_reference", "=", "ATM-1001")])
        self.assertEqual(len(order), 1)
        self.assertEqual(order.state, "draft")
        self.assertEqual(order.client_order_ref, "ATM-1001")
        self.assertEqual(order.create_uid, self.sales_user)  # runs as the API key's user

    def test_same_reference_never_creates_a_duplicate(self):
        first = self.assert_envelope(self.api("POST", "/quotations", json=self.payload("ATM-2001")), 201, "QUOTATION_CREATED")
        again = self.assert_envelope(self.api("POST", "/quotations", json=self.payload("ATM-2001")), 200, "QUOTATION_ALREADY_EXISTS")
        self.assertEqual(first["data"]["id"], again["data"]["id"])
        self.assertEqual(self.env["sale.order"].search_count([("atome_reference", "=", "ATM-2001")]), 1)

    def test_unknown_customer_is_422_unless_creation_is_requested(self):
        body = self.payload("ATM-3001", customer={"name": "Brand New Customer Ltd"})
        fields = self.assert_envelope(self.api("POST", "/quotations", json=body), 422, "VALIDATION_FAILED")["data"]["fields"]
        self.assertIn("customer.name", fields)
        self.assertFalse(self.env["res.partner"].search([("name", "=", "Brand New Customer Ltd")]))

        body["create_customer_if_missing"] = True
        self.allow_customer_creation()
        self.assert_envelope(self.api("POST", "/quotations", json=body), 201, "QUOTATION_CREATED")
        self.assertEqual(self.env["res.partner"].search_count([("name", "=", "Brand New Customer Ltd")]), 1)

    def test_creating_a_customer_needs_the_contact_creation_right(self):
        body = self.payload("ATM-3003", customer={"name": "Not Allowed Ltd"}, create_customer_if_missing=True)
        response = self.api("POST", "/quotations", json=body)
        envelope = self.assert_envelope(response, 403, "FORBIDDEN")
        self.assertIn("Contact Creation", envelope["message"])
        self.assertFalse(self.env["res.partner"].search([("name", "=", "Not Allowed Ltd")]))
        self.assertFalse(self.env["sale.order"].search([("atome_reference", "=", "ATM-3003")]))

    def test_unknown_product_and_unknown_partner_id_are_field_errors(self):
        body = self.payload("ATM-3002", customer={"name": "X", "partner_id": 999999}, lines=[{"product_id": 999999, "qty": 1, "unit_price": 1}])
        fields = self.assert_envelope(self.api("POST", "/quotations", json=body), 422, "VALIDATION_FAILED")["data"]["fields"]
        self.assertIn("customer.partner_id", fields)
        self.assertIn("lines.0.product_id", fields)

    def test_failure_rolls_back_everything_including_a_new_customer(self):
        body = self.payload("ATM-4001", customer={"name": "Rolled Back Ltd"}, create_customer_if_missing=True)
        self.allow_customer_creation()
        order_model = type(self.env["sale.order"])
        with patch.object(order_model, "create", side_effect=UserError("Simulated failure")):
            response = self.api("POST", "/quotations", json=body)
        self.assert_envelope(response, 422, "BUSINESS_RULE_VIOLATED")
        self.assertFalse(self.env["res.partner"].search([("name", "=", "Rolled Back Ltd")]), "customer must not survive a failed order")
        self.assertFalse(self.env["sale.order"].search([("atome_reference", "=", "ATM-4001")]))

    # ------------------------------------------------------------------ read
    def test_get_quotation_by_reference(self):
        self.api("POST", "/quotations", json=self.payload("ATM-5001"))
        body = self.assert_envelope(self.api("GET", "/quotations/ATM-5001"), 200, "QUOTATION_RETRIEVED")
        self.assertEqual(body["data"]["atome_reference"], "ATM-5001")
        missing = self.assert_envelope(self.api("GET", "/quotations/ATM-NOPE"), 404, "QUOTATION_NOT_FOUND")
        self.assertNotIn("data", missing)

    def test_list_is_cursor_paginated_newest_first(self):
        for n in (1, 2, 3):
            self.api("POST", "/quotations", json=self.payload(f"ATM-600{n}"))
        page1 = self.assert_envelope(self.api("GET", "/quotations?limit=2"), 200, "QUOTATIONS_RETRIEVED")["data"]
        self.assertEqual([o["atome_reference"] for o in page1["items"]], ["ATM-6003", "ATM-6002"])
        self.assertTrue(page1["pagination"]["hasMore"])
        cursor = page1["pagination"]["nextCursor"]
        self.assertTrue(cursor)

        page2 = self.assert_envelope(self.api("GET", f"/quotations?limit=2&cursor={cursor}"), 200, "QUOTATIONS_RETRIEVED")["data"]
        self.assertEqual([o["atome_reference"] for o in page2["items"]], ["ATM-6001"])
        self.assertEqual(page2["pagination"], {"nextCursor": None, "hasMore": False})

        fields = self.assert_envelope(self.api("GET", "/quotations?limit=0&cursor=abc"), 422, "VALIDATION_FAILED")["data"]["fields"]
        self.assertIn("limit", fields)
        self.assertIn("cursor", fields)

    def test_products_collection_is_an_array_with_category_filter(self):
        data = self.assert_envelope(self.api("GET", "/products?category=FIRE_RATED"), 200, "PRODUCTS_RETRIEVED")["data"]
        self.assertIsInstance(data, list)
        self.assertEqual([p["id"] for p in data], [self.fire.product_variant_id.id])
        self.assertEqual(data[0]["door_category"], "FIRE_RATED")
        found = self.api("GET", "/products?q=smoke").json()["data"]
        self.assertTrue(any(p["door_category"] == "SMOKE_RATED" for p in found))
        fields = self.assert_envelope(self.api("GET", "/products?category=WOODEN"), 422, "VALIDATION_FAILED")["data"]["fields"]
        self.assertIn("category", fields)

    # ------------------------------------------------------------------ model
    @mute_logger("odoo.sql_db")
    def test_atome_reference_is_unique_in_the_database(self):
        vals = {"partner_id": self.customer.id, "atome_reference": "ATM-7001"}
        self.env["sale.order"].create(vals)
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env["sale.order"].create(vals)
        # Several orders without an Atome reference are fine.
        self.env["sale.order"].create({"partner_id": self.customer.id})
        self.env["sale.order"].create({"partner_id": self.customer.id})
