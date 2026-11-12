# atome-odoo

Odoo 19 add-ons for Atome Manufacturing.

## Modules

- `atome_connector`: Atome reference on sales orders, one product per door category, and a REST API for creating draft quotations.

## Install

1. Add this folder to `addons_path` in `odoo.conf`:
   ```
   addons_path = <odoo>/server/odoo/addons,D:\news\atome-odoo
   ```
2. Restart Odoo.
3. Open `/odoo?debug=1`, then Apps → Update Apps List, and install (or upgrade) **Atome Connector**.

## API

Base path `/atome/api/v1`. Send `Authorization: Bearer <Odoo API key>` and `X-Odoo-Database: <db>`.

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET | `/health` | Status (no key needed) |
| GET | `/products` | Sellable products (`?category=`, `?q=`) |
| POST | `/quotations` | Create a draft quotation, in one transaction, idempotent on `atome_reference` |
| GET | `/quotations` | List, newest first (`?limit=`, `?cursor=`) |
| GET | `/quotations/<atome_reference>` | One quotation |

Responses use the same envelope as the Atome app (`http_status_code`, `status_code`, `status`, `status_message`, `message`, `code`, `requestId`, optional `data`), real HTTP status codes, and `data.fields` for validation errors. Try every request in `api.http` (PyCharm HTTP client).

## Develop

```bash
python odoo-bin -c odoo.conf -d <database> -u atome_connector --dev=all
```

Run the tests in a throwaway database:

```bash
python odoo-bin -c odoo.conf -d <test_db> -i atome_connector --test-enable --test-tags /atome_connector --stop-after-init
```

Requires Odoo 19 with the Sales app. License: LGPL-3.
