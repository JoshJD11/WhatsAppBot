"""Shared fixtures. All business data here is fake and exists only for tests."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest

from bot.config import Settings
from bot.knowledge import Knowledge, parse_workbook
from bot.template import build_template

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"
PHONE_NUMBER_ID = "123456789"
OWNER = "50671413393"
CUSTOMER = "50688887777"


def make_settings(**overrides) -> Settings:
    values = dict(
        whatsapp_token="test-token",
        whatsapp_phone_number_id=PHONE_NUMBER_ID,
        meta_app_secret=APP_SECRET,
        webhook_verify_token=VERIFY_TOKEN,
        gemini_model="test-model",
        excel_source="local",
        excel_local_path="unused.xlsx",
        bot_mode="rule",
        admin_numbers=frozenset({OWNER}),
        owner_number=OWNER,
    )
    values.update(overrides)
    return Settings(**values)


def sample_workbook_bytes() -> bytes:
    workbook = build_template()
    workbook["Productos"].append(
        ["Caja Prueba", "Cajas musicales", "Caja de prueba.", "Grabado de nombre", 25000, "caja prueba", "Sí"]
    )
    workbook["Productos"].append(["Llavero Prueba", "Otros productos", "Llavero de prueba.", "", None, "", "Sí"])
    workbook["Productos"].append(["Oculto Prueba", "Otros productos", "No se muestra.", "", None, "", "No"])
    workbook["Preguntas"].append(["¿Hacen envíos?", "Respuesta de prueba sobre envíos.", "envio, envios, enviar"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def workbook_bytes() -> bytes:
    return sample_workbook_bytes()


@pytest.fixture
def knowledge(workbook_bytes) -> Knowledge:
    return parse_workbook(workbook_bytes)


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs) -> None:
        self.current += timedelta(**kwargs)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


class FakeSender:
    def __init__(self, succeed: bool = True) -> None:
        self.sent: list[tuple[str, str]] = []
        self.succeed = succeed

    async def send_text(self, to: str, text: str) -> bool:
        self.sent.append((to, text))
        return self.succeed

    def texts_to(self, number: str) -> list[str]:
        return [text for to, text in self.sent if to == number]


class MemoryStore:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.uploads = 0
        self.fail = False

    def download(self) -> bytes:
        if self.fail:
            raise OSError("store unavailable")
        return self.data

    def upload(self, data: bytes) -> None:
        if self.fail:
            raise OSError("store unavailable")
        self.data = data
        self.uploads += 1


class FakeProvider:
    """LLM provider returning queued answers or raising queued exceptions."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, system_instruction, history, message, schema) -> str:
        self.calls.append(
            {"system": system_instruction, "history": list(history), "message": message, "schema": schema}
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def ai_json(action: str, reply: str = "", summary: str = "") -> str:
    return json.dumps({"action": action, "reply": reply, "summary": summary})


def sign(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def webhook_payload(
    sender: str = CUSTOMER,
    text: str | None = "hola",
    message_id: str = "wamid.1",
    kind: str = "text",
    name: str = "Cliente Prueba",
    phone_number_id: str = PHONE_NUMBER_ID,
) -> dict:
    message: dict = {"from": sender, "id": message_id, "timestamp": "1760000000", "type": kind}
    if kind == "text":
        message["text"] = {"body": text}
    elif kind == "image":
        message["image"] = {"id": "media-1", "mime_type": "image/jpeg"}
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "50670304072", "phone_number_id": phone_number_id},
                            "contacts": [{"wa_id": sender, "profile": {"name": name}}],
                            "messages": [message],
                        },
                    }
                ],
            }
        ],
    }


def echo_payload(customer: str = CUSTOMER, message_id: str = "wamid.echo", phone_number_id: str = PHONE_NUMBER_ID) -> dict:
    """A `smb_message_echoes` webhook: the owner wrote from the WhatsApp Business app."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "smb_message_echoes",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "50670304072", "phone_number_id": phone_number_id},
                            "message_echoes": [
                                {
                                    "from": "50670304072",
                                    "to": customer,
                                    "id": message_id,
                                    "timestamp": "1760000000",
                                    "type": "text",
                                    "text": {"body": "Hola, te atiendo yo."},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

