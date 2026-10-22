"""WhatsApp Cloud API: webhook signature, payload parsing, and sending replies."""

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .text import mask_number, sanitize_outgoing

logger = logging.getLogger(__name__)

# Message types the bot never answers (a reaction is not a question).
IGNORED_TYPES = frozenset({"reaction", "system", "ephemeral", "unsupported", "errors"})


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Check Meta's X-Hub-Signature-256 header against the raw request body."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@dataclass(frozen=True)
class IncomingMessage:
    message_id: str
    sender: str
    name: str
    type: str
    text: str  # Empty for media and other non-text messages.
    phone_number_id: str


def _text_of(message: dict[str, Any]) -> str:
    kind = message.get("type")
    if kind == "text":
        return str(message.get("text", {}).get("body", ""))
    if kind == "button":
        return str(message.get("button", {}).get("text", ""))
    if kind == "interactive":
        interactive = message.get("interactive", {})
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return str(reply.get("title", ""))
    return ""


def parse_messages(payload: dict[str, Any]) -> list[IncomingMessage]:
    """Extract customer messages from a webhook payload.

    Status updates, message echoes from the WhatsApp Business app, and other
    fields are skipped.
    """
    if payload.get("object") != "whatsapp_business_account":
        return []
    messages = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            phone_number_id = str((value.get("metadata") or {}).get("phone_number_id", ""))
            names = {
                str(contact.get("wa_id", "")): str((contact.get("profile") or {}).get("name", ""))
                for contact in value.get("contacts") or []
            }
            for message in value.get("messages") or []:
                kind = str(message.get("type", ""))
                sender = str(message.get("from", ""))
                message_id = str(message.get("id", ""))
                if not sender or not message_id or kind in IGNORED_TYPES:
                    continue
                messages.append(
                    IncomingMessage(
                        message_id=message_id,
                        sender=sender,
                        name=names.get(sender, ""),
                        type=kind,
                        text=_text_of(message).strip(),
                        phone_number_id=phone_number_id,
                    )
                )
    return messages


@dataclass(frozen=True)
class OwnerReply:
    """A message the owner sent to a customer from the WhatsApp Business app."""

    message_id: str
    customer: str
    phone_number_id: str


def parse_owner_replies(payload: dict[str, Any]) -> list[OwnerReply]:
    """Extract `smb_message_echoes` events (coexistence only).

    Meta sends them when someone writes from the WhatsApp Business app on the
    business number; messages sent by the bot through the API are not echoed.
    """
    if payload.get("object") != "whatsapp_business_account":
        return []
    replies = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "smb_message_echoes":
                continue
            value = change.get("value") or {}
            phone_number_id = str((value.get("metadata") or {}).get("phone_number_id", ""))
            for echo in value.get("message_echoes") or []:
                customer = str(echo.get("to", ""))
                message_id = str(echo.get("id", ""))
                if customer and message_id:
                    replies.append(OwnerReply(message_id, customer, phone_number_id))
    return replies


def parse_account_events(payload: dict[str, Any]) -> list[str]:
    """Describe `account_update` events, such as Meta disconnecting the number.

    A `PARTNER_REMOVED` event with reason `PRIMARY_INACTIVITY` means the
    WhatsApp Business app on the main phone was not opened for about 14 days.
    """
    if payload.get("object") != "whatsapp_business_account":
        return []
    events = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "account_update":
                continue
            value = change.get("value") or {}
            event = str(value.get("event", "UNKNOWN"))
            reason = (value.get("disconnection_info") or {}).get("reason")
            events.append(f"{event} ({reason})" if reason else event)
    return events


class MessageSender(Protocol):
    async def send_text(self, to: str, text: str) -> bool: ...


class WhatsAppClient:
    """Sends free-form text replies. Never sends templates (see CLAUDE.md, Conversations)."""

    def __init__(self, token: str, phone_number_id: str, api_version: str, http: httpx.AsyncClient) -> None:
        self._url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._http = http

    async def send_text(self, to: str, text: str) -> bool:
        body = sanitize_outgoing(text)
        if not body:
            return False
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        try:
            response = await self._http.post(self._url, json=payload, headers=self._headers, timeout=15)
        except httpx.HTTPError as exc:
            logger.error("Sending to %s failed: %s", mask_number(to), type(exc).__name__)
            return False
        if response.is_error:
            # Meta's error body explains the cause (closed 24 hour window, bad token...).
            logger.error("Sending to %s failed: HTTP %s %s", mask_number(to), response.status_code, response.text[:500])
            return False
        return True
