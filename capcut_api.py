import json
import subprocess


class CapcutApiError(Exception):
    pass


def _ps_single_quote(value):
    return str(value).replace("'", "''")


class CapcutApiClient:
    def __init__(self, base_url, api_key, timeout=10):
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.timeout = timeout
        if not self.base_url or not self.api_key:
            raise CapcutApiError("CapCut API is not configured")

    def _build_powershell_script(self, method, path, body=None):
        method = str(method).title()
        url = _ps_single_quote(f"{self.base_url}{path}")
        api_key = _ps_single_quote(self.api_key)
        lines = [
            "$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()",
            f"$headers = @{{'X-API-Key'='{api_key}'}}",
        ]
        if body is None:
            lines.append(
                f"$response = Invoke-RestMethod -Method {method} -Uri '{url}' -Headers $headers"
            )
        else:
            body_json = _ps_single_quote(json.dumps(body, separators=(",", ":")))
            lines.append(
                f"$response = Invoke-RestMethod -Method {method} -Uri '{url}' -Headers $headers -ContentType 'application/json' -Body '{body_json}'"
            )
        lines.append("$response | ConvertTo-Json -Depth 20 -Compress")
        return "; ".join(lines)

    def _request_json(self, method, path, body=None):
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            self._build_powershell_script(method, path, body),
        ]
        completed = subprocess.run(
            args=command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "CapCut request failed"
            raise CapcutApiError(message)

        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise CapcutApiError("Invalid CapCut API response") from exc

        if not data.get("success"):
            raise CapcutApiError(data.get("message") or data.get("code") or "CapCut request failed")
        return data

    def get_products(self):
        return self._request_json("GET", "/products")

    def get_balance(self):
        return self._request_json("GET", "/balance")

    def buy_product(self, product_id, quantity):
        return self._request_json(
            "POST",
            "/buy",
            {"product_id": product_id, "quantity": int(quantity)},
        )
