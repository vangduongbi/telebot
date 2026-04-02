import json
import urllib.error
import urllib.parse
import urllib.request

from capcut_api import CapcutApiError, _ps_single_quote, _resolve_powershell_executable
from supplier_api import SupplierApiError


PROTOCOL_DEFAULTS = {
    "sumistore": {
        "balance_path": "/tele-balance",
        "buy_path": "/tele-product/buy",
        "product_detail_path_template": "/tele-products/{product_id}",
        "auth_header": "X-Tele-API-ID",
        "auth_query_param": None,
        "buy_product_id_field": "id",
        "buy_quantity_field": "quantity",
    },
    "node_api": {
        "products_path": "/products",
        "balance_path": "/balance",
        "buy_path": "/buy",
        "auth_header": "X-API-Key",
        "auth_query_param": None,
        "buy_product_id_field": "product_id",
        "buy_quantity_field": "quantity",
    },
}


def _row_value(row, key, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            value = row[key]
            return default if value is None else value
    except AttributeError:
        pass
    if isinstance(row, dict):
        value = row.get(key, default)
        return default if value is None else value
    return default


def _error_type_for_protocol(protocol):
    return SupplierApiError if protocol == "sumistore" else CapcutApiError


def resolve_provider_config(provider_row):
    protocol = str(_row_value(provider_row, "protocol", "")).strip()
    if protocol not in PROTOCOL_DEFAULTS:
        raise ValueError("Unsupported provider protocol")

    raw_overrides = str(_row_value(provider_row, "overrides_json", "{}")).strip() or "{}"
    overrides = json.loads(raw_overrides)
    if not isinstance(overrides, dict):
        raise ValueError("Invalid provider overrides")

    resolved = dict(PROTOCOL_DEFAULTS[protocol])
    resolved.update(overrides)
    resolved.update(
        {
            "code": str(_row_value(provider_row, "code", "")).strip(),
            "name": str(_row_value(provider_row, "name", "")).strip(),
            "protocol": protocol,
            "base_url": str(_row_value(provider_row, "base_url", "")).rstrip("/"),
            "api_key": str(_row_value(provider_row, "api_key", "")).strip(),
            "is_active": int(_row_value(provider_row, "is_active", 0) or 0),
        }
    )
    return resolved


class ConfiguredSupplierHttpClient:
    def __init__(self, resolved_config, timeout=10):
        self.config = dict(resolved_config or {})
        self.timeout = timeout

    def _build_url(self, path):
        url = f"{self.config['base_url']}{path}"
        query_param = self.config.get("auth_query_param")
        api_key = self.config.get("api_key")
        if query_param and api_key:
            parts = urllib.parse.urlsplit(url)
            query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            query.append((str(query_param), str(api_key)))
            url = urllib.parse.urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment)
            )
        return url

    def _build_powershell_script(self, method, path, body=None):
        method = str(method).title()
        url = _ps_single_quote(self._build_url(path))
        lines = ["$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()"]
        auth_header = self.config.get("auth_header")
        api_key = self.config.get("api_key")
        if auth_header and api_key:
            lines.append(f"$headers = @{{'{_ps_single_quote(auth_header)}'='{_ps_single_quote(api_key)}'}}")
            headers_expr = "-Headers $headers"
        else:
            headers_expr = ""
        if body is None:
            lines.append(
                f"$response = Invoke-RestMethod -Method {method} -Uri '{url}' {headers_expr}".rstrip()
            )
        else:
            body_json = _ps_single_quote(json.dumps(body, separators=(",", ":")))
            lines.append(
                (
                    f"$response = Invoke-RestMethod -Method {method} -Uri '{url}' {headers_expr} "
                    f"-ContentType 'application/json' -Body '{body_json}'"
                ).rstrip()
            )
        lines.append("$response | ConvertTo-Json -Depth 20 -Compress")
        return "; ".join(lines)

    def request_json(self, method, path, body=None):
        powershell = _resolve_powershell_executable()
        if powershell:
            import subprocess

            completed = subprocess.run(
                args=[powershell, "-NoProfile", "-Command", self._build_powershell_script(method, path, body)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Supplier request failed")
            payload = completed.stdout
        else:
            url = self._build_url(path)
            headers = {}
            auth_header = self.config.get("auth_header")
            api_key = self.config.get("api_key")
            if auth_header and api_key:
                headers[str(auth_header)] = str(api_key)
            data = None
            if body is not None:
                data = json.dumps(body, separators=(",", ":")).encode("utf-8")
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(url, data=data, headers=headers, method=str(method).upper())
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = response.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                message = exc.read().decode("utf-8", errors="replace").strip() or str(exc)
                raise RuntimeError(message) from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(str(exc.reason or exc)) from exc

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Invalid supplier response") from exc
        if not data.get("success", True):
            raise RuntimeError(data.get("message") or data.get("code") or "Supplier request failed")
        return data


class SupplierRuntime:
    def __init__(self, provider_row, request_json=None, timeout=10):
        self.config = resolve_provider_config(provider_row)
        self._request_json = request_json or ConfiguredSupplierHttpClient(self.config, timeout=timeout).request_json
        self._error_type = _error_type_for_protocol(self.config["protocol"])

    def _raise(self, message):
        raise self._error_type(message)

    def _get_sumistore_product_detail(self, product_id):
        path = self.config["product_detail_path_template"].format(product_id=urllib.parse.quote(str(product_id), safe=""))
        return self._request_json("GET", path)

    def _get_node_product(self, product_id):
        products_response = self._request_json("GET", self.config["products_path"])
        for product in products_response.get("products") or []:
            if str(product.get("id") or "").strip() == str(product_id or "").strip():
                return product
        self._raise("Supplier product is unavailable")

    def get_product_detail(self, product_id):
        if self.config["protocol"] == "sumistore":
            return self._get_sumistore_product_detail(product_id)
        return self._get_node_product(product_id)

    def get_balance(self):
        return self._request_json("GET", self.config["balance_path"])

    def get_unit_price(self, product_detail):
        if self.config["protocol"] == "sumistore":
            product = (product_detail or {}).get("product") or {}
            for key in ("sale_price", "special_price", "price", "base_price"):
                value = product.get(key)
                if value is not None:
                    price = int(value)
                    if price > 0:
                        return price
            self._raise("Supplier product price is unavailable")

        value = (product_detail or {}).get("price")
        if value is None:
            self._raise("Supplier product price is unavailable")
        price = int(value)
        if price <= 0:
            self._raise("Supplier product price is invalid")
        return price

    def get_available_units(self, product_id):
        if not product_id:
            return 0
        try:
            product_detail = self.get_product_detail(product_id)
            balance_response = self.get_balance()
            unit_price = self.get_unit_price(product_detail)
            balance_units = max(int(balance_response.get("balance") or 0) // unit_price, 0)
            if self.config["protocol"] == "sumistore":
                return balance_units
            api_stock = max(int(product_detail.get("stock") or 0), 0)
            return min(balance_units, api_stock)
        except Exception:
            return 0

    def check_purchase_ready(self, product_id, quantity):
        qty = int(quantity)
        if qty <= 0:
            self._raise("Invalid quantity")
        product_detail = self.get_product_detail(product_id)
        unit_price = self.get_unit_price(product_detail)
        balance_response = self.get_balance()
        balance = int(balance_response.get("balance") or 0)
        if self.config["protocol"] == "sumistore":
            product = (product_detail or {}).get("product") or {}
            if not product.get("api_enabled"):
                self._raise("Supplier product is temporarily unavailable")
            if int(product.get("stock") or 0) < qty:
                self._raise("Supplier stock is not enough")
        else:
            if int(product_detail.get("stock") or 0) < qty:
                self._raise("Supplier stock is not enough")
        if balance < unit_price * qty:
            self._raise("Supplier balance is not enough")
        return product_detail

    def buy_product(self, product_id, quantity):
        body = {
            self.config["buy_product_id_field"]: product_id,
            self.config["buy_quantity_field"]: int(quantity),
        }
        return self._request_json("POST", self.config["buy_path"], body)

    def extract_delivered_accounts(self, purchase_response):
        if self.config["protocol"] == "sumistore":
            raw_accounts = purchase_response.get("raw_accounts")
            if isinstance(raw_accounts, list):
                accounts = [str(item).strip() for item in raw_accounts if str(item).strip()]
                if accounts:
                    return accounts
            if isinstance(raw_accounts, str) and raw_accounts.strip():
                return [raw_accounts.strip()]
            accounts = []
            for row in purchase_response.get("accounts") or []:
                if isinstance(row, dict):
                    if row.get("raw"):
                        accounts.append(str(row["raw"]).strip())
                    else:
                        accounts.append(" | ".join(str(value).strip() for value in row.values()))
                elif str(row).strip():
                    accounts.append(str(row).strip())
            return [account for account in accounts if account]

        order = (purchase_response or {}).get("order") or {}
        accounts = []
        for row in order.get("accounts") or []:
            if isinstance(row, dict):
                accounts.append(" | ".join(str(value).strip() for value in row.values()))
            elif str(row).strip():
                accounts.append(str(row).strip())
        return [account for account in accounts if account]
