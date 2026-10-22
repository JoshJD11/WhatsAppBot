# WhatsAppBot

## Project Description
WhatsAppBot answers the customer messages that reach the WhatsApp number of **Bosca**, a Costa Rican laser art business whose main product is handcrafted wooden **music boxes**. The full business context lives in `~/Desktop/Bosca/CLAUDE.md` (read it for the brand and its rules, not for its code).

- **Type:** WhatsApp chatbot (backend service, no web interface)
- **Status:** First version built and tested locally with fakes (see Current Progress). Not yet connected to Meta, Gemini or Drive with real credentials.
- **Target users:** People in Costa Rica who write to Bosca on WhatsApp asking about products, customizations, prices, or orders.
- **Business number:** +506 7030 4072 (the same number the business already uses).

## Claude's Role
Act as a senior developer specialized in backend development, messaging integrations, QA, and security.

## Goal
Reply to WhatsApp messages automatically using only business information stored in an Excel file on Google Drive. The bot has **two modes**, and the owner chooses which one runs:

1. **AI mode**
   - An LLM (Google Gemini, free tier) answers in natural language.
   - It answers **only** from the Excel content and **only** about the business.
   - Any other topic gets a polite refusal and a redirect to Bosca topics (for example, "Solo puedo ayudarte con temas de Bosca. ¿Te interesa alguna caja musical?").
   - It never invents products, prices, delivery times, or policies that are not in the Excel.

2. **Rule mode (no AI)**
   - A classic chatbot that combines a **numbered menu** (for example "1. Cajas musicales, 2. Otros productos, 3. Hablar con una persona") with **keyword matching** (a message containing "precio", "envío", etc. jumps straight to the right answer).
   - Menu texts, keywords, and answers come from the same Excel, so editing the Excel changes the bot without touching code.
   - It covers the same questions as AI mode and gives the same information.

Both modes share everything except the reply engine: WhatsApp integration, Excel loading, the handoff to a person, and the admin commands.

## Decisions Made
| Topic | Decision |
|---|---|
| WhatsApp integration | Official **WhatsApp Cloud API** (Meta). No unofficial libraries (Baileys, whatsapp-web.js): they break WhatsApp's terms and can get the number banned. |
| Number | The business number +506 7030 4072. It is on the **WhatsApp Business** app, so it is shared between the owner's phone and the Cloud API through Meta's coexistence feature. |
| Language | Python. |
| AI provider | **Google Gemini, free tier.** The owner does not want to pay for an API. A Claude subscription cannot power a customer-facing bot, so Claude is not an option without paid API credits. |
| Data source | An `.xlsx` file uploaded to Google Drive. It does not exist yet; Claude will design and build it in a later session. For now it is the bot's database: the bot reads business information from it and **writes requests to a separate sheet** in the same file. |
| Prices | The bot gives prices **only** if the Excel contains them. If a product has no price, it says the piece is quoted on request. |
| Mode switch | By a **WhatsApp command** sent from an authorized admin number. Only two commands exist (see Admin Commands). |
| Handoff to a person | When the bot cannot answer or the customer asks for a person or a quote, it **notifies the owner on WhatsApp at +506 7141 3393**, **tells the customer** they will be attended soon, logs the request in the Excel, and **stays silent with that customer for one hour** so the owner can take over. |
| Off-topic messages | Polite refusal and redirect to the business. |
| Business hours | The bot does **not** mention business hours for now. |
| AI unavailable | If Gemini fails for any reason (quota or tokens used up on the free **or** a future paid plan, rate limits, errors, timeouts), the bot **automatically answers that message in rule mode**. The configured mode stays `ai`, so the next message tries the AI again. The customer never gets silence or an error. |
| Admin number | Commands are sent **only from +506 7141 3393**, the owner's other number. |
| Conversations | The bot **only replies** to messages. It never starts a conversation with anyone, and it never sends paid template messages. |
| Owner notification | Sent to +506 7141 3393 **only while its 24 hour window is open** (option A, see Notes). |
| Hosting | First on the owner's computer for development, then Vercel or a similar free host. |
| Connecting the real number | **Path 1 (chosen 2026-10-20):** the owner, as admin of their own Meta app, runs **Embedded Signup with coexistence** from a page the bot serves (`/signup`), with no Tech Provider or BSP. If Meta blocks it, the fallback is becoming a Tech Provider (free, but needs business verification and App Review). BSPs were rejected (usually paid), and moving the number fully to the API was rejected (the owner would lose the app). |
| Coexistence trade-offs | The owner **accepted** (2026-10-20) losing in the app: broadcast lists (read only), disappearing messages, view once, live location, and the unlinking of companion devices (they can be linked again, except WhatsApp for Windows). |

