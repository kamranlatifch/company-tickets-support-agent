# Cogent Support Chat

Customer support chat with RAG-backed answers and human-in-the-loop ticket
escalation. Built as a standalone project — no dependency on the Week1-4
training repo.

## What it does

- Customers log in and chat; confident, low-stakes questions get answered
  directly from a KB (Chroma + OpenRouter embeddings)
- Anything urgent, angry, billing-related, low-confidence, or explicitly
  asking for a human becomes a ticket (hardcoded policy gate — the model
  never decides this itself)
- Admin reviews tickets in a separate dashboard, assisted by the model
  (draft → feedback → redraft → approve, via LangGraph interrupt/resume)
- Resolution gets emailed to the customer (Brevo)

## Project structure

```
cogent-support-chat/
├── app.py                    # Streamlit customer chat (entry point)
├── pages/1_Admin_Dashboard.py
├── config.py                 # env vars, paths, thresholds
├── auth.py + users.yaml      # login (email/password/role) — committed: demo accounts, plain-text passwords
├── schemas.py                # Pydantic models
├── policy.py                 # hardcoded escalation gate
├── agents.py                 # Pydantic AI: assess_message, draft_ticket_reply
├── tools.py                  # KB search / account / ticket / email wrappers
├── turso_db.py                # ticket + account storage (Turso/libSQL)
├── email_client.py           # Brevo (stubs/logs if no key set)
├── review_graph.py           # LangGraph interrupt/resume — admin review loop
├── rag/                      # extract -> chunk -> embed -> store -> retrieve -> answer
├── data/kb/                  # KB source docs; the *.pdf files are gitignored (internal), only example .md files are tracked
└── index/                    # Chroma index — committed (Cloud deploy needs it); rebuild with `python3 -m rag.ingest`
```

## Setup

```bash
cd cogent-support-chat
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

| Variable | Where to get it |
|---|---|
| `COGENT_OPRNROUTER_KEY` | Same OpenRouter key used elsewhere — note the spelling: `OPRN`, not `OPEN` |
| `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` | Free at [turso.tech](https://turso.tech): `turso db create cogent-support`, then `turso db show cogent-support --url` and `turso db tokens create cogent-support` |
| `BREVO_API_KEY` / `BREVO_FROM_EMAIL` / `BREVO_FROM_NAME` | Free tier (300/day) at [brevo.com](https://www.brevo.com) — add and **verify a sender** under Senders, Domains & Dedicated IPs, then create a key under SMTP & API > **API Keys** (must start with `xkeysib-`; the `xsmtpsib-` SMTP keys don't work). A Gmail sender works with no DNS setup; a company-domain sender with a strict DMARC policy needs the domain authenticated in Brevo first |
| `LOGFIRE_TOKEN` | Optional — leave blank to disable tracing, no code changes needed |

Then initialize storage and the KB index:

```bash
python3 -c "from turso_db import init_schema; init_schema()"
python3 -m rag.ingest
```

Run locally:

```bash
streamlit run app.py
```

Customer chat at `http://localhost:8501`, admin dashboard under the
"Admin Dashboard" page in the sidebar.

## Accounts

`users.yaml` (login credentials) is committed to this public repo on purpose, so logins
work on a deploy. Those are demo accounts with plain-text passwords — treat them as
public and change them before any real use. Account *profile* data (name, tier,
plan — used by the escalation policy for VIP-tier detection) lives in Turso,
not YAML — insert rows via `turso_db.upsert_account()` for any customer you
want tier-based escalation to apply to.

## What's genuinely verified vs. what needs your credentials to prove out

Verified locally while building this (see commit history / build notes):
- Full assess → policy → RAG-answer path (real LLM calls)
- Full LangGraph interrupt → redraft-on-feedback → finalize-on-approve cycle
- RAG ingest → retrieve, against the example KB docs
- Both Streamlit pages boot without import errors
- `turso_db.py`'s API calls were checked against the actual installed
  `libsql-client` package's signatures, not guessed. Note it connects over
  `https://` (`libsql://` websockets get a 400 from Turso) — `get_client()` swaps the scheme.

Needs your real Turso + Brevo accounts to verify end-to-end (I can't
create third-party service accounts on your behalf):
- Actual ticket persistence across sessions
- Actual email delivery on resolution

## Why LangGraph only wraps the admin review loop, not the whole ticket lifecycle

The customer-to-admin handoff can span arbitrary real time and two different
people — that's fundamentally a queue, not an agent execution to pause.
Turso + polling (`st.fragment`) owns that. The admin's own
assess→draft→feedback→approve loop is a single person, single sitting, tight
iterative cycle — the actual shape LangGraph's `interrupt()`/checkpointer
pattern is built for — so that's the one place it's used. Forcing
LangGraph's checkpointer to span the customer wait too would mean swapping
Turso for Postgres just to host graph state, for zero behavioral gain.

## Deploying to Streamlit Cloud

**This repo is public, and the pre-built Chroma index (`index/`) and `users.yaml` are
committed to it on purpose.** Streamlit Cloud's checkout is read-only, so the index
can't be built at runtime; it's built locally, committed, and `rag/store.py` copies it
into a writable temp dir when it detects Cloud. The source PDFs (`data/kb/*.pdf`) are
gitignored — they aren't needed at runtime. Because the index stores each chunk's text,
**the policy content is publicly readable in this repo**.

`chromadb` is pinned in `requirements.txt` to the version that built the index (its
on-disk format changes between releases) — if you upgrade it, re-run the ingest below
and commit the new `index/`. In the deploy form, pick the branch that has the code
(`develop`, unless it's been merged to `main`), set the main file to `app.py`, and
choose Python 3.12 under Advanced settings.

Turso and Brevo are network services, so they need no special Cloud handling — paste
the same `.env` values into Streamlit's Secrets (TOML format) when deploying.

**Every time `data/kb/` changes:**

```bash
python3 -m rag.ingest      # rebuild the index (fresh embeddings)
git add index/
git commit -m "Update KB index"
git push
```

## Security notes (demo only)

- Passwords in `users.yaml` are plain text — fine for a demo, not production
- `users.yaml` is committed to a public repo, so its passwords are public — demo accounts only
- `index/` is committed to a public repo, so the KB's policy text is public too
- Never commit `.env` or the KB PDFs
