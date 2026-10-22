"""One-time Embedded Signup that connects the business number (coexistence).

The owner opens `/signup?key=<SIGNUP_KEY>` once, logs in with Facebook and
confirms the number in the WhatsApp Business app. The page sends the
exchangeable code to `/signup/complete`, which finishes the onboarding:

1. Exchange the code for a business token (the code lives about 30 seconds).
2. Subscribe this app to the WhatsApp Business Account so webhooks arrive.
3. Start the contacts and history sync that Meta expects within 24 hours.

The number is already registered by the WhatsApp Business app, so there is no
registration step. The token is used for these calls only and never stored,
logged or returned; the bot keeps using WHATSAPP_TOKEN.
"""

import json
import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com"
SYNC_TYPES = ("smb_app_state_sync", "history")


class SignupError(Exception):
    """Raised when the code exchange fails; nothing else can run without the token."""


@dataclass
class SignupResult:
    waba_id: str
    phone_number_id: str
    subscribed: bool = False
    synced: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.subscribed and all(self.synced.values())


def is_graph_id(value: str) -> bool:
    """Graph IDs are numeric. Anything else must never reach a request path."""
    return value.isdigit() and len(value) <= 32


def _error_text(response: httpx.Response) -> str:
    try:
        message = response.json().get("error", {}).get("message", "")
    except ValueError:
        message = ""
    return f"HTTP {response.status_code} {message}".strip()[:300]


class SignupClient:
    def __init__(self, app_id: str, app_secret: str, api_version: str, http: httpx.AsyncClient) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._base = f"{GRAPH_URL}/{api_version}"
        self._http = http

    async def _exchange_code(self, code: str) -> str:
        try:
            response = await self._http.get(
                f"{self._base}/oauth/access_token",
                params={"client_id": self._app_id, "client_secret": self._app_secret, "code": code},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            raise SignupError(f"Code exchange failed: {type(exc).__name__}") from exc
        if response.is_error:
            raise SignupError(f"Code exchange failed: {_error_text(response)}")
        token = response.json().get("access_token", "")
        if not token:
            raise SignupError("Code exchange returned no access token")
        return token

    async def _post(self, path: str, token: str, payload: dict[str, str] | None = None) -> str | None:
        """POST to the Graph API. Returns None on success, or a short error text."""
        try:
            response = await self._http.post(
                f"{self._base}/{path}", json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=15
            )
        except httpx.HTTPError as exc:
            return type(exc).__name__
        return _error_text(response) if response.is_error else None

    async def complete(self, code: str, waba_id: str, phone_number_id: str) -> SignupResult:
        if not (is_graph_id(waba_id) and is_graph_id(phone_number_id)):
            raise SignupError("waba_id and phone_number_id must be numeric")
        token = await self._exchange_code(code)
        result = SignupResult(waba_id=waba_id, phone_number_id=phone_number_id)

        error = await self._post(f"{waba_id}/subscribed_apps", token)
        result.subscribed = error is None
        if error:
            result.errors.append(f"subscribed_apps: {error}")

        for sync_type in SYNC_TYPES:
            error = await self._post(
                f"{phone_number_id}/smb_app_data", token, {"messaging_product": "whatsapp", "sync_type": sync_type}
            )
            result.synced[sync_type] = error is None
            if error:
                result.errors.append(f"{sync_type}: {error}")

        logger.info(
            "Signup finished for WABA %s, phone number ID %s: subscribed=%s synced=%s",
            waba_id, phone_number_id, result.subscribed, result.synced,
        )
        for error in result.errors:
            logger.error("Signup step failed: %s", error)
        return result


def _js(value: str) -> str:
    """A JSON string literal that is safe inside a <script> block."""
    return json.dumps(value).replace("</", "<\\/")


def render_signup_page(app_id: str, config_id: str, api_version: str, key: str) -> str:
    """The page the owner opens once. Its text is in Spanish because the owner reads it."""
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Conectar número de Bosca</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; line-height: 1.5; }}
  button {{ font-size: 1rem; padding: 12px 20px; cursor: pointer; }}
  pre {{ background: #f3f3f3; padding: 12px; white-space: pre-wrap; word-break: break-word; }}
</style>
</head>
<body>
<h1>Conectar el número de Bosca al bot</h1>
<p>Usa esta página una sola vez. Ten a mano el teléfono con WhatsApp Business abierto:
Meta te pedirá escanear un código o confirmar en la app.</p>
<button id="start" disabled>Conectar con Facebook</button>
<h2>Resultado</h2>
<pre id="log">Cargando el SDK de Facebook...</pre>
<script>
  const APP_ID = {_js(app_id)};
  const CONFIG_ID = {_js(config_id)};
  const API_VERSION = {_js(api_version)};
  const KEY = {_js(key)};
  const logBox = document.getElementById("log");
  const button = document.getElementById("start");
  let session = null;

  function show(text) {{ logBox.textContent += "\\n" + text; }}

  window.addEventListener("message", (event) => {{
    if (!event.origin.endsWith("facebook.com")) return;
    try {{
      const data = JSON.parse(event.data);
      if (data.type !== "WA_EMBEDDED_SIGNUP") return;
      show("Evento de Meta: " + data.event);
      if (data.event && data.event.startsWith("FINISH")) session = data.data;
      if (data.event === "CANCEL") show("Cancelado o con error: " + JSON.stringify(data.data));
    }} catch (error) {{ /* Other Facebook messages are not JSON. */ }}
  }});

  async function waitForSession() {{
    for (let i = 0; i < 20 && !session; i++) await new Promise((r) => setTimeout(r, 250));
    return session;
  }}

  async function finish(code) {{
    const info = await waitForSession();
    if (!info) {{ show("Meta no envió el ID del número. Revisa la configuración y vuelve a intentar."); return; }}
    show("Terminando la conexión en el servidor...");
    const response = await fetch("/signup/complete", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ key: KEY, code: code, waba_id: info.waba_id, phone_number_id: info.phone_number_id }}),
    }});
    show(JSON.stringify(await response.json(), null, 2));
  }}

  window.fbAsyncInit = function () {{
    FB.init({{ appId: APP_ID, autoLogAppEvents: true, xfbml: false, version: API_VERSION }});
    logBox.textContent = "Listo. Presiona el botón para empezar.";
    button.disabled = false;
  }};

  button.addEventListener("click", () => {{
    button.disabled = true;
    FB.login((response) => {{
      if (response.authResponse && response.authResponse.code) finish(response.authResponse.code);
      else show("No se completó el inicio de sesión.");
    }}, {{
      config_id: CONFIG_ID,
      response_type: "code",
      override_default_response_type: true,
      extras: {{ featureType: "whatsapp_business_app_onboarding" }},
    }});
  }});
</script>
<script async defer crossorigin="anonymous" src="https://connect.facebook.net/es_LA/sdk.js"></script>
</body>
</html>
"""
