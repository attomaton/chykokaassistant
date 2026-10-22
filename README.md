**Also available in:** [Русский](README.ru.md)

# Telegram Business Assistant

A reusable, production-ready Telegram customer support bot template. Each
deployment is configured for a single business via a Markdown knowledge base
(`data/business.md`) and answers customer questions using OpenAI's Responses
API, grounded strictly in that file. Runs as a stateless FastAPI app on
Vercel, driven entirely by a Telegram webhook.

## 1. Project overview

- Customers ask questions in Telegram; the bot answers using only
  information in `data/business.md`.
- When the AI is not confident, or information is missing, the bot honestly
  says so and offers to collect the customer's contact details for a human
  follow-up (a "lead").
- The registered administrator receives every escalated request in Telegram,
  can reply through the bot, and can mark requests resolved.
- All state (conversations, leads, FSM step, dedup) lives in Postgres, not
  in process memory, because serverless functions are stateless.

## 2. Architecture

```
Telegram  --webhook-->  Vercel (FastAPI, api/index.py -> app.py)
                              |
                              v
                     bot/router.py (dispatch)
                     /        |         \
        bot/handlers/*   services/*   database/repositories/*
                              |
                     OpenAI Responses API   Postgres (async, SQLAlchemy)
```

- **api/index.py** - Vercel's Python entrypoint; just re-exports the FastAPI
  `app` from `app.py`.
- **app.py** - FastAPI app: `GET /`, `GET /health`, `POST
  /api/telegram/webhook`. All webhook processing is awaited synchronously
  before the HTTP response is returned (Vercel does not guarantee background
  work continues after the response).
