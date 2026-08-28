"""Pure tests for the Evolution API v2 client contract helpers."""

import pytest

from app.modules.whatsapp_evolution import client


def test_normalize_base_url_accepts_self_hosted_lan():
    assert client.normalize_base_url("http://192.168.1.20:8080/") == "http://192.168.1.20:8080"


@pytest.mark.parametrize(
    "value",
    [
        "evolution.local:8080",
        "ftp://evolution.local",
        "https://user:pass@example.test",
        "https://example.test/?token=secret",
    ],
)
def test_normalize_base_url_rejects_unsafe_shapes(value):
    with pytest.raises(ValueError):
        client.normalize_base_url(value)


def test_normalize_phone_number_strips_formatting_and_jid():
    assert client.normalize_phone_number("+34 600 111 222@s.whatsapp.net") == "34600111222"


def test_normalize_phone_number_rejects_group_and_invalid_length():
    with pytest.raises(ValueError):
        client.normalize_phone_number("120363000000000000@g.us")
    with pytest.raises(ValueError):
        client.normalize_phone_number("123")


def test_provider_message_id_uses_evolution_key_id():
    assert client.provider_message_id({"key": {"id": "ABC123"}}) == "ABC123"
    assert client.provider_message_id({"key": {}}) is None


def test_connection_state_is_normalized():
    assert client.connection_state({"instance": {"state": "OPEN"}}) == "open"
