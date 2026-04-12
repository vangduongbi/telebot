import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request


class CapcutApiError(Exception):
    pass


def _api_debug_enabled():
    return str(os.environ.get("API_DEBUG") or "").strip() == "1"


def _mask_secret(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return f"{text[:2]}...{text[-2:]}"
    return f"{text[:4]}...{text[-4:]}"


def _is_sensitive_debug_key(key):
    normalized = "".join(ch for ch in str(key or "").lower() if ch.isalnum())
    sensitive_tokens = ("apikey", "authorization", "token", "password", "passwd", "secret")
    return any(token in normalized for token in sensitive_tokens)


def _sanitize_debug_value(value, key_hint=None):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if _is_sensitive_debug_key(key):
                sanitized[key] = _mask_secret(item)
            else:
                sanitized[key] = _sanitize_debug_value(item, key)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_debug_value(item, key_hint) for item in value]
    if _is_sensitive_debug_key(key_hint):
        return _mask_secret(value)
    return value


def _render_debug_value(key, value, limit=1000):
    sanitized = _sanitize_debug_value(value, key)
    if isinstance(sanitized, (dict, list)):
        rendered = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    else:
        rendered = str(sanitized)
    if limit and len(rendered) > limit:
        return f"{rendered[:limit]}...(truncated)"
    return rendered


def _debug_print(prefix, **fields):
    if not _api_debug_enabled():
        return
    parts = [prefix]
    for key, value in fields.items():
        if value is None:
            continue
        rendered = _render_debug_value(key, value)
        parts.append(f"{key}={rendered}")
    print(" ".join(parts))


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
        powershell = _resolve_powershell_executable()
        if not powershell:
            return self._request_json_via_urllib(method, path, body)

        url = f"{self.base_url}{path}"
        command = [
            powershell,
            "-NoProfile",
            "-Command",
            self._build_powershell_script(method, path, body),
        ]
        _debug_print(
            "[CapcutApiClient] request",
            transport="powershell",
            method=str(method).upper(),
            url=url,
            headers={"X-API-Key": _mask_secret(self.api_key)},
            body=body,
            command=" ".join(command).replace(self.api_key, _mask_secret(self.api_key)),
        )
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
            _debug_print("[CapcutApiClient] error", method=str(method).upper(), url=url, message=message)
            raise CapcutApiError(message)

        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            _debug_print(
                "[CapcutApiClient] error",
                method=str(method).upper(),
                url=url,
                message="Invalid CapCut API response",
                response_preview=completed.stdout[:500],
            )
            raise CapcutApiError("Invalid CapCut API response") from exc

        if not data.get("success"):
            _debug_print(
                "[CapcutApiClient] error",
                method=str(method).upper(),
                url=url,
                message=data.get("message") or data.get("code") or "CapCut request failed",
                response=data,
            )
            raise CapcutApiError(data.get("message") or data.get("code") or "CapCut request failed")
        _debug_print(
            "[CapcutApiClient] response",
            method=str(method).upper(),
            url=url,
            success=data.get("success"),
            keys=sorted(data.keys()),
            response=data,
        )
        return data

    def _request_json_via_urllib(self, method, path, body=None):
        url = f"{self.base_url}{path}"
        data = None
        headers = {"X-API-Key": self.api_key}
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        _debug_print(
            "[CapcutApiClient] request",
            transport="urllib",
            method=str(method).upper(),
            url=url,
            headers={key: _mask_secret(value) if key.lower() == "x-api-key" else value for key, value in headers.items()},
            body=body,
        )
        request = urllib.request.Request(url, data=data, headers=headers, method=str(method).upper())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace").strip() or str(exc)
            _debug_print("[CapcutApiClient] error", method=str(method).upper(), url=url, message=message)
            raise CapcutApiError(message) from exc
        except urllib.error.URLError as exc:
            _debug_print("[CapcutApiClient] error", method=str(method).upper(), url=url, message=str(exc.reason or exc))
            raise CapcutApiError(str(exc.reason or exc)) from exc

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            _debug_print(
                "[CapcutApiClient] error",
                method=str(method).upper(),
                url=url,
                message="Invalid CapCut API response",
                response_preview=payload[:500],
            )
            raise CapcutApiError("Invalid CapCut API response") from exc

        if not data.get("success"):
            _debug_print(
                "[CapcutApiClient] error",
                method=str(method).upper(),
                url=url,
                message=data.get("message") or data.get("code") or "CapCut request failed",
                response=data,
            )
            raise CapcutApiError(data.get("message") or data.get("code") or "CapCut request failed")
        _debug_print(
            "[CapcutApiClient] response",
            method=str(method).upper(),
            url=url,
            success=data.get("success"),
            keys=sorted(data.keys()),
            response=data,
        )
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