- **bot/** - Update dispatch (`router.py`), command/callback handlers,
  inline keyboards, and the FSM state constants. Conversation "state" (e.g.
  "collecting customer's phone number") is persisted on the `users` row
  (`fsm_state` / `fsm_data`), never in memory, because a warm Vercel
  instance may not receive the next update for a given user.
- **services/** - `knowledge_service.py` (loads/caches `business.md`),
  `openai_service.py` (Responses API + structured output validation),
  `telegram_service.py` (direct `httpx` calls to the Bot API, no
  polling/framework), `escalation_service.py` (lead creation + admin
  notification), `validation.py` (name/phone/email checks).
- **database/** - Async SQLAlchemy models and repositories. Postgres in
  production, SQLite (aiosqlite) in tests.

Telegram is integrated via direct `httpx` calls rather than a
polling-oriented framework (e.g. aiogram's dispatcher), because polling is
explicitly unsupported on Vercel and a framework's built-in FSM storage
typically assumes long-lived process memory, which serverless does not
provide.

## 3. Local installation

### Python version

Python 3.11 or 3.12.

### Install

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Fill in `.env` with real values (see section 5).

## 4. Environment variables

See `.env.example` for the full list with descriptions. Required:
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `OPENAI_API_KEY`,
`DATABASE_URL`. Everything else has a safe default or is optional
(`ADMIN_SETUP_SECRET` / `ADMIN_TELEGRAM_ID` control administrator
bootstrap - see section 12).

Never commit `.env`. It is already excluded via `.gitignore`.

## 5. Database setup

Use any Postgres instance; a connection-pooling provider (Neon, Supabase,
or RDS Proxy) is strongly recommended because serverless functions open many
short-lived connections (the app uses `NullPool` on the Python side for the
same reason - it does not hold connections open between invocations).

Quick start (dev only, see limitations below):

```bash
python scripts/init_db.py
```

Production / anything beyond local quick-start - use Alembic:

```bash
alembic upgrade head
```

`scripts/init_db.py` only calls `Base.metadata.create_all`: it has no
migration history and will not alter a table that already exists. Once you
have run it once, use Alembic (`alembic revision --autogenerate -m "..."`
then `alembic upgrade head`) for any further schema change.

## 6. Editing `data/business.md`

This file is the bot's entire knowledge base and is sent to the model in
full on every question (subject to `MAX_KNOWLEDGE_CHARACTERS`, default
80,000). Structure it with clear Markdown headings - see the shipped
example for the expected sections (products/prices, delivery, payment,
hours, address/contact, FAQ, returns/warranty).

- Keep it accurate: the model is instructed to answer *only* from this file
  and to escalate rather than guess when something is missing.
- On Vercel the file is bundled into the deployment at build time, so
  editing it requires a redeploy - `/reload` (admin-only) re-validates and
  re-hashes the in-memory cache, but cannot pull in content Vercel did not
  bundle.
- If your knowledge base grows past `MAX_KNOWLEDGE_CHARACTERS`, this
  template will refuse to start answering with it (fails safely) rather
  than silently truncating your business information. At that point, add
  retrieval (RAG): the `KnowledgeService` interface (`services/
  knowledge_service.py`) is deliberately small so it can be replaced with a
  vector-store or database-backed retriever without touching callers.

### The structured product catalog

`data/business.md` also contains a `## Structured Product Catalog` table.
That table is the **only** list of products the bot can recommend, and it is
parsed programmatically by `services/catalog_service.py`:

| Column | Meaning |
|---|---|
| `product_id` | Stable ID the model must use; never rename an existing one |
| `Назва` | Display name shown to the customer |
| `Ціна` | Confirmed price in UAH, or `невідомо` if not confirmed |
| `Наявність` | `в наявності`, or `невідомо` if stock is not confirmed |
| `Категорія`, `Теги` | Used to match products to a customer's request |

To add or change a product, edit this table - not the prompt. Prices and
availability shown to customers always come from here, and any product the
model invents is dropped before the reply is sent.

## 6a. Language and recommendations

The customer interface is **Ukrainian by default**, and the bot answers in
Ukrainian even when the customer writes in another language. All
customer-facing text lives in `bot/locales/uk.py` and is resolved with
`t("key")` - never hardcode a customer-visible string in a handler. Adding a
locale means adding a module to `bot/locales/` and registering it in
`LOCALES`; Ukrainian remains the fallback for any missing key.

The assistant works from two sources with different trust levels:

- **Business facts** (products, prices, stock, delivery, payment, contacts,
  ingredients, allergens, promotions, policies) come *only* from
  `data/business.md`. These are never generated.
- **Culinary recommendations** (flavour and texture pairings, serving ideas,
  tea/coffee matches, gift-set concepts) may use the model's general
  knowledge, and are presented to the customer as suggestions.

Recommendations are validated on the backend, not trusted from the model:
invented product IDs are dropped, prices and totals are computed from the
catalog, foods the store does not sell are labelled as external suggestions,
and a recommendation that survives none of this falls through to the normal
escalation flow instead of being shown.

## 7. Run locally

```bash
uvicorn app:app --reload --port 8000
```

Telegram cannot reach `localhost` directly; use a tunnel (e.g. `ngrok http
8000`) and point `APP_URL` at the tunnel URL, then run
`scripts/set_webhook.py` (see section 11). Alternatively, POST a sample
Telegram update JSON directly to `http://localhost:8000/api/telegram/webhook`
with the `X-Telegram-Bot-Api-Secret-Token` header set to your
`TELEGRAM_WEBHOOK_SECRET` for manual testing without a tunnel.

## 8. Test locally

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
```

With a coverage report:

```bash
pytest --cov=. --cov-report=term-missing
```

Tests use an isolated in-memory SQLite database and fake Telegram/OpenAI
service doubles - no network calls, no real credentials required (the test
suite sets harmless placeholder env vars itself via `tests/conftest.py`).
See [AGENTS.md](AGENTS.md) for the permanent testing rule that applies to
every change in this repository.

## 9. Deploy to Vercel

1. Push this repository to GitHub/GitLab/Bitbucket and import it in Vercel,
   or run `vercel` from the project root with the Vercel CLI.
2. In **Project Settings -> Environment Variables**, add every variable
   from `.env.example` for the Production environment (and Preview, if you
   use preview deployments) - paste real values, never commit them.
3. Deploy. Vercel detects `api/index.py` as a Python (FastAPI) serverless
   function; `vercel.json` rewrites all paths to it so `/`, `/health`, and
   `/api/telegram/webhook` are all served from the same app.
4. Run your database migrations against the production database (`alembic
   upgrade head`) from your machine or CI - Vercel does not run migrations
   for you.

## 10. Configure the production webhook

After deployment, with `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, and
`APP_URL` set in your local shell (matching the Vercel values):

```bash
python scripts/set_webhook.py
```

Verify:

```bash
python scripts/webhook_info.py
```

To remove the webhook (e.g. to switch back to manual testing):

```bash
python scripts/delete_webhook.py
```

## 11. Claim the administrator role

Two options:

- **Automatic**: set `ADMIN_TELEGRAM_ID` (your numeric Telegram user ID,
  from e.g. @userinfobot) in the environment before first deploy/first
  webhook call. That account is installed as administrator automatically
  and `/claim` is permanently disabled.
- **Manual, one-time**: set `ADMIN_SETUP_SECRET` to a long random value
  (`python -c "import secrets; print(secrets.token_urlsafe(24))"`), deploy,
  then message the bot `/claim <that secret>` from the Telegram account you
  want as administrator. The first successful claim permanently registers
  that account and all further `/claim` attempts are rejected - this uses a
  database-level unique-constraint race guard, so it is safe even if two
  people race to claim at the same moment.

## 12. Rotate leaked Telegram/OpenAI keys

- **Telegram**: message @BotFather -> `/revoke` (or `/token`) for your bot
  to invalidate the old token and issue a new one. Update
  `TELEGRAM_BOT_TOKEN` in Vercel, redeploy, then re-run
  `scripts/set_webhook.py` (the webhook registration is tied to the token).
- **OpenAI**: revoke the key in the OpenAI dashboard, generate a new one,
  update `OPENAI_API_KEY` in Vercel, redeploy. No further action needed.
- **Webhook secret**: generate a new `TELEGRAM_WEBHOOK_SECRET`, update it in
  Vercel, redeploy, then re-run `scripts/set_webhook.py` so Telegram starts
  sending the new secret header.
- After rotating any secret, confirm `python scripts/webhook_info.py`
  reports no pending errors.

## 13. Troubleshooting

- **Bot doesn't respond**: check `python scripts/webhook_info.py` for
  `last_error_message`; confirm `APP_URL` matches your actual Vercel
  deployment URL and that the webhook was set after the latest deploy.
- **401 from the webhook endpoint**: `TELEGRAM_WEBHOOK_SECRET` mismatch
  between Vercel and what was passed to `set_webhook.py` - they must be
  identical.
- **`/health` reports `database: false`**: check `DATABASE_URL` and that
  your Postgres provider allows connections from Vercel's egress IPs (or
  use a pooler that doesn't IP-restrict).
- **Duplicate replies to the same message**: check for multiple webhooks
  registered (`webhook_info.py`) or that you haven't deployed two bots on
  the same token.
- **Admin never receives escalations**: confirm an administrator is
  actually registered (`/stats` as the admin, or check the `users` table
  for `role = 'admin'`); if none exists, all escalations are saved as
  `pending` but never delivered (by design - nothing is dropped).

## 14. Security notes

- No secret is ever hardcoded; all are read from environment variables
  (`config.py`).
- The webhook validates Telegram's `X-Telegram-Bot-Api-Secret-Token` header
  before doing anything else.
- All admin commands/callbacks re-check the caller's Telegram ID against the
  database `role = 'admin'` on every request - `callback_data` content is
  never trusted as proof of privilege.
- The first-administrator claim is guarded by a database unique-constraint
  (not a check-then-write race) so it cannot be won twice, even under
  concurrent requests.
- All outgoing Telegram messages are sent without a `parse_mode`, so
  user-supplied content (names, questions, admin replies) cannot inject
  Markdown/HTML formatting or links.
- All SQL access goes through SQLAlchemy's parameterized query builder -
  no raw string-interpolated SQL anywhere in the codebase.
- Basic per-user rate limiting and message-length limits are enforced
  before any OpenAI call.
- Logging never includes full secrets, full update payloads, or full
  customer message content in error logs - only IDs and short reasons.

## 15. Known Vercel / serverless limitations

- **No background work after the response.** The webhook handler awaits all
  processing (DB writes, Telegram sends, OpenAI calls) before responding;
  there is no reliable background task or long-lived thread on Vercel.
  Function timeout is configured via `vercel.json`
  (`functions.api/index.py.maxDuration`) - raise it if your plan allows and
  your OpenAI/Telegram calls are slow.
- **Read-only filesystem at runtime.** `data/business.md` is bundled at
  build time; there is no way to persist edits to it from a running
  function. To change content without a redeploy, replace
  `KnowledgeService` with a database- or object-storage-backed source.
  This is why `KnowledgeService` is a swappable component.
- **No process memory across requests.** Every piece of state that must
  survive between updates (FSM step, dedup of `update_id`, rate-limit
  counters) is stored in Postgres, never in a global Python variable.
- **Cold starts** add latency to the first request after idle periods;
  OpenAI/Telegram timeouts are configured generously
  (`OPENAI_TIMEOUT_SECONDS`, `TELEGRAM_TIMEOUT_SECONDS`) to tolerate this,
  but very slow cold starts combined with a slow OpenAI response can still
  hit the function's `maxDuration`.
- **Connection limits.** Many concurrent serverless invocations each open a
  short-lived Postgres connection; use a pooling-capable provider or you
  may exhaust `max_connections` on the database under load.

## Project structure

```
project-root/
├── app.py                     FastAPI app (routes, webhook)
├── api/index.py                Vercel entrypoint (re-exports app)
├── config.py                   Pydantic Settings (env vars only)
├── bot/
│   ├── router.py                Update dispatch
│   ├── context.py                Shared per-request context
│   ├── handlers/                 start / customer / admin command+callback logic
│   ├── keyboards/                 Inline keyboard builders
│   ├── middleware/                 Admin auth check, rate limiting
│   └── states/                      FSM state constants
├── services/
│   ├── openai_service.py           OpenAI Responses API + structured output
│   ├── knowledge_service.py        business.md loader/cache
│   ├── telegram_service.py         Direct Telegram Bot API client (httpx)
│   ├── escalation_service.py       Lead creation + admin notification
│   └── validation.py                Name/phone/email validators
├── database/
│   ├── models.py                    SQLAlchemy models
│   ├── session.py                    Async engine/session factory
│   └── repositories/                  One repository per table
├── data/business.md                 Example knowledge base
├── scripts/
│   ├── set_webhook.py / delete_webhook.py / webhook_info.py
│   └── init_db.py                    Dev-only quick-start schema creation
├── alembic/                        Migrations (production schema changes)
├── tests/                          Pytest suite (mocks OpenAI/Telegram)
├── .env.example
├── requirements.txt                 Production deps (kept lightweight)
├── requirements-dev.txt             + test/local-dev tooling
└── vercel.json
```
