# Cogent Support Chat

Customer support chat with RAG-backed answers and human-in-the-loop ticket
escalation. Built as a standalone project — no dependency on the Week1-4
training repo.

## What it does

- Customers log in and chat; confident, low-stakes questions get answered
  directly from a KB (Chroma + OpenRouter embeddings)
- Anything urgent, billing-related, low-confidence, about the customer's own
  records, or explicitly asking for a human becomes a ticket (hardcoded policy gate — the model
  never decides this itself)
- Admin reviews tickets in a separate dashboard, assisted by the model
  (draft → feedback → redraft → approve, via LangGraph interrupt/resume)
- Resolution gets emailed to the customer (Brevo)

## Project structure

```
cogent-support-chat/
├── app.py                       # Streamlit entry point: customer chat (deploy this as the main file)
├── pages/1_Admin_Dashboard.py   # Streamlit entry point: admin dashboard
│
├── support_chat/                # the application package — all the real code lives here
│   ├── config.py                #   env vars, paths, thresholds
│   ├── schemas.py               #   Pydantic models (assessment, tickets, drafts)
│   ├── auth.py                  #   login against data/users.yaml
│   ├── policy.py                #   hardcoded escalation gate — the model never decides this
│   ├── tools.py                 #   tool functions: KB search, account, tickets, email
│   ├── pipeline.py              #   assess -> KB search -> gate (shared by the app and the evals)
│   ├── observability.py         #   Logfire tracing setup
│   ├── agents/                  #   Pydantic AI: llm.py (shared model), assess.py, draft.py
│   ├── rag/                     #   extract -> chunk -> embed -> store -> retrieve -> answer (+ ingest)
│   ├── storage/turso.py         #   ticket + account storage (Turso/libSQL)
│   ├── notifications/brevo.py   #   resolution email via Brevo (logs only if no key set)
│   ├── workflows/admin_review.py#   LangGraph interrupt/resume — the admin review loop
│   └── ui/                      #   chat.py, admin.py — the Streamlit page logic
│
├── evals/                       # DeepEval suites: routing, rag, drafts (datasets/, judge.py, metrics.py, run.py)
├── scripts/init_db.py           # create the Turso tables
├── data/
│   ├── kb/                      #   KB source docs; *.pdf are gitignored (internal), example .md are tracked
│   └── users.yaml               #   logins — committed: demo accounts, plain-text passwords
├── index/                       # Chroma index — committed (Cloud deploy needs it)
├── docs/EVALS.md                # how the evals work — a walkthrough
├── requirements.txt
└── .env.example
```

Streamlit requires `app.py` and `pages/` at the repo root, so they stay there as thin entry
points; each just calls `main()` in `support_chat/ui/`.

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
| `LOGFIRE_TOKEN` | Optional — [logfire.pydantic.dev](https://logfire.pydantic.dev) write token. Blank = tracing off, nothing is sent |

Then initialize storage and the KB index:

```bash
python3 -m scripts.init_db
python3 -m support_chat.rag.ingest
```

Run locally:

```bash
streamlit run app.py
```

Customer chat at `http://localhost:8501`, admin dashboard under the
"Admin Dashboard" page in the sidebar.

## Evals and tracing

```bash
python3 -m evals.run all        # routing accuracy, RAG quality, draft quality (see docs/EVALS.md)
```

Evals run the app's real pipeline against golden datasets in `evals/datasets/` and grade the results
with DeepEval (an LLM judge for the RAG/draft suites). Run them after any change to a prompt, the
chunking, or a threshold. With `LOGFIRE_TOKEN` set, every chat turn is traced to Logfire.

## Accounts

`data/users.yaml` (login credentials) is committed to this public repo on purpose, so logins
work on a deploy. Those are demo accounts with plain-text passwords — treat them as
public and change them before any real use. Every customer is treated the same way (no tiers): the chat searches the KB first and only
opens a ticket if an escalation rule fires. A customer's display name — used to address them in a
drafted reply — lives in Turso (`accounts`: email + name); add rows with
`support_chat.storage.turso.upsert_account()`. If your Turso database predates this change, run
`python3 -m scripts.init_db` once to drop the unused `tier`/`plan`/`mrr_usd` columns.

## What's genuinely verified vs. what needs your credentials to prove out

Verified locally while building this (see commit history / build notes):
- Full assess → policy → RAG-answer path (real LLM calls)
- Full LangGraph interrupt → redraft-on-feedback → finalize-on-approve cycle
- RAG ingest → retrieve, against the example KB docs
- Both Streamlit pages boot without import errors
- `support_chat/storage/turso.py`'s API calls were checked against the actual installed
  `libsql-client` package's signatures, not guessed. Note it connects over
  `https://` (`libsql://` websockets get a 400 from Turso) — `_new_client()` swaps the scheme.

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

**This repo is public, and the pre-built Chroma index (`index/`) and `data/users.yaml` are
committed to it on purpose.** Streamlit Cloud's checkout is read-only, so the index
can't be built at runtime; it's built locally, committed, and `support_chat/rag/store.py` copies it
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
python3 -m support_chat.rag.ingest      # rebuild the index (fresh embeddings)
git add index/
git commit -m "Update KB index"
git push
```

## Security notes (demo only)

- Passwords in `data/users.yaml` are plain text — fine for a demo, not production
- `data/users.yaml` is committed to a public repo, so its passwords are public — demo accounts only
- `index/` is committed to a public repo, so the KB's policy text is public too
- Never commit `.env` or the KB PDFs
