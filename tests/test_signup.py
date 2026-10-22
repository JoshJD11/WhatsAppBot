import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from bot.main import build_services, create_app
from bot.signup import SignupClient, SignupError, SignupResult, is_graph_id, render_signup_page

from .conftest import FakeSender, MemoryStore, make_settings

KEY = "k" * 32
WABA_ID = "111"
PHONE_ID = "222"


def _graph(fail: set[str] | None = None, token: str = "business-token"):
    """A fake Graph API. `fail` holds path fragments that answer with an error."""
    fail = fail or set()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if any(fragment in path for fragment in fail):
            return httpx.Response(400, json={"error": {"message": "nope"}})
        if path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": token} if token else {})
        return httpx.Response(200, json={"success": True})

    return handler, calls


def _run(handler, code="code", waba_id=WABA_ID, phone_id=PHONE_ID) -> SignupResult:
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await SignupClient("app-id", "app-secret", "v26.0", http).complete(code, waba_id, phone_id)

    return asyncio.run(scenario())


def test_complete_runs_every_step_with_the_exchanged_token():
    handler, calls = _graph()
    result = _run(handler)
    assert result.ok
    assert result.synced == {"smb_app_state_sync": True, "history": True}
    exchange, subscribe, contacts, history = calls
    assert exchange.url.params["code"] == "code"
    assert exchange.url.params["client_secret"] == "app-secret"
    assert subscribe.url.path == f"/v26.0/{WABA_ID}/subscribed_apps"
    assert subscribe.headers["Authorization"] == "Bearer business-token"
    assert contacts.url.path == f"/v26.0/{PHONE_ID}/smb_app_data"
    assert json.loads(contacts.content)["sync_type"] == "smb_app_state_sync"
    assert json.loads(history.content)["sync_type"] == "history"


def test_complete_never_registers_the_number():
    handler, calls = _graph()
    _run(handler)
    assert not any(call.url.path.endswith("/register") for call in calls)


def test_failed_exchange_raises_and_stops():
    handler, calls = _graph(fail={"oauth"})
    with pytest.raises(SignupError, match="nope"):
        _run(handler)
    assert len(calls) == 1


def test_exchange_without_token_raises():
    handler, _ = _graph(token="")
    with pytest.raises(SignupError, match="no access token"):
        _run(handler)


def test_failed_step_is_reported_and_the_rest_still_runs():
    handler, calls = _graph(fail={"subscribed_apps"})
    result = _run(handler)
    assert not result.ok
    assert result.subscribed is False
    assert result.synced == {"smb_app_state_sync": True, "history": True}
    assert result.errors == ["subscribed_apps: HTTP 400 nope"]
    assert len(calls) == 4


def test_result_never_contains_the_token():
    handler, _ = _graph(fail={"smb_app_data"})
    result = _run(handler)
    assert "business-token" not in repr(result)


@pytest.mark.parametrize("waba_id, phone_id", [("../me", PHONE_ID), (WABA_ID, "1?x=2"), ("", PHONE_ID)])
def test_non_numeric_ids_are_rejected_before_any_call(waba_id, phone_id):
    handler, calls = _graph()
    with pytest.raises(SignupError):
        _run(handler, waba_id=waba_id, phone_id=phone_id)
    assert calls == []


@pytest.mark.parametrize("value, expected", [("123", True), ("", False), ("12a", False), ("1" * 33, False)])
def test_is_graph_id(value, expected):
    assert is_graph_id(value) is expected


def test_signup_page_embeds_settings_safely():
    page = render_signup_page("app</script>", "cfg", "v26.0", KEY)
    assert "app<\\/script>" in page
    assert '"cfg"' in page
    assert "whatsapp_business_app_onboarding" in page


# Routes


def _app(workbook_bytes, handler=None, **overrides):
    settings = make_settings(**({"meta_app_id": "app-id", "signup_config_id": "cfg", "signup_key": KEY} | overrides))
    signup = None
    if handler is not None:
        signup = SignupClient("app-id", "app-secret", "v26.0", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    services = build_services(settings, FakeSender(), MemoryStore(workbook_bytes), None, signup=signup)
    return TestClient(create_app(services))


def _body(**overrides):
    return {"key": KEY, "code": "code", "waba_id": WABA_ID, "phone_number_id": PHONE_ID} | overrides


def test_signup_page_with_key_is_served_without_caching(workbook_bytes):
    handler, _ = _graph()
    with _app(workbook_bytes, handler) as client:
        response = client.get("/signup", params={"key": KEY})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "Conectar" in response.text


@pytest.mark.parametrize("params", [{}, {"key": "wrong"}, {"key": KEY[:-1]}])
def test_signup_page_with_bad_key_does_not_exist(workbook_bytes, params):
    handler, _ = _graph()
    with _app(workbook_bytes, handler) as client:
        assert client.get("/signup", params=params).status_code == 404


def test_signup_is_off_without_a_signup_client(workbook_bytes):
    with _app(workbook_bytes) as client:
        assert client.get("/signup", params={"key": KEY}).status_code == 404
        assert client.post("/signup/complete", json=_body()).status_code == 404


def test_signup_is_off_when_settings_are_incomplete(workbook_bytes):
    handler, _ = _graph()
    with _app(workbook_bytes, handler, signup_config_id="") as client:
        assert client.get("/signup", params={"key": KEY}).status_code == 404


def test_complete_route_returns_the_result(workbook_bytes):
    handler, _ = _graph()
    with _app(workbook_bytes, handler) as client:
        response = client.post("/signup/complete", json=_body())
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["phone_number_id"] == PHONE_ID
    assert "business-token" not in response.text


def test_complete_route_with_bad_key_makes_no_calls(workbook_bytes):
    handler, calls = _graph()
    with _app(workbook_bytes, handler) as client:
        assert client.post("/signup/complete", json=_body(key="wrong")).status_code == 404
    assert calls == []


def test_complete_route_reports_a_failed_exchange_as_502(workbook_bytes):
    handler, _ = _graph(fail={"oauth"})
    with _app(workbook_bytes, handler) as client:
        assert client.post("/signup/complete", json=_body()).status_code == 502
