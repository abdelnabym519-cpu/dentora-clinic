"""Pure Evolution webhook parsing helpers.

The provider has emitted more than one payload shape across integrations and
versions. These helpers accept the documented v2 shapes without trusting any
clinic/tenant identifier from the payload; tenant resolution happens from the
configured instance on the webhook route.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeliveryUpdate:
    message_id: str
    status: str


@dataclass(frozen=True)
class InboundText:
    message_id: str
    phone: str
    body: str


def normalize_event_name(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", ".")


def _items(data: Any) -> list[dict]:
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _map_status(value: Any) -> str | None:
    # Baileys WebMessageInfo.Status: 0 error, 1 pending, 2 server ack,
    # 3 delivery ack, 4 read, 5 played. Pending is deliberately ignored.
    if isinstance(value, int):
        return {0: "failed", 2: "sent", 3: "delivered", 4: "read", 5: "read"}.get(value)
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return {
        "error": "failed",
        "failed": "failed",
        "failure": "failed",
        "sent": "sent",
        "server_ack": "sent",
        "delivered": "delivered",
        "delivery_ack": "delivered",
        "read": "read",
        "played": "read",
    }.get(raw)


def delivery_updates(payload: dict) -> list[DeliveryUpdate]:
    updates: list[DeliveryUpdate] = []
    for item in _items(payload.get("data")):
        key = item.get("key") if isinstance(item.get("key"), dict) else {}
        update = item.get("update") if isinstance(item.get("update"), dict) else {}
        message_id = item.get("messageId") or item.get("keyId") or key.get("id")
        status = _map_status(item.get("status", update.get("status")))
        if message_id and status:
            updates.append(DeliveryUpdate(str(message_id), status))
    return updates


def _text_body(message: Any) -> str | None:
    if not isinstance(message, dict):
        return None
    if isinstance(message.get("conversation"), str):
        return message["conversation"]
    extended = message.get("extendedTextMessage")
    if isinstance(extended, dict) and isinstance(extended.get("text"), str):
        return extended["text"]
    return None


def inbound_texts(payload: dict) -> list[InboundText]:
    rows: list[InboundText] = []
    for item in _items(payload.get("data")):
        key = item.get("key") if isinstance(item.get("key"), dict) else {}
        if key.get("fromMe") is True:
            continue
        remote = str(key.get("remoteJid") or item.get("remoteJid") or "")
        if not remote or remote.endswith("@g.us"):
            continue
        message_id = key.get("id") or item.get("messageId")
        body = _text_body(item.get("message"))
        phone = remote.split("@", 1)[0]
        if message_id and phone and body:
            rows.append(InboundText(str(message_id), phone, body))
    return rows


def payload_instance(payload: dict) -> str | None:
    value = payload.get("instance") or payload.get("instanceName")
    if isinstance(value, dict):
        value = value.get("instanceName")
    return str(value) if value else None


def connection_update_state(payload: dict) -> str | None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    value = data.get("state") or data.get("status")
    return str(value).lower() if value is not None else None
