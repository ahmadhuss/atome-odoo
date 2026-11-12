from odoo import fields, models

DOOR_CATEGORIES = [
    ("FIRE_RATED", "Fire-rated door"),
    ("SMOKE_RATED", "Smoke-rated door"),
    ("STANDARD", "Standard door"),
    ("OTHER", "Other door"),
]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    atome_door_category = fields.Selection(
        DOOR_CATEGORIES,
        string="Atome Door Category",
        index=True,
        help="Atome quotation lines of this category use this product when no product is given explicitly.",
    )
