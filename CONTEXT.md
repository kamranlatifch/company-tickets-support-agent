# Context handoff — read this first

This project was designed and built in a long brainstorming + build session
with Claude Code elsewhere. This file captures the decisions and reasoning
that a fresh session won't otherwise have — the README covers setup/structure,
this covers *why* it's shaped this way. Read both before making changes.

## Origin

Grew out of a support-ticket-triage exercise (a separate training repo,
`Week4/Day05`, not part of this project) that established a pattern worth
reusing: an LLM only ever extracts structured facts; a hardcoded policy gate
(plain Python, not the model) decides what happens next. This app applies
that same principle to a live chat instead of a batch ticket file, and adds
a second, previously-built reference app (`role-rag-app`, also on this
Desktop) as the source for the RAG/auth/Streamlit patterns.

## Decisions made, and why (in the order they were settled)

1. **Auth**: YAML file (`users.yaml`), real emails as usernames, pre-provisioned,
   no signup flow. Profile data (tier/plan) deliberately does **not** live in
   YAML — it's in Turso (`turso_db.py`'s `accounts` table). YAML is login-only.

2. **2-minute "wait for admin" UX**: considered a literal blocking wait, an
   immediate redirect-to-email, and a background auto-refresh. Landed on
   `st.fragment(run_every=...)` polling Turso — Streamlit can't push updates
   into an already-rendered page, so *some* re-checking is unavoidable;
   `st.fragment` is the native, cheap way to do it (re-runs only that
   fragment, not the whole page). Single source of truth = the ticket row in
   Turso; polling frequency only affects how fast a view notices a change,
   never whether two views can disagree.

3. **No presence/online detection for the admin.** Originally considered a
   `last_seen` heartbeat so the system would "know" if an admin was online.
   Explicitly dropped as unnecessary: the admin dashboard already polls for
   current ticket state whenever it's open, so "instant reply if the admin
   happens to be there" falls out naturally with zero extra mechanism. Don't
   add presence tracking back in without a real reason — it was cut for being
   solved-problem complexity.

4. **Storage: Turso**, not local SQLite/JSON and not Google Sheets/Supabase.
   Reasoning: Streamlit Community Cloud's filesystem is read-only/ephemeral
   at runtime (documented in `role-rag-app/README.md` for the same reason its
   Chroma index is pre-built and committed rather than built at runtime) — so
   local SQLite would silently lose every ticket on reboot. Turso was chosen
   over Google Sheets (weak concurrent-write safety, would need hand-rolled
   locking) and over Supabase (heavier setup than this needs, though it'd be
   the right call if this ever needs to scale past a demo).

5. **Email: Brevo**, free tier (300/day), REST API called via httpx (no SDK).
   Originally SendGrid, replaced (and fully removed) because cogentlabs.co has
   DMARC `p=reject` with no SendGrid DKIM, so SendGrid mail from a `@cogentlabs.co`
   sender was accepted (202) but silently dropped by Gmail — and authenticating the
   domain needs DNS access the project owner doesn't have. Brevo replaces free-mail
   senders (a personal Gmail) with its own domain, so no DNS changes are needed.
   Needs an API key (`xkeysib-`), not an SMTP key (`xsmtpsib-`). See README setup table.

