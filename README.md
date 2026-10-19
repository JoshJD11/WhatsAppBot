# WhatsAppBot

A WhatsApp bot that answers customer messages for **Bosca**, a Costa Rican business that makes laser-cut wooden pieces (mainly music boxes). It answers only with information stored in an Excel file on Google Drive, and it hands the conversation to a person when it cannot help.

## What it does

- **Two reply modes.** The owner switches between them from WhatsApp:
  - **AI mode:** Google Gemini (free tier) answers in natural language, using only the Excel content. It refuses off-topic questions and never invents prices or details.
  - **Menu mode:** a numbered menu plus keyword matching ("envío", "precio", a product name...). Menu texts, keywords and answers come from the same Excel.
- **Automatic fallback.** If Gemini fails (quota, rate limit, timeout, any error), that message is answered in menu mode. The next message tries the AI again.
- **Handoff to a person.** When a customer asks for a person, a quote or an order, or the bot has no answer, the bot:
  1. tells the customer they will be attended soon,
  2. notifies the owner on WhatsApp (only while the owner's 24 hour window is open),
  3. adds a row to the `Solicitudes` sheet of the Excel,
  4. stays silent with that customer for 60 minutes so the owner can take over.
- **Owner replies pause the bot.** When the owner writes to a customer from the WhatsApp Business app, the bot stays silent with that customer for 60 minutes from the owner's last message, so they never answer at the same time. This uses Meta's `smb_message_echoes` webhook, which only exists once the real number is connected through coexistence.
- **Survives restarts.** The mode, active pauses and the time of the owner's last message are saved in `data/state.json`.
- **Admin commands** (only from numbers in `ADMIN_NUMBERS`; the whole message must be the command):

  | Command | Effect |
  |---|---|
  | `#bosca ia` | Switch to AI mode |
  | `#bosca menu` | Switch to menu mode |

- **Free to run.** The bot only replies to incoming messages (free on the Cloud API). It never starts conversations and never sends template messages.
- **Security.** Every webhook call is checked with Meta's `X-Hub-Signature-256` signature. Duplicate deliveries are ignored, replies are rate limited per customer, customer text cannot change the bot's rules or mode, and logs hide most of each phone number.

## How it works

```
Customer ──► WhatsApp Cloud API ──webhook──► FastAPI server (bot/main.py)
                                               ├─ signature check, dedup
                                               ├─ admin commands (bot/admin.py)
                                               ├─ reply engine: AI (bot/engines/ai.py)
                                               │                menu (bot/engines/rule.py)
                                               ├─ handoff + pause (bot/bot.py)
                                               └─ Excel: knowledge cache + Solicitudes sheet
                                                  (bot/workbook.py, Drive or local file)
```

| Path | Purpose |
|---|---|
| `bot/main.py` | FastAPI app: webhook endpoints, startup, Excel reload timer |
| `bot/bot.py` | Message flow shared by both modes, handoff |
| `bot/engines/` | `rule.py` (menu and keywords), `ai.py` (Gemini behind an `LLMProvider` interface) |
| `bot/knowledge.py` | Excel layout and parsing, shared text formatting |
| `bot/workbook.py`, `bot/excel_store.py` | Cached knowledge, writes to `Solicitudes`, Drive or local storage |
| `bot/state.py` | Runtime state (mode, pauses, rate limits, history, owner window) and `StateFile` (JSON) |
| `bot/whatsapp.py` | Signature check, payload parsing, sending replies |
| `bot/template.py`, `scripts/create_excel_template.py` | Excel template generator |
| `templates/bosca_bot.xlsx` | Ready-made Excel template |
| `tests/` | pytest suite |

## Running it

### 1. Install

Requires Python 3.12 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

### 2. Prepare the Excel

Copy the template and fill in the real business data:

```bash
mkdir -p data
cp templates/bosca_bot.xlsx data/bosca_bot.xlsx
```

The `Instrucciones` sheet explains each sheet. In short:

| Sheet | Columns | Notes |
|---|---|---|
| `Productos` | Nombre, Categoría, Descripción, Personalización, Precio, Palabras clave, Disponible | Empty price: the bot says the piece is quoted. `Disponible = No` hides a product. |
| `Preguntas` | Pregunta, Respuesta, Palabras clave | Frequent questions (shipping, payment, materials...). |
| `Menu` | Opción, Texto del menú, Acción, Categoría, Respuesta, Palabras clave | Action: `responder`, `productos` (lists a category) or `persona` (handoff). |
| `Mensajes` | Clave, Texto, Para qué se usa | The bot's own texts (greeting, handoff reply...). Change `Texto`, never `Clave`. |
| `Solicitudes` | Fecha, Número, Nombre, Resumen, Estado | Written by the bot on each handoff. |

Keywords are comma separated and matched ignoring case and accents. This layout is provisional until the Excel is designed with the owner. To regenerate the template: `python -m scripts.create_excel_template`.

**Using Google Drive** (`EXCEL_SOURCE=drive`):

1. In Google Cloud Console, create a project, enable the **Google Drive API**, create a **service account** and download its JSON key. Keep the key out of the repository (for example in `credentials/`, which git ignores).
2. Upload the `.xlsx` to Drive. Keep it as an Excel file; do not convert it to Google Sheets.
3. Share the file with the service account's email as **Editor** (it needs to write the `Solicitudes` sheet).
4. Set `DRIVE_FILE_ID` (from the file URL) and `GOOGLE_SERVICE_ACCOUNT_FILE` in `.env`.

### 3. Configure

```bash
cp .env.example .env
```

Fill in `.env`. Every variable is described in `.env.example`. For a first local test, `EXCEL_SOURCE=local` avoids the Google setup.

### 4. Start the server

To run only the bot, without a tunnel:

```bash
uvicorn bot.main:app --port 8000
```

Check it at `http://localhost:8000/health`. The Excel is loaded at startup and every `EXCEL_RELOAD_MINUTES`.

The saved state in `data/state.json` wins over `BOT_MODE`: after a `#bosca ia` command, the bot restarts in AI mode. To go back to the `.env` value, send the other command or delete the file while the bot is stopped.

### 5. Expose it with ngrok (local development)

Meta needs a public HTTPS URL. The project uses **ngrok** with its free **static domain**, so the URL is always the same and is configured in Meta only once.

One-time setup (done by the owner, outside the project):

1. Create a free account at [ngrok.com](https://ngrok.com) and install the ngrok client.
2. Add your authtoken to the ngrok client (`ngrok config add-authtoken ...`). It stays in ngrok's own config file, never in this project.
3. Claim your free static domain in the ngrok dashboard (Domains), for example `your-name.ngrok-free.app`.
4. Put that domain in `.env` as `NGROK_DOMAIN` (only the domain, without `https://`).

Start the bot and the tunnel together:

```bash
scripts/start.sh
```

The script reads `NGROK_DOMAIN` from `.env`, starts uvicorn, waits until `/health` answers, and then runs:

```bash
ngrok http --url=<NGROK_DOMAIN> 8000
```

`Ctrl+C` stops both. To run them by hand instead, start uvicorn first and then the ngrok command above in a second terminal.

Anyone with the URL can reach **only the bot** (not the rest of the computer), and the bot rejects any call without a valid Meta signature. While ngrok is stopped, the URL does not reach your computer at all.

### 6. Connect Meta

1. At [developers.facebook.com](https://developers.facebook.com), create an app of type Business and add the **WhatsApp** product.
2. Start with Meta's free **test number** (WhatsApp > API Setup): copy the token and the phone number ID into `.env`, and add your own phone as a test recipient.
3. Run `scripts/start.sh`. Then, in WhatsApp > Configuration, set the callback URL to `https://<NGROK_DOMAIN>/webhook` and the verify token to your `WEBHOOK_VERIFY_TOKEN`. Meta checks the URL right away, so the bot must be running when you save. Subscribe to the **messages** field (and, once the real number uses coexistence, to **smb_message_echoes**).
4. Send a message to the test number and the bot answers.

The callback URL is configured **only once**: the static domain does not change when you restart the bot, ngrok or the computer. Messages that arrive while the bot is off are not answered; Meta retries for a while and then gives up.

Moving to the real number (+506 7030 4072, which runs on the WhatsApp Business app) uses Meta's **coexistence** onboarding. See the open question in `CLAUDE.md` before attempting it.

## Troubleshooting ngrok

| Problem | Cause and fix |
|---|---|
| The tunnel does not start (`authentication failed`, `ERR_NGROK_4018`) | The authtoken is missing or wrong. Run `ngrok config add-authtoken <token>` again with the token from the ngrok dashboard. |
| ngrok rejects the domain or says it is not yours | `NGROK_DOMAIN` in `.env` must match exactly the domain claimed in the ngrok dashboard (Domains), without `https://` and without a trailing slash. |
| Another tunnel is already online | The free plan allows one tunnel at a time. Close the other ngrok window (or stop it in the dashboard, Agents) and try again. |
| Meta says the callback URL could not be verified | The bot is not running or the verify token differs. Start it with `scripts/start.sh`, check `http://localhost:8000/health`, and make sure the verify token in Meta equals `WEBHOOK_VERIFY_TOKEN`. |
| The script stops with "The bot stopped while starting" | uvicorn failed, usually because of a missing value in `.env`. The error is printed above that line. |
| Opening the URL in a browser shows an ngrok warning page | Normal on the free plan for browser visits. Meta's requests are not affected. |

## Tests

```bash
pytest
```

The tests use fakes for WhatsApp, Gemini and Drive, so they need no network or credentials.

## Limitations

- Meta only lets the bot message the owner within 24 hours of the owner's last message to the business number. The owner must write once a day (any text or a command) to keep receiving handoff notifications. The bot cannot do this for the owner: it cannot send from the owner's number, and messaging first would need a paid template.
- Conversation history for the AI, duplicate detection and rate limits stay in memory and reset on restart.
- Each write to the Excel replaces the whole file. Avoid editing the `Solicitudes` sheet at the exact moment a request arrives.
- A serverless host such as Vercel has no persistent disk, so `data/state.json` would not work there. It needs a shared store first.

## License

MIT. See `LICENSE`.
