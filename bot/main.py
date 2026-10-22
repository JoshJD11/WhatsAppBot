"""FastAPI server that receives WhatsApp webhooks.

Run with: uvicorn bot.main:app
"""

import asyncio
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import timedelta

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from .bot import Bot
from .config import Settings, load_settings
from .engines.ai import AIEngine, GeminiProvider, LLMProvider
from .excel_store import DriveExcelStore, ExcelStore, LocalExcelStore
from .signup import SignupClient, SignupError, render_signup_page
from .state import BotState, StateFile
from .whatsapp import (
    IncomingMessage,
    MessageSender,
    OwnerReply,
    WhatsAppClient,
    parse_account_events,
    parse_messages,
    parse_owner_replies,
    verify_signature,
)
from .workbook import WorkbookService

logger = logging.getLogger(__name__)
MAX_BODY_BYTES = 1_000_000


@dataclass
class Services:
    settings: Settings
    state: BotState
    workbook: WorkbookService
    bot: Bot
    state_file: StateFile | None = None
    signup: SignupClient | None = None


class SignupCompletion(BaseModel):
    key: str
    code: str
    waba_id: str
    phone_number_id: str


def build_services(
    settings: Settings,
    sender: MessageSender,
    store: ExcelStore,
    provider: LLMProvider | None,
    state_file: StateFile | None = None,
    signup: SignupClient | None = None,
) -> Services:
    state = BotState(
        mode=settings.bot_mode,
        handoff_pause=timedelta(minutes=settings.handoff_pause_minutes),
        rate_limit_max=settings.rate_limit_max_messages,
        rate_limit_window=timedelta(seconds=settings.rate_limit_window_seconds),
        history_limit=settings.ai_history_messages,
        history_idle=timedelta(minutes=settings.ai_history_idle_minutes),
    )
    workbook = WorkbookService(store)
    bot = Bot(settings, state, workbook, sender, AIEngine(provider), state_file)
    return Services(
        settings=settings, state=state, workbook=workbook, bot=bot, state_file=state_file, signup=signup
    )


def _make_store(settings: Settings) -> ExcelStore:
    if settings.excel_source == "local":
        return LocalExcelStore(settings.excel_local_path)
    return DriveExcelStore(settings.drive_file_id, settings.google_service_account_file)


def _make_provider(settings: Settings) -> LLMProvider | None:
    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY is not set; AI mode will always fall back to the menu")
        return None
    return GeminiProvider(
        settings.gemini_api_key,
        settings.gemini_model,
        settings.gemini_thinking_level,
        settings.gemini_timeout_seconds,
    )


async def _restore_state(services: Services) -> None:
    """Load the saved state, if any. The saved mode wins over BOT_MODE."""
    if services.state_file is None:
        return
    snapshot = await asyncio.to_thread(services.state_file.load)
    if snapshot is not None:
        services.state.restore_snapshot(snapshot)


async def _reload_loop(services: Services) -> None:
    interval = services.settings.excel_reload_minutes * 60
    while True:
        await asyncio.sleep(interval)
        await services.workbook.reload()
        services.state.prune()


def create_app(services: Services | None = None) -> FastAPI:
    """Build the app. Tests pass ready-made services; production builds them from env."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        http: httpx.AsyncClient | None = None
        current = services
        if current is None:
            load_dotenv()
            logging.basicConfig(
                level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            )
            settings = load_settings()
            http = httpx.AsyncClient()
            sender = WhatsAppClient(
                settings.whatsapp_token, settings.whatsapp_phone_number_id, settings.graph_api_version, http
            )
            state_file = StateFile(settings.state_file) if settings.state_file else None
            signup = (
                SignupClient(settings.meta_app_id, settings.meta_app_secret, settings.graph_api_version, http)
                if settings.signup_enabled
                else None
            )
            current = build_services(
                settings, sender, _make_store(settings), _make_provider(settings), state_file, signup
            )
        await _restore_state(current)
        logger.info("Running in %s mode", current.state.mode)
        app.state.services = current
        await current.workbook.reload()
        reload_task = asyncio.create_task(_reload_loop(current))
        try:
            yield
        finally:
            reload_task.cancel()
            with suppress(asyncio.CancelledError):
                await reload_task
            if http is not None:
                await http.aclose()

    app = FastAPI(title="Bosca WhatsApp bot", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/webhook", response_class=PlainTextResponse)
    async def verify_webhook(
        request: Request,
        mode: str = Query("", alias="hub.mode"),
        token: str = Query("", alias="hub.verify_token"),
        challenge: str = Query("", alias="hub.challenge"),
    ) -> str:
        """Meta's one-time handshake when the webhook URL is saved in the app dashboard."""
        expected = request.app.state.services.settings.webhook_verify_token
        if mode == "subscribe" and token and _same(token, expected):
            return challenge
        raise HTTPException(status_code=403, detail="Verification failed")

    @app.post("/webhook")
    async def receive_webhook(request: Request, background: BackgroundTasks) -> dict[str, str]:
        current: Services = request.app.state.services
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Payload too large")
        if not verify_signature(current.settings.meta_app_secret, body, request.headers.get("X-Hub-Signature-256")):
            logger.warning("Rejected a webhook call with an invalid signature")
            raise HTTPException(status_code=403, detail="Invalid signature")
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON") from exc

        # Answer Meta right away and process afterwards, so slow AI calls do not cause retries.
        payload = payload if isinstance(payload, dict) else {}
        for message in parse_messages(payload):
            background.add_task(_handle_safely, current.bot, message)
        for reply in parse_owner_replies(payload):
            background.add_task(_handle_owner_reply_safely, current.bot, reply)
        for event in parse_account_events(payload):
            logger.warning("Meta account update: %s", event)
        return {"status": "received"}

    def _check_signup_key(services: Services, key: str) -> SignupClient:
        # 404, not 403: while signup is off or the key is wrong, the page does not exist.
        if services.signup is None or not services.settings.signup_enabled:
            raise HTTPException(status_code=404)
        if not key or not _same(key, services.settings.signup_key):
            raise HTTPException(status_code=404)
        return services.signup

    @app.get("/signup", response_class=HTMLResponse)
    async def signup_page(request: Request, key: str = Query("")) -> HTMLResponse:
        current: Services = request.app.state.services
        _check_signup_key(current, key)
        settings = current.settings
        page = render_signup_page(settings.meta_app_id, settings.signup_config_id, settings.graph_api_version, key)
        return HTMLResponse(page, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    @app.post("/signup/complete")
    async def signup_complete(request: Request, body: SignupCompletion) -> dict[str, object]:
        current: Services = request.app.state.services
        client = _check_signup_key(current, body.key)
        try:
            result = await client.complete(body.code, body.waba_id, body.phone_number_id)
        except SignupError as exc:
            logger.error("Signup failed: %s", exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "ok": result.ok,
            "waba_id": result.waba_id,
            "phone_number_id": result.phone_number_id,
            "subscribed": result.subscribed,
            "synced": result.synced,
            "errors": result.errors,
        }

    return app


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


async def _handle_safely(bot: Bot, message: IncomingMessage) -> None:
    # Last line of defense: a background task has nobody to report errors to.
    try:
        await bot.handle(message)
    except Exception:
        logger.exception("Unexpected error while handling a message")


async def _handle_owner_reply_safely(bot: Bot, reply: OwnerReply) -> None:
    try:
        await bot.handle_owner_reply(reply)
    except Exception:
        logger.exception("Unexpected error while handling an owner reply")


app = create_app()