## Architecture
```
WhatsApp customer
      │
      ▼
Meta Cloud API ──webhook──► Bot server (Python)
                              ├── Webhook verification and signature check
                              ├── Admin command handler (mode switch, Excel reload)
                              ├── Reply engine: ai  (Gemini + Excel context)
                              │                 rule (menu + keywords from Excel)
                              ├── Handoff: notify owner + tell customer + pause bot for that customer
                              └── Excel on Google Drive: knowledge (read, cached) + requests sheet (write)
```

- **Webhook:** Meta sends each incoming message to a public HTTPS URL. During local development an ngrok tunnel with a free static domain exposes the computer.
- **Excel loading:** download the `.xlsx` from Drive with a Google service account (the file is shared with it), parse it, and cache it in memory. Reload it on a timer and with an admin command, not on every message.
- **AI context:** the Excel content goes into the prompt as the only allowed source. The system prompt sets the scope, the tone, and the refusal rule.
- **Provider abstraction:** keep the LLM behind a small interface so Gemini can be replaced (for example by Claude with API credits) without changing the rest of the bot.
- **AI fallback:** the AI engine signals failure to the caller, which then runs the rule engine for that same message. Log each fallback so the owner can tell when the quota is running out.
- **Requests sheet:** each handoff adds a row to a separate sheet of the same `.xlsx` (columns to be defined with the Excel design: date, customer number, name if known, summary of the request, status). Writing means downloading the file, adding the row, and uploading it again, so see the concurrency note below.
- **Handoff pause:** after a handoff, the bot stays silent with that customer for **one hour** (kept in configuration as `HANDOFF_PAUSE_MINUTES=60`). Messages that arrive during that hour get no reply. The bot answers again only when the customer writes **after** the hour has passed. There is no command to end the pause early.
- **Costs:** replies within 24 hours of the other person's last message are free on the Cloud API. The bot never starts a conversation and never sends template messages, so it costs nothing. The owner notification follows the same rule (see Notes).

## Admin Commands
- Only numbers listed in an `ADMIN_NUMBERS` setting can run commands. Today that is only `50671413393`. Messages from any other number are treated as normal customer messages, even if they look like commands.
- Commands are handled by code **before** any reply engine, so the AI can never trigger or fake them.
- There are exactly **two commands**. They are case insensitive and must be the whole message:

| Command | Effect | Bot reply to the admin |
|---|---|---|
| `#bosca ia` | Switch to AI mode | `Modo IA activado.` |
| `#bosca menu` | Switch to rule mode | `Modo menú activado.` |

- The `#bosca` prefix keeps a customer from triggering a command by accident. Even so, only admin numbers can use them.
- The mode applies to every conversation from that moment on.
- The default mode at startup comes from a `BOT_MODE` setting (`ai` or `rule`).
- The Excel reloads on a timer only; there is no reload command.
- Any other message from an admin number gets no reply. It still counts as the owner's daily message that keeps the 24 hour window open (see Notes).
- Commands are not accepted from the business number +506 7030 4072. It cannot message itself, and a command typed in the WhatsApp Business app would also be delivered to the person in that chat.

