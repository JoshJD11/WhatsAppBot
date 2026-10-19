import asyncio
import json

import httpx

from bot.whatsapp import WhatsAppClient, parse_messages, parse_owner_replies, verify_signature

from .conftest import APP_SECRET, CUSTOMER, PHONE_NUMBER_ID, echo_payload, sign, webhook_payload


def test_verify_signature_accepts_valid_signature():
    body = b'{"a": 1}'
    assert verify_signature(APP_SECRET, body, sign(body))


def test_verify_signature_rejects_tampered_body_wrong_secret_and_missing_header():
    body = b'{"a": 1}'
    assert not verify_signature(APP_SECRET, b'{"a": 2}', sign(body))
    assert not verify_signature(APP_SECRET, body, sign(body, "other-secret"))
    assert not verify_signature(APP_SECRET, body, None)
    assert not verify_signature(APP_SECRET, body, "md5=abc")


def test_parse_messages_extracts_text_message():
    [message] = parse_messages(webhook_payload(text="Hola"))
    assert message.sender == CUSTOMER
    assert message.text == "Hola"
    assert message.name == "Cliente Prueba"
    assert message.phone_number_id == PHONE_NUMBER_ID


def test_parse_messages_keeps_media_with_empty_text():
    [message] = parse_messages(webhook_payload(kind="image"))
    assert message.type == "image"
    assert message.text == ""


def test_parse_messages_reads_button_and_interactive_titles():
    payload = webhook_payload()
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message.update(type="interactive", interactive={"type": "button_reply", "button_reply": {"title": "Sí"}})
    assert parse_messages(payload)[0].text == "Sí"
    message.update(type="button", button={"text": "Ver"})
    assert parse_messages(payload)[0].text == "Ver"


def test_parse_messages_ignores_reactions_statuses_and_echoes():
    reaction = webhook_payload()
    reaction["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "reaction"
    assert parse_messages(reaction) == []

    status = webhook_payload()
    value = status["entry"][0]["changes"][0]["value"]
    value["statuses"] = [{"id": "wamid.1", "status": "read"}]
    del value["messages"]
    assert parse_messages(status) == []

    echo = webhook_payload()
    echo["entry"][0]["changes"][0]["field"] = "smb_message_echoes"
    assert parse_messages(echo) == []


def test_parse_messages_ignores_other_objects_and_malformed_payloads():
    assert parse_messages({"object": "page"}) == []
    assert parse_messages({"object": "whatsapp_business_account", "entry": None}) == []


def _client(handler) -> tuple[WhatsAppClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WhatsAppClient("token", "999", "v26.0", http), http


def test_send_text_posts_sanitized_text_message():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.x"}]})

    async def scenario():
        client, http = _client(handler)
        async with http:
            return await client.send_text("50688887777", "Hola 😊 -- listo")

    assert asyncio.run(scenario()) is True
    request = requests[0]
    assert str(request.url) == "https://graph.facebook.com/v26.0/999/messages"
    assert request.headers["Authorization"] == "Bearer token"
    body = json.loads(request.content)
    assert body["to"] == "50688887777"
    assert body["type"] == "text"
    assert body["text"]["body"] == "Hola - listo"


def test_send_text_returns_false_on_api_error_and_network_error():
    async def scenario(handler):
        client, http = _client(handler)
        async with http:
            return await client.send_text("1", "hola")

    assert asyncio.run(scenario(lambda request: httpx.Response(400, json={"error": {}}))) is False

    def broken(request):
        raise httpx.ConnectError("down")

    assert asyncio.run(scenario(broken)) is False


def test_send_text_skips_empty_messages():
    def handler(request):
        raise AssertionError("should not send")

    async def scenario():
        client, http = _client(handler)
        async with http:
            return await client.send_text("1", "😊")

    assert asyncio.run(scenario()) is False


def test_parse_owner_replies_reads_message_echoes():
    [reply] = parse_owner_replies(echo_payload(customer=CUSTOMER, message_id="echo-1"))
    assert reply.customer == CUSTOMER
    assert reply.message_id == "echo-1"
    assert reply.phone_number_id == PHONE_NUMBER_ID


def test_parse_owner_replies_ignores_customer_messages_and_incomplete_echoes():
    assert parse_owner_replies(webhook_payload()) == []
    payload = echo_payload()
    del payload["entry"][0]["changes"][0]["value"]["message_echoes"][0]["to"]
    assert parse_owner_replies(payload) == []
    assert parse_owner_replies({"object": "page"}) == []

