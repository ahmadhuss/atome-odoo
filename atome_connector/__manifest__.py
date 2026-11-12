{
    'name': "Atome Connector",

    'summary': "Connects Atome Manufacturing quotations to Odoo sales orders.",

    'description': """
Atome Connector
===============
Adds the integration points Atome Manufacturing needs in Odoo:

* an Atome reference on sales orders
* creation of draft quotations from Atome in a single transaction
    """,

    'author': "Atome Manufacturing",
    'website': "https://github.com/ahmadhuss/atome-odoo",

    'category': 'Sales',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',

    # Modules that must be installed first
    'depends': ['sale'],

    # Files loaded on install/upgrade (every listed file must exist)
    'data': [
        'views/sale_order_views.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