6. **Escalation triggers** — deterministic, evaluated on `MessageAssessment`
   (the LLM's structured output), never on the model's own judgment:
   explicit human request > urgent > angry > billing/refund mention > VIP
   tier > asks about own account data > KB has nothing relevant > very low
   confidence. Order matters only for which *reason* gets
   reported, not the final decision (any true trigger escalates) — see
   `policy.py::should_escalate`.
   **Updated after KB went live:** "low confidence" used to be the model's
   self-rated confidence with a 0.75 cutoff. In testing that was wrong both ways
   (in-KB questions scored 0.3-0.5, out-of-KB ones 0.8-0.9), so a follow-up like
   "how many max amount can I apply for?" got escalated though the Loan policy
   answers it. The gate now uses the best KB retrieval score
   (`KB_MIN_RETRIEVAL_SCORE`, 0.38 — off-topic <=0.34, in-KB >=0.40; the search
   query includes the assessment's context-resolved `summary` so follow-ups match)
   plus a model-extracted boolean `needs_account_data`. Model confidence is only a
   0.25 backstop. Re-check the 0.38 threshold if the KB changes a lot.

7. **2 tickets per login, not per day/lifetime.** Counted via
   `turso_db.count_tickets_for_user_since(email, login_started_at)`, where
   `login_started_at` is captured once at login into session state. On the
   3rd escalation-worthy message in one login, no ticket is created — the
   user gets a warm, positively-framed message instead of a hard block
   (`app.py::_handle_confirmation`), and can keep chatting for
   best-effort answers.

8. **Admin drafts are on-demand, not pre-emptive.** Unlike the Day 05
   reference pattern (which always drafts a reply up front), this app only
   calls `draft_ticket_reply` when the admin actually opens a ticket
   (`review_graph.py::_gather_and_draft`) — saves an LLM call on any ticket
   the admin handles without wanting AI help.

9. **LangGraph interrupt/resume — deliberately scoped to *only* the admin's
   draft→feedback→approve loop, not the customer-to-admin handoff.**
   This is the one decision most likely to look "wrong" to a fresh reader,
   so it's worth restating clearly: the customer-to-admin handoff can span
   arbitrary real time and two different people — that's a queue, not an
   agent execution to pause. Wrapping *that* in LangGraph's checkpointer
   would mean hosting graph state somewhere durable across sessions, which
   practically means swapping Turso for Postgres, for zero visible behavior
   change. The admin's own review loop, by contrast, is single-person,
   single-sitting, tight iteration — the actual shape `interrupt()` is built
   for. This was tested directly and confirmed working: a full
   assess→draft→interrupt→feedback→redraft→interrupt→approve→finalize cycle
   ran end-to-end with real LLM calls, and the redraft genuinely
   incorporated the feedback given (see build notes below).

## What was actually verified while building (not just written)

- Real LLM calls through `assess_message` + `policy.decide_outcome`: a plain
  password question correctly resolved to `ANSWER`; a message with an angry
  tone, urgency, and a `$300` refund demand correctly resolved to `ESCALATE`
  with every field (`is_urgent`, `is_angry`, `mentions_billing_or_refund`,
  `requested_amount_usd`, `wants_human`) extracted correctly.
- Real RAG ingest + retrieval against the two example KB docs in `data/kb/`
  — correct top match by embedding similarity.
- The full LangGraph cycle described in point 9, run directly against
  `review_graph.py`, mocking only the Turso account lookup (Turso itself
  wasn't configured yet at build time).
- `turso_db.py`'s exact function calls were checked
  against the *installed* `libsql-client` package's real
  signatures (`inspect.signature`) rather than written from memory/guessed —
  flagged explicitly during the build because package APIs shift over time
  and getting the persistence layer wrong silently would be a real problem.
- Both `app.py` and `pages/1_Admin_Dashboard.py` boot without import errors
  (verified via a headless Streamlit launch + HTTP check).

## What's NOT verified yet — needs real credentials

- Turso: schema creation and ticket persistence are now verified against a real
  database (see the `https://` note in the README). Still worth a multi-session check.
- Brevo: a test send was accepted (201); inbox delivery not yet confirmed
- The full customer-facing flow through a real browser (only checked that
  pages boot, not the actual click-through UX)

## Deliberately deferred, not forgotten

- **DeepEval** — explicitly deferred to "later," Logfire only for now
- **MCP** — ruled out for the same reason it was ruled out in the Day 05
  reference project: nothing external needs to reach into this app's tools;
  would be exposing a protocol boundary nothing on the other side needs
- Multimodal (screenshot attachments), a "skills" library of canned reply
  templates, agentic multi-hop RAG, and a cheap local-model first-pass triage
  were all discussed as legitimate v2 additions and explicitly *not* built
  into v1 — the scenario was deliberately simplified before building started

## Immediate next steps (as of hand-off)

1. Get Turso credentials, run `python3 -c "from turso_db import init_schema; init_schema()"`
2. Confirm a Brevo email actually lands in the inbox (set `BREVO_API_KEY` / `BREVO_FROM_EMAIL`)
3. Replace `data/kb/*.md` placeholders with real KB content, re-run
   `python3 -m rag.ingest`
4. Full click-through test in a real browser
5. Nothing has been committed to git yet — repo is `git init`'d locally only
