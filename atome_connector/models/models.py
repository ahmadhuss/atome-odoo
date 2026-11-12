# from odoo import models, fields, api


# class atome_connector(models.Model):
#     _name = 'atome_connector.atome_connector'
#     _description = 'atome_connector.atome_connector'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100

