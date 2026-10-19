import json

import pytest
from fastapi.testclient import TestClient

from bot.excel_store import LocalExcelStore
from bot.main import MAX_BODY_BYTES, _make_provider, _make_store, build_services, create_app
from bot.state import StateFile

from .conftest import (
    CUSTOMER,
    VERIFY_TOKEN,
    FakeSender,
    MemoryStore,
    echo_payload,
    make_settings,
    sign,
    webhook_payload,
)


@pytest.fixture
def setup(workbook_bytes):
    sender = FakeSender()
    services = build_services(make_settings(), sender, MemoryStore(workbook_bytes), None)
    with TestClient(create_app(services)) as client:
        yield client, sender, services


def _post(client, payload, signature=None):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature or sign(body)},
    )


def test_health(setup):
    client, _, _ = setup
    assert client.get("/health").json() == {"status": "ok"}


def test_startup_loads_the_excel(setup):
    _, _, services = setup
    assert services.workbook.knowledge.loaded


def test_verification_handshake_returns_challenge(setup):
    client, _, _ = setup
    response = client.get(
        "/webhook", params={"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "12345"}
    )
    assert response.status_code == 200
    assert response.text == "12345"


@pytest.mark.parametrize(
    "params",
    [
        {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
        {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1"},
        {},
    ],
)
def test_verification_handshake_rejects_bad_requests(setup, params):
    client, _, _ = setup
    assert client.get("/webhook", params=params).status_code == 403


def test_signed_message_is_answered(setup):
    client, sender, _ = setup
    response = _post(client, webhook_payload(text="hola"))
    assert response.status_code == 200
    assert sender.texts_to(CUSTOMER)


def test_invalid_signature_is_rejected_and_not_processed(setup):
    client, sender, _ = setup
    response = _post(client, webhook_payload(), signature="sha256=" + "0" * 64)
    assert response.status_code == 403
    assert sender.sent == []


def test_missing_signature_is_rejected(setup):
    client, _, _ = setup
    response = client.post("/webhook", content=b"{}", headers={"Content-Type": "application/json"})
    assert response.status_code == 403


def test_invalid_json_with_valid_signature_returns_400(setup):
    client, _, _ = setup
    body = b"not json"
    response = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sign(body)})
    assert response.status_code == 400


def test_oversized_body_is_rejected(setup):
    client, _, _ = setup
    body = b"x" * (MAX_BODY_BYTES + 1)
    response = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sign(body)})
    assert response.status_code == 413


def test_status_only_payload_is_accepted_without_reply(setup):
    client, sender, _ = setup
    payload = webhook_payload()
    del payload["entry"][0]["changes"][0]["value"]["messages"]
    assert _post(client, payload).status_code == 200
    assert sender.sent == []


def test_docs_are_disabled(setup):
    client, _, _ = setup
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_make_store_local(tmp_path):
    settings = make_settings(excel_local_path=str(tmp_path / "a.xlsx"))
    assert isinstance(_make_store(settings), LocalExcelStore)


def test_make_provider_without_key_returns_none():
    assert _make_provider(make_settings(gemini_api_key="")) is None


def test_make_provider_with_key_returns_gemini(monkeypatch):
    monkeypatch.setattr("google.genai.Client", lambda api_key: object())
    provider = _make_provider(make_settings(gemini_api_key="key"))
    assert type(provider).__name__ == "GeminiProvider"


def test_owner_echo_webhook_pauses_customer(setup):
    client, sender, services = setup
    assert _post(client, echo_payload()).status_code == 200
    assert services.state.is_paused(CUSTOMER)
    _post(client, webhook_payload(text="hola", message_id="wamid.after"))
    assert sender.texts_to(CUSTOMER) == []


def test_startup_restores_saved_state(workbook_bytes, tmp_path):
    state_file = StateFile(str(tmp_path / "state.json"))
    state_file.save({"mode": "ai", "owner_last_message": None, "paused_until": {}})
    services = build_services(make_settings(bot_mode="rule"), FakeSender(), MemoryStore(workbook_bytes), None, state_file)
    with TestClient(create_app(services)):
        assert services.state.mode == "ai"


def test_startup_without_saved_state_uses_bot_mode(workbook_bytes, tmp_path):
    state_file = StateFile(str(tmp_path / "missing.json"))
    services = build_services(make_settings(bot_mode="ai"), FakeSender(), MemoryStore(workbook_bytes), None, state_file)
    with TestClient(create_app(services)):
        assert services.state.mode == "ai"