## Stack and Tools
- **Language:** Python (version to be confirmed, 3.12+ suggested).
- **Messaging:** WhatsApp Cloud API (Meta Graph API).
- **AI:** Google Gemini API, free tier. Keep the model name in configuration, never hard-coded.
- **Data:** Google Drive API (service account) and `openpyxl` to read and write the `.xlsx`.
- **Web framework:** FastAPI, for the webhook server.
- **Tools:** Git.
- **Project skills** (in `.agents/skills`, linked from `.claude/skills`): `gemini-api-dev`, `python-testing-patterns`, `fastapi-python`, `xlsx-manipulation`, `whatsapp-automation`, `python-patterns`, `async-python-patterns`. Follow `python-patterns` and `async-python-patterns` for all Python code (typing, idioms, no blocking calls in the event loop). The `whatsapp-automation` skill also covers broadcasts, template messages, and outbound notifications. Ignore those parts: this bot only replies and never sends templates (see Decisions Made).
- **Python version:** 3.12+ required; developed on Python 3.14 in a `.venv` virtual environment.
- **Dependencies:** pinned in `requirements.txt` (runtime) and `requirements-dev.txt` (adds pytest): fastapi, uvicorn, httpx, google-genai, google-api-python-client, google-auth, openpyxl, python-dotenv.
- **Gemini SDK:** `google-genai` with the **Interactions API** (`client.interactions.create`), as the `gemini-api-dev` skill requires. The legacy `google-generativeai` package and `generate_content` are not used.
- **Graph API version:** `v26.0` (configurable with `GRAPH_API_VERSION`).
- **Test runner:** pytest.
- **Tunnel for local development:** **ngrok** with a free static domain (`ngrok http --url=<NGROK_DOMAIN> 8000`), chosen by the owner on 2026-10-18 so the Meta callback URL never changes. It replaced the Cloudflare quick tunnel (chosen 2026-10-16), whose URL changed on every run. The owner creates the ngrok account, installs the client, adds the authtoken and claims the domain; Claude never asks for or handles the authtoken. `NGROK_DOMAIN` lives in `.env`. `scripts/start.sh` starts uvicorn and ngrok together. **Never run ngrok with sudo** (owner asked on 2026-10-19; the cause was `/usr/local/bin` missing from PATH and the authtoken saved in root's config, and the owner chose the fix without sudo). The script refuses to run as root and falls back to `/usr/local/bin/ngrok` when ngrok is not in PATH.
- **Not decided:** hosting provider for production. Ask before choosing it.

## Project Structure
```
WhatsAppBot/
├── bot/
│   ├── main.py          # FastAPI app: /webhook (GET handshake, POST messages), /health, lifespan, reload timer
│   ├── bot.py           # Message flow: dedup, admin commands, pause, rate limit, engines, handoff
│   ├── admin.py         # The two #bosca commands
│   ├── config.py        # Settings from environment variables
│   ├── state.py         # In-memory runtime state (mode, pauses, rate limit, history, owner window)
│   ├── knowledge.py     # Excel layout, parsing, default bot messages, shared formatting
│   ├── workbook.py      # Knowledge cache and serialized writes to the Solicitudes sheet
│   ├── excel_store.py   # DriveExcelStore (service account) and LocalExcelStore
│   ├── whatsapp.py      # Signature check, webhook parsing, WhatsAppClient (text replies only)
│   ├── signup.py        # One-time Embedded Signup page and onboarding calls (coexistence)
│   ├── template.py      # Builds the Excel template
│   ├── text.py          # Normalization, outgoing text sanitizer (no emojis, no double hyphens)
│   └── engines/         # base.py (Reply), rule.py (menu + keywords), ai.py (LLMProvider + Gemini)
├── scripts/
│   ├── create_excel_template.py
│   └── start.sh               # Starts uvicorn, waits for /health, then ngrok with NGROK_DOMAIN
├── templates/bosca_bot.xlsx   # Generated template, no business data
├── tests/                     # pytest suite with fakes for WhatsApp, Gemini and Drive
├── .env.example
└── requirements*.txt
```

## Useful Commands
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt           # Install dependencies
pytest                                        # Run the tests
uvicorn bot.main:app --port 8000              # Run the bot (reads .env)
scripts/start.sh                              # Bot + ngrok tunnel (reads NGROK_DOMAIN from .env)
ngrok http --url=<NGROK_DOMAIN> 8000          # Tunnel only, if uvicorn is already running
python -m scripts.create_excel_template       # Regenerate templates/bosca_bot.xlsx
```

## Rules and Conventions
### Always
- Write code, comments, commit messages, and documentation in English.
- Write every message the bot sends in Spanish (the audience is in Costa Rica).
- Use only information from the Excel. If it is not there, the bot says it does not know and offers the handoff.
- Add tests whenever a new function is created.
- Keep secrets (Meta token, app secret, Gemini key, Google credentials) in environment variables, never in the repository. Document them in `.env.example`.

### Never
- Modify files inside `.claude` without asking first.
- Invent data, prices, or sources.
- Install new dependencies without telling me first.
- Use paid tools or services. Check for a free tier before proposing anything.
- Use emojis or double hyphens (`--`) in the bot's messages. Customers may use them in their own messages.
- Mention business-only details from the Bosca context (for example, that the mechanisms use paper strips) unless the Excel includes them.

### When in Doubt
- Ask before acting if the task is ambiguous.
- If a technology, service, or tool comes up that is not listed here, ask me before using it.

## Response Style
- **Language:** Spanish (conversation with me), English (code and docs)
- **Tone:** Friendly and technical
- **Length:** Detailed, maximum 500 words
- **Format:** Lists, tables, and code blocks where they help

## Important Context
- Bosca sells laser-made wooden pieces, with music boxes as the highlight. Every music box comes with a 15 note or a 30 note mechanism; the 30 note box is larger and plays more of the melody. The website shows no prices and quotes everything on request.
- Market: Costa Rica only for now.
- The owner answers customers personally on the same number, so the bot and the owner share conversations.

## Notes
### Security
- Verify every webhook call: the `hub.verify_token` handshake and the `X-Hub-Signature-256` signature with the Meta app secret. Reject anything that fails.
- Meta may deliver the same message more than once. Deduplicate by message ID so the bot never replies twice.
- Treat customer messages as untrusted input. They must not change the bot's scope, rules, or mode (prompt injection).
- Rate limit replies per customer to protect the Gemini quota and avoid spam loops.
- Collect and log the minimum personal data needed. Do not log full conversations unless the owner asks.

### Gemini free tier
- It has rate limits. When they are hit, the bot falls back to rule mode (see AI unavailable in Decisions Made).
- Under the free tier, Google may use prompts and responses to improve its products, so customer messages could be reviewed by Google. The owner accepted the free tier; revisit this if privacy becomes a concern.

### Owner notification and the 24 hour window
- Sending a WhatsApp message to +506 7141 3393 is free only while that number has an open 24 hour window, which means it wrote to the business number in the last 24 hours. Outside that window Meta requires a paid template message, which this project never uses.
- **Decided (option A):** the owner sends any message from +506 7141 3393 to the business number at least once a day to keep the window open. A command counts too. Archiving the chat on the owner's phone does not matter for sending.
- The bot keeps the time of the last message from +506 7141 3393. If the window is closed when a handoff happens, the notification is **not sent**: the customer still gets the "pronto te atenderán" reply and the request is still logged in the Excel requests sheet.
- Archived chats: the bot's notifications still arrive in an archived chat, but if the WhatsApp setting "Mantener chats archivados" is on, the chat stays archived and the owner may not notice them.

### Writing to the Excel
- The `.xlsx` lives on Drive, so each write replaces the whole file. If the owner edits it at the same time, or two requests arrive together, changes can be lost. Serialize writes inside the bot, re-download right before writing, and keep the requests sheet separate from the sheets the owner edits.
- The service account needs edit access to the file, not only read access.

### Serverless hosting
- On Vercel there is no persistent memory between requests. The current mode, the menu position of each customer, the handoff pauses, and the owner's 24 hour window would be lost. This must be solved before production (see Open Questions).

## Open Questions
- **Where to keep state** (current mode, handoff pauses, owner's last message time) if the production host is serverless like Vercel. Locally it is saved in `data/state.json` (`STATE_FILE`), which a serverless host cannot keep. **Ask the owner when building it**, explaining the options in plain Spanish. Not a problem while the bot runs on the owner's computer.
- **Excel design:** a provisional layout is built (see Current Progress). The owner will explain the final design in a later session; adjust `bot/knowledge.py` and `bot/template.py` together.
- **Coexistence onboarding (checked against Meta's docs on 2026-10-19):**
  - Coexistence only works through **Embedded Signup** (Facebook Login for Business, a `config_id`, the JS SDK on an HTTPS page listed in Allowed domains). Meta's guide lists being a Solution Partner or Tech Provider as a prerequisite, but Embedded Signup also runs in development mode for the app's own admins. **Not confirmed** that a non-partner can onboard its own number; path 1 tests exactly that.
  - Embedded Signup v2 and v3 were deprecated on 2026-10-15. In v4 the products (including WhatsApp Business app onboarding) are chosen in the Login configuration and `extras` is empty; `bot/signup.py` still sends `featureType: whatsapp_business_app_onboarding` in case it is honored. Exact v4 UI labels not verified.
  - Costa Rica (+506) is not on any unsupported country list. WhatsApp Business app version 2.24.17+ is required (the owner's app is freshly installed from the Play Store).
  - After onboarding: skip number registration, subscribe the app to the WABA, and start the contacts and history sync within 24 hours (each only once).
  - Meta disconnects the number after about **14 days without opening the app on the main phone** (`account_update`, `PARTNER_REMOVED`, `PRIMARY_INACTIVITY`). Meta documents no way to prevent it. Restarting the bot does **not** reconnect it: the owner has to repeat the `/signup` flow (set `SIGNUP_KEY` again). The owner wants to avoid it; the bot logs these events, and a reminder is proposed (see Not done).
  - The bot needs a permanent token (System User in Business Settings) instead of the 24 hour token, and the app probably has to be in Live mode to receive real customers' webhooks, which needs a privacy policy URL. The owner has a web app where they can publish it.
  - **Bosca is not legally registered** (2026-10-20), so the Tech Provider fallback (business verification) may not be possible yet.
- **Gemini model and free tier limits:** `GEMINI_MODEL=gemini-3.5-flash-lite` in `.env.example`. Free tier availability and limits for current models were not confirmed from an official Google page; check the live quota in AI Studio.
- **Production host:** to be decided later (Vercel or similar). The owner will stop using ngrok once the bot is hosted; then the webhook callback URL, the Facebook Login Allowed domains and `Por hacer.txt` must move to the new domain.

## Current Progress
Last updated: 2026-10-20.

### Built and verified
- Full bot as described in Goal, Decisions Made and Admin Commands: webhook handshake and signature check, dedup by message ID, admin commands before any engine, rule engine, AI engine with automatic per-message fallback, handoff (customer reply, owner notification only inside the 24 hour window, row in `Solicitudes`, 60 minute pause), per-customer rate limit, outgoing sanitizer.
- 155 pytest tests passed in the first version (`pytest`). They use fakes, so no real Meta, Gemini or Drive call has been made yet.
- The real server was started with uvicorn and a local Excel: `/health`, the verify handshake, a signed webhook (handoff row written to the Excel) and a rejected bad signature (403) all worked.

- **Added 2026-10-16 (owner request):** the state that matters after a restart (mode, active pauses, owner's last message time) is saved to `data/state.json` and restored at startup; the saved mode wins over `BOT_MODE`. When the owner writes to a customer from the WhatsApp Business app (`smb_message_echoes` webhook, coexistence only), the bot pauses with that customer for `HANDOFF_PAUSE_MINUTES` from the owner's last message and clears its AI history.
- **174 pytest tests pass** after these changes.
- **Added 2026-10-18:** ngrok replaces cloudflared; `scripts/start.sh` with 8 tests (fake uvicorn and ngrok). **183 tests pass.**
- **2026-10-19:** the owner confirmed that AI mode and menu mode both work end to end with Meta's test number.
- **Added 2026-10-20 (real number, path 1):** `bot/signup.py` with `GET /signup?key=` (page with the Embedded Signup button) and `POST /signup/complete` (code exchange, `subscribed_apps`, contacts and history sync, no registration). Both answer 404 unless `META_APP_ID`, `SIGNUP_CONFIG_ID` and `SIGNUP_KEY` (32+ chars) are set and the key matches. The business token is used only for those calls and never stored, logged or returned. `account_update` webhooks are logged as warnings. **213 tests pass.** Not yet run against Meta.

### Design choices made in this session (change if the owner disagrees)
- **Excel layout (provisional):** sheets `Instrucciones`, `Productos`, `Preguntas`, `Menu`, `Mensajes`, `Solicitudes`, with Spanish headers matched ignoring case and accents. The template contains the menu from CLAUDE.md (1 Cajas musicales, 2 Otros productos, 3 Hablar con una persona) and the bot's default messages, but no products, prices or policies.
- **Bot messages:** defaults live in `DEFAULT_MESSAGES` (`bot/knowledge.py`) and the `Mensajes` sheet overrides them. They use "tú".
- **AI:** structured JSON output (`action`: answer, handoff, off_topic). Off-topic replies always use the Excel's `fuera_de_tema` text, not the model's text. Conversations are not stored on Google's side (`store=False`); the last 10 turns are kept in memory for 30 minutes.
- **Rule mode:** a menu number picks an option; otherwise the longest matching keyword wins (menu, then questions, then product names and keywords); a greeting or the first message in 12 hours shows the welcome and menu; anything else gets `no_entiendo` plus the menu (which includes the handoff option).
- **Media messages** (photos, audio, stickers) get the `solo_texto` reply. Reactions, status updates and `smb_message_echoes` are ignored.
- `#bosca menú` (with accent) is accepted as the same command as `#bosca menu`.
- If the Excel never loaded, every customer message goes to handoff, so nobody gets silence.

### Not done
- **Real number onboarding (path 1):** pending Meta dashboard steps by the owner (Facebook Login for Business configuration, Allowed domains with `NGROK_DOMAIN`, `account_update` / `history` / `smb_app_state_sync` / `smb_message_echoes` webhook fields), back up the WhatsApp Business chats, run `/signup`, create the System User permanent token, switch `WHATSAPP_PHONE_NUMBER_ID`, publish the privacy policy and set the app to Live, then clear `SIGNUP_KEY`.
- **14 day inactivity reminder: declined for now (2026-10-20, temporary).** The owner does not want the bot to remind them to open WhatsApp Business yet; ask again later. A disconnection alert was also proposed and not built.
- **`Por hacer.txt`** (project root, Spanish, for the owner): the steps to connect the real number and the reconnection steps after a disconnect. Keep it in sync when those steps change, including when ngrok is replaced by a host.
- Drive service account status not confirmed. `cloudflared` was installed earlier but is no longer used.
- The owner-reply pause cannot be tested with Meta's test number; verify it after the coexistence onboarding.
- **Owner's 24 hour window:** the owner asked whether the bot could send the daily message from the owner's number automatically after a restart. It cannot (the bot only controls the business number, and messaging the owner first needs a paid template). Saving the state to a file solved the restart part; the owner still writes once a day, optionally with a phone automation such as iPhone Shortcuts.

