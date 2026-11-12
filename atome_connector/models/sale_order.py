from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    atome_reference = fields.Char(
        string="Atome Reference",
        copy=False,
        index=True,
        readonly=True,
        help="Reference of the quotation in Atome. Unique, so the same Atome quotation never creates two orders.",
    )

    _atome_reference_uniq = models.Constraint(
        "UNIQUE (atome_reference)",
        "An order with this Atome reference already exists.",
    )
