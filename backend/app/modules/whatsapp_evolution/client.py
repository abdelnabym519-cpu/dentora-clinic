"""Small, provider-specific Evolution API v2 HTTP client.

Only Infrastructure code knows provider URLs/payloads. Errors are deliberately
sanitized: response bodies, API keys, phone numbers and message content are not
copied into exception messages or logs.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

_TIMEOUT = 30.0
_RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


class EvolutionApiError(Exception):
    """Safe Evolution provider failure suitable for persistence/logging."""

    def __init__(self, code: str, *, status_code: int | None = None, retryable: bool = False):
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        suffix = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(f"Evolution API {code}{suffix}")


def normalize_base_url(value: str) -> str:
    """Validate a configured self-hosted endpoint without forbidding private LANs."""
    raw = (value or "").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Evolution API URL must be an absolute http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Evolution API URL must not contain credentials, query, or fragment")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def normalize_phone_number(value: str) -> str:
    """Return a WhatsApp individual destination in international digits-only form."""
    raw = (value or "").strip()
    if "@g.us" in raw:
        raise ValueError("Group destinations are not supported")
    raw = raw.split("@", 1)[0]
    digits = re.sub(r"\D", "", raw)
    if not 8 <= len(digits) <= 15:
        raise ValueError("Invalid WhatsApp destination")
    return digits


def text_payload(number: str, text: str) -> dict:
    """Build the Evolution API v2 SendTextDto payload."""
    return {"number": normalize_phone_number(number), "text": text}


def webhook_payload(webhook_url: str, webhook_token: str) -> dict:
    """Build the Evolution API v2 webhook configuration envelope."""
    return {
        "webhook": {
            "enabled": True,
            "url": webhook_url,
            "events": ["MESSAGES_UPSERT", "MESSAGES_UPDATE", "CONNECTION_UPDATE"],
            "headers": {"X-Dentora-Webhook-Token": webhook_token},
            "byEvents": False,
            "base64": False,
        }
    }


async def _request(
    method: str,
    base_url: str,
    api_key: str,
    path: str,
    *,
    payload: dict | None = None,
) -> dict:
    url = f"{normalize_base_url(base_url)}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            response = await http.request(
                method,
                url,
                headers={"apikey": api_key, "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise EvolutionApiError("timeout", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise EvolutionApiError("transport_error", retryable=True) from exc

    if response.status_code >= 400:
        raise EvolutionApiError(
            "request_failed",
            status_code=response.status_code,
            retryable=response.status_code in _RETRYABLE_HTTP,
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise EvolutionApiError("invalid_json_response", retryable=False) from exc
    if not isinstance(data, dict):
        raise EvolutionApiError("invalid_response_shape", retryable=False)
    return data


async def send_text(
    base_url: str,
    api_key: str,
    instance_name: str,
    number: str,
    text: str,
) -> dict:
    instance = quote(instance_name, safe="")
    return await _request(
        "POST",
        base_url,
        api_key,
        f"/message/sendText/{instance}",
        payload=text_payload(number, text),
    )


async def send_media(
    base_url: str,
    api_key: str,
    instance_name: str,
    *,
    number: str,
    media_type: str,
    mimetype: str,
    media: str,
    file_name: str,
    caption: str = "",
) -> dict:
    """Send a URL/base64 media payload using the Evolution v2 media contract."""
    if media_type not in {"image", "video", "audio", "document"}:
        raise ValueError("Unsupported Evolution media type")
    payload = {
        "number": normalize_phone_number(number),
        "mediatype": media_type,
        "mimetype": mimetype,
        "media": media,
        "fileName": file_name,
        "caption": caption,
    }
    instance = quote(instance_name, safe="")
    return await _request(
        "POST", base_url, api_key, f"/message/sendMedia/{instance}", payload=payload
    )


async def get_connection_state(base_url: str, api_key: str, instance_name: str) -> dict:
    instance = quote(instance_name, safe="")
    return await _request("GET", base_url, api_key, f"/instance/connectionState/{instance}")


async def set_webhook(
    base_url: str,
    api_key: str,
    instance_name: str,
    *,
    webhook_url: str,
    webhook_token: str,
) -> dict:
    """Configure only the events Dentora consumes, with a static secret header."""
    instance = quote(instance_name, safe="")
    return await _request(
        "POST",
        base_url,
        api_key,
        f"/webhook/set/{instance}",
        payload=webhook_payload(webhook_url, webhook_token),
    )


def provider_message_id(response: dict) -> str | None:
    key = response.get("key")
    if isinstance(key, dict):
        value = key.get("id")
        return str(value) if value else None
    return None


def connection_state(response: dict) -> str | None:
    instance = response.get("instance")
    if isinstance(instance, dict):
        value = instance.get("state")
        return str(value).lower() if value is not None else None
    return None
