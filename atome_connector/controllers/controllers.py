# from odoo import http


# class AtomeConnector(http.Controller):
#     @http.route('/atome_connector/atome_connector', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/atome_connector/atome_connector/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('atome_connector.listing', {
#             'root': '/atome_connector/atome_connector',
#             'objects': http.request.env['atome_connector.atome_connector'].search([]),
#         })

#     @http.route('/atome_connector/atome_connector/objects/<model("atome_connector.atome_connector"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('atome_connector.object', {
#             'object': obj
#         })

