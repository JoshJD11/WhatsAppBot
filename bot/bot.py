"""Message handling shared by both modes: admin commands, pauses, engines, and handoff."""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .admin import CONFIRMATIONS, parse_command
from .config import Settings
from .engines.ai import AIEngine
from .engines.base import EngineUnavailable, Reply
from .engines.rule import rule_reply
from .state import BotState, StateFile
from .text import format_number_for_humans, mask_number, sanitize_outgoing
from .whatsapp import IncomingMessage, MessageSender, OwnerReply
from .workbook import HandoffRequest, WorkbookService

logger = logging.getLogger(__name__)


def owner_notification(request: HandoffRequest, pause_minutes: int) -> str:
    lines = [
        "Nueva solicitud de atención en el WhatsApp de Bosca.",
        f"Cliente: {format_number_for_humans(request.number)}",
    ]
    if request.name:
        lines.append(f"Nombre: {request.name}")
    lines.append(f"Resumen: {request.summary}")
    lines.append(
        f"Respóndele desde WhatsApp Business. El bot no le escribirá durante {pause_minutes} minutos."
    )
    return "\n".join(lines)


class Bot:
    def __init__(
        self,
        settings: Settings,
        state: BotState,
        workbook: WorkbookService,
        sender: MessageSender,
        ai_engine: AIEngine,
        state_file: StateFile | None = None,
    ) -> None:
        self._settings = settings
        self._state = state
        self._workbook = workbook
        self._sender = sender
        self._ai = ai_engine
        self._timezone = ZoneInfo(settings.timezone)
        self._state_file = state_file
        self._save_lock = asyncio.Lock()

    async def handle(self, message: IncomingMessage) -> None:
        if message.phone_number_id and message.phone_number_id != self._settings.whatsapp_phone_number_id:
            logger.warning("Ignoring a message for another phone number ID")
            return
        if self._state.is_duplicate(message.message_id):
            return

        if message.sender == self._settings.owner_number:
            self._state.record_owner_message()
            await self._save_state()
        if message.sender in self._settings.admin_numbers:
            await self._handle_admin(message)
            return

        async with self._state.customer_lock(message.sender):
            await self._handle_customer(message)

    async def _handle_admin(self, message: IncomingMessage) -> None:
        mode = parse_command(message.text)
        if mode is None:
            # Other admin messages only keep the owner's 24 hour window open.
            return
        self._state.mode = mode
        await self._save_state()
        logger.info("Mode switched to %s by %s", mode, mask_number(message.sender))
        await self._sender.send_text(message.sender, CONFIRMATIONS[mode])

    async def handle_owner_reply(self, reply: OwnerReply) -> None:
        """The owner wrote to a customer from the WhatsApp Business app: stay out of that chat."""
        if reply.phone_number_id and reply.phone_number_id != self._settings.whatsapp_phone_number_id:
            return
        if self._state.is_duplicate(reply.message_id):
            return
        async with self._state.customer_lock(reply.customer):
            self._state.pause(reply.customer)
            self._state.forget(reply.customer)
        await self._save_state()
        logger.info("Owner replied to %s; bot paused for that chat", mask_number(reply.customer))

    async def _save_state(self) -> None:
        if self._state_file is None:
            return
        async with self._save_lock:
            try:
                await asyncio.to_thread(self._state_file.save, self._state.to_snapshot())
            except OSError:
                logger.exception("Could not save the state file")

    async def _handle_customer(self, message: IncomingMessage) -> None:
        customer = message.sender
        if self._state.is_paused(customer):
            return
        if not self._state.allow_reply(customer):
            logger.warning("Rate limit reached for %s", mask_number(customer))
            return

        is_new = self._state.is_new_conversation(customer)
        knowledge = self._workbook.knowledge
        if not message.text:
            await self._send(customer, knowledge.message("solo_texto"))
            return

        reply = await self._reply(message, is_new)
        if reply.handoff:
            await self._handoff(message, reply.summary)
            return
        self._state.remember(customer, "customer", message.text)
        sent_text = await self._send(customer, reply.text)
        if sent_text:
            self._state.remember(customer, "bot", sent_text)

    async def _reply(self, message: IncomingMessage, is_new: bool) -> Reply:
        knowledge = self._workbook.knowledge
        if self._state.mode == "ai":
            try:
                return await self._ai.reply(knowledge, self._state.history(message.sender), message.text)
            except EngineUnavailable as exc:
                # The configured mode stays "ai"; only this message uses the menu.
                logger.warning("AI fallback to rule mode: %s", exc)
        return rule_reply(knowledge, message.text, is_new)

    async def _send(self, to: str, text: str) -> str:
        """Send a sanitized message. Returns the text sent, or "" if sending failed."""
        body = sanitize_outgoing(text)
        if not body:
            return ""
        return body if await self._sender.send_text(to, body) else ""

    async def _handoff(self, message: IncomingMessage, summary: str) -> None:
        customer = message.sender
        knowledge = self._workbook.knowledge
        await self._send(customer, knowledge.message("handoff_cliente"))
        self._state.pause(customer)
        self._state.forget(customer)
        await self._save_state()

        request = HandoffRequest(
            created_at=datetime.now(self._timezone),
            number=customer,
            name=message.name,
            summary=summary,
        )
        owner = self._settings.owner_number
        if not owner:
            logger.warning("OWNER_NUMBER is not set; the handoff was not notified")
        elif self._state.owner_window_open():
            await self._sender.send_text(owner, owner_notification(request, self._settings.handoff_pause_minutes))
        else:
            logger.warning(
                "Owner's 24 hour window is closed; handoff for %s logged but not notified",
                mask_number(customer),
            )
        if not await self._workbook.add_request(request):
            logger.error("Handoff for %s could not be saved in the Excel", mask_number(customer))
        logger.info("Handoff for %s", mask_number(customer))
