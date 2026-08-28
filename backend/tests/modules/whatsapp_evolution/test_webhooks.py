"""Pure Evolution webhook mapping tests."""

from app.modules.whatsapp_evolution import webhooks


def test_messages_update_maps_numeric_delivery_statuses():
    payload = {
        "data": [
            {"key": {"id": "m1"}, "update": {"status": 3}},
            {"key": {"id": "m2"}, "update": {"status": 4}},
            {"key": {"id": "m3"}, "update": {"status": 1}},
        ]
    }
    assert webhooks.delivery_updates(payload) == [
        webhooks.DeliveryUpdate("m1", "delivered"),
        webhooks.DeliveryUpdate("m2", "read"),
    ]


def test_messages_update_maps_string_failures():
    payload = {"data": {"messageId": "m9", "status": "FAILED"}}
    assert webhooks.delivery_updates(payload) == [webhooks.DeliveryUpdate("m9", "failed")]


def test_messages_upsert_extracts_only_individual_inbound_text():
    payload = {
        "data": [
            {
                "key": {"id": "in1", "remoteJid": "34600111222@s.whatsapp.net", "fromMe": False},
                "message": {"conversation": "Hola"},
            },
            {
                "key": {"id": "mine", "remoteJid": "34600111222@s.whatsapp.net", "fromMe": True},
                "message": {"conversation": "ignore"},
            },
            {
                "key": {"id": "group", "remoteJid": "120363000000@g.us", "fromMe": False},
                "message": {"conversation": "ignore"},
            },
        ]
    }
    assert webhooks.inbound_texts(payload) == [
        webhooks.InboundText("in1", "34600111222", "Hola")
    ]


def test_messages_upsert_uses_phone_alt_for_lid():
    payload = {
        "data": {
            "key": {
                "id": "lid1",
                "remoteJid": "219743428550712@lid",
                "remoteJidAlt": "34600111222@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {"conversation": "Hola desde LID"},
        }
    }
    assert webhooks.inbound_texts(payload) == [
        webhooks.InboundText("lid1", "34600111222", "Hola desde LID")
    ]


def test_messages_upsert_ignores_unresolved_lid_instead_of_treating_it_as_phone():
    payload = {
        "data": {
            "key": {
                "id": "lid2",
                "remoteJid": "219743428550712@lid",
                "fromMe": False,
            },
            "message": {"conversation": "No phone mapping"},
        }
    }
    assert webhooks.inbound_texts(payload) == []


def test_event_and_instance_normalization():
    assert webhooks.normalize_event_name("MESSAGES_UPDATE") == "messages.update"
    assert webhooks.payload_instance({"instance": "clinic-a"}) == "clinic-a"
    assert webhooks.connection_update_state({"data": {"state": "OPEN"}}) == "open"
