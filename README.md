# atome-odoo

Odoo 19 add-ons for Atome Manufacturing.

## Modules

- `atome_connector`: skeleton for now. It installs but adds no features yet.

## Install

1. Add this folder to `addons_path` in `odoo.conf`:
   ```
   addons_path = <odoo>/server/odoo/addons,D:\news\atome-odoo
   ```
2. Restart Odoo.
3. Open `/odoo?debug=1`, then Apps → Update Apps List, and install **Atome Connector**.

## Develop

```bash
python odoo-bin -c odoo.conf -d <database> -u atome_connector --dev=all
```

Requires Odoo 19 with the Sales app. License: LGPL-3.
