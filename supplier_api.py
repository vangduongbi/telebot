import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request


class SupplierApiError(Exception):
    pass


def _ps_single_quote(value):
    return str(value).replace("'", "''")


def _resolve_powershell_executable():
    for candidate in ("powershell", "powershell.exe", "pwsh"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    fallback = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if os.path.exists(fallback):
        return fallback
    return None


class SupplierApiClient:
    def __init__(self, base_url, api_key, timeout=10):
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.timeout = timeout
        if not self.base_url or not self.api_key:
            raise SupplierApiError("Supplier API is not configured")

    def _build_powershell_script(self, method, path, body=None):
        method = str(method).title()
        url = _ps_single_quote(f"{self.base_url}{path}")
        api_key = _ps_single_quote(self.api_key)
        lines = [
            "$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()",
            f"$headers = @{{'X-Tele-API-ID'='{api_key}'}}",
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
        powershell = _resolve_powershell_executable()
        if not powershell:
            return self._request_json_via_urllib(method, path, body)

        command = [
            powershell,
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
            message = completed.stderr.strip() or completed.stdout.strip() or "Supplier request failed"
            raise SupplierApiError(message)

        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SupplierApiError("Invalid supplier response") from exc

        if not data.get("success"):
            raise SupplierApiError(data.get("message") or data.get("code") or "Supplier request failed")
        return data

    def _request_json_via_urllib(self, method, path, body=None):
        url = f"{self.base_url}{path}"
        data = None
        headers = {"X-Tele-API-ID": self.api_key}
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=str(method).upper())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace").strip() or str(exc)
            raise SupplierApiError(message) from exc
        except urllib.error.URLError as exc:
            raise SupplierApiError(str(exc.reason or exc)) from exc

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SupplierApiError("Invalid supplier response") from exc

        if not data.get("success"):
            raise SupplierApiError(data.get("message") or data.get("code") or "Supplier request failed")
        return data

    def get_balance(self):
        return self._request_json("GET", "/tele-balance")

    def get_product_detail(self, product_id):
        return self._request_json("GET", f"/tele-products/{product_id}")

    def buy_product(self, product_id, quantity):
        return self._request_json(
            "POST",
            "/tele-product/buy",
            {"id": product_id, "quantity": int(quantity)},
        )
