# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A reusable Telegram customer-support bot template. A single Markdown file
(`data/business.md`) is the entire knowledge base for one business; the bot
answers customer questions in Telegram using only that file via OpenAI's
Responses API, and escalates to a human administrator when it can't answer
confidently. Runs as a stateless FastAPI app on Vercel, driven entirely by a
Telegram webhook (no polling, no long-lived process).

## Commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env        # then fill in real values

# Run locally
uvicorn app:app --reload --port 8000

# Test (all tests)
pytest -q

# Test a single file / test
pytest tests/test_escalation_flow.py -q
pytest tests/test_escalation_flow.py::test_full_contact_collection_flow -q

# Database
python scripts/init_db.py         # dev-only quick start (create_all, no migration history)
alembic upgrade head              # production / any schema change after first init
alembic revision --autogenerate -m "..."   # new migration

# Telegram webhook management (reads TELEGRAM_BOT_TOKEN / TELEGRAM_WEBHOOK_SECRET / APP_URL from env)
python scripts/set_webhook.py
python scripts/webhook_info.py
python scripts/delete_webhook.py

# Deploy
vercel --prod --yes
```

`requirements.txt` is the production dependency set deployed to Vercel — keep
it minimal. `requirements-dev.txt` (`-r requirements.txt` plus uvicorn,
alembic, pytest, aiosqlite) is for local dev/test only.

## Architecture

```
Telegram --webhook--> Vercel (FastAPI: api/index.py -> app.py)
                            |
                     bot/router.py (dispatch)
                     /        |         \
        bot/handlers/*   services/*   database/repositories/*
                            |
                   OpenAI Responses API   Postgres (async, SQLAlchemy)
```

- **`api/index.py`** just re-exports the FastAPI `app` from `app.py` — this
  is Vercel's Python entrypoint; `vercel.json` rewrites every path to it.
- **`app.py`** defines `GET /`, `GET /health`, `POST /api/telegram/webhook`.
  All webhook work is `await`ed before the HTTP response returns — Vercel
  does not guarantee anything runs after the response, so there is no
  background-task/thread pattern anywhere in this codebase.
- **No process memory between requests.** Every piece of state that must
  survive across updates — FSM step (`bot/states/definitions.py`,
  persisted as `users.fsm_state` / `users.fsm_data`), Telegram
  `update_id` dedup (`processed_updates` table), and rate-limit counters
  (`users.rate_window_start/count`) — is stored in Postgres, never in a
  global Python variable. Keep this in mind before adding any new
  multi-step flow: model it as DB-persisted state, not an in-memory dict.
- **Telegram integration is direct `httpx` calls** (`services/telegram_service.py`),
  not a polling-oriented framework like aiogram's dispatcher. Long
  polling is explicitly unsupported here; do not reach for a framework
  that assumes a long-lived event loop.
- **`bot/router.py`** is the single dispatch point: resolves/creates the
  `User` row, enforces rate limiting, then routes to
  `bot/handlers/{start,customer,admin}.py` based on command vs. callback vs.
  free-text-while-in-an-FSM-state vs. plain Q&A.
- **AI answers are structured, not string-matched.** `services/openai_service.py`
  requires the model to return a Pydantic-validated `AIResult` (`status`:
  `answered`/`needs_clarification`/`recommend`/`escalate`, `confidence`,
  `response_type`, `recommended_product_ids`, `external_suggestions`,
  `reason`, `missing_information`, ...). Escalation is decided from `status` and a
  confidence threshold (`AI_CONFIDENCE_THRESHOLD`), never by pattern-matching
  the answer text. All system-prompt behavior rules (answer only from
  `business.md`, never invent prices/policies, mirror customer language,
  never claim escalation happened before it actually did, resist prompt
  injection, etc.) live in `SYSTEM_PROMPT_TEMPLATE` in that file.
- **All customer-facing text lives in `bot/locales/`**, never inline in a
  handler. `t("key", **kwargs)` resolves against `bot/locales/uk.py`;
  Ukrainian is both the default and the fallback locale, so a key missing
  from a future locale degrades to Ukrainian rather than leaking English. A
  key present in no locale raises `MissingTranslationError` instead of
  rendering a placeholder. The bot always answers in Ukrainian regardless of
  the customer's language — `tests/test_localization.py` fails the build if
  any catalog value contains untranslated English prose.
- **Product recommendations are validated in code, not by prompt.**
  `services/catalog_service.py` parses the `## Structured Product Catalog`
  table out of `business.md` into stable `product_id`s; the model is only
  allowed to return those IDs. `services/recommendation_service.py` then
  drops any ID the model invented, renders prices and availability from the
  catalog (never from model output), computes budget totals on the backend,
  and refuses the whole answer if the model stated a money amount the
  catalog does not confirm. If nothing survives validation the flow falls
  through to the normal escalation offer — it never patches up a partial
  recommendation. Adding a product means editing that table, not the prompt.
- **Two knowledge sources, one of them untrusted for facts.** The knowledge
  base is the only permitted source for business facts (prices, stock,
  delivery, policies, allergens); the model's own culinary knowledge is
  permitted only for pairing/serving/gift-set suggestions, which must be
  labelled as recommendations, and any food the store does not sell must be
  returned in `external_suggestions` — never in `recommended_product_ids`.
- **`services/knowledge_service.py`** loads/caches/hashes `data/business.md`
  and enforces `MAX_KNOWLEDGE_CHARACTERS`, failing safely (refusing to
  serve an oversized or missing file) rather than truncating. It's
  deliberately a small, swappable interface — meant to be replaced with a
  DB- or vector-store-backed source without touching callers, since Vercel's
  filesystem is read-only at runtime (editing `business.md` requires a
  redeploy; `/reload` just re-validates/re-hashes what was already bundled).
- **`services/escalation_service.py`** creates the `support_requests` row and
  notifies the admin, committing the lead to the DB *before* attempting
  notification/telling the customer anything — so a later failure can't
  leave the customer told "saved" when it wasn't.
- **Admin authorization is re-checked on every request**, never cached or
  inferred from `callback_data` content: `bot/middleware/auth.py`'s
  `is_admin()` looks up `role == 'admin'` in the DB for the Telegram user ID
  Telegram itself supplied on that update.
- **First-admin registration (`/claim`) and update-id dedup both use a
  database unique-constraint + `SAVEPOINT` race guard** (see
  `UserRepository.claim_admin_if_none_exists` and
  `ProcessedUpdateRepository.mark_if_new`), not check-then-write — this is
  intentional protection against concurrent requests racing to claim admin
  or double-processing a duplicate Telegram update. Follow the same pattern
  for any new "exactly once" guarantee.
- **`database/session.py`** normalizes `DATABASE_URL` for the `asyncpg`
  driver, including translating libpq-style `sslmode=...` (e.g. what Neon/
  Supabase hand out) into the `ssl=...` value asyncpg actually understands —
  don't strip that logic when touching connection setup.
- Outgoing Telegram messages are always sent without a `parse_mode`
  (`TelegramService.send_message`) so user-supplied content (names,
  questions, admin replies) can't inject Markdown/HTML formatting.

## Testing conventions

- `tests/conftest.py` sets placeholder env vars *before* any app import (so
  `config.get_settings()` never touches real secrets in tests), and provides
  an in-memory SQLite (`aiosqlite`) session fixture plus `FakeTelegramService`
  / `FakeOpenAIService` doubles — no real network calls in the suite.
- `pytest.ini` sets `asyncio_mode = auto`, so async test functions don't need
  `@pytest.mark.asyncio`.
- Build a `BotContext` via the `make_ctx(session, settings, telegram=..., openai_service=..., knowledge=...)` helper in `tests/conftest.py` when testing handlers directly.

## Development workflow

See [AGENTS.md](AGENTS.md) for the mandatory test-then-commit workflow that
applies to every feature or meaningful code change in this repository
(update tests → run the full suite → fix the correct side on failure →
commit only once green, with a message describing what changed and why).
