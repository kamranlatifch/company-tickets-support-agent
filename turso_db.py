"""Turso (libSQL) client — tickets and customer accounts.

Uses `libsql_client.create_client_sync(url=, auth_token=)` — verified against
the installed libsql-client package (create_client_sync/ClientSync.execute/
ResultSet.rows/Row index access all confirmed directly, not guessed).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import libsql_client

from config import TURSO_AUTH_TOKEN, TURSO_DATABASE_URL
from schemas import CustomerAccount, TicketRecord, TicketStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tier TEXT NOT NULL,
    plan TEXT NOT NULL,
    mrr_usd REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    query TEXT NOT NULL,
    chat_context TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    reason TEXT NOT NULL DEFAULT '',
    draft_subject TEXT,
    draft_body TEXT,
    answer TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
"""


def get_client():
    if not TURSO_DATABASE_URL:
        raise SystemExit("Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in .env")
    # libsql:// makes this client open a websocket, which Turso now rejects with a 400
    # handshake error; the same database works fine over HTTPS.
    url = TURSO_DATABASE_URL.replace("libsql://", "https://", 1)
    return libsql_client.create_client_sync(url=url, auth_token=TURSO_AUTH_TOKEN)


def init_schema() -> None:
    client = get_client()
    try:
        for statement in _SCHEMA.strip().split(";"):
            statement = statement.strip()
            if statement:
                client.execute(statement)
    finally:
        client.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- accounts ---------------------------------------------------------------


def get_account(email: str) -> CustomerAccount | None:
    client = get_client()
    try:
        rs = client.execute("SELECT email, name, tier, plan, mrr_usd FROM accounts WHERE email = ?", [email])
    finally:
        client.close()
    if not rs.rows:
        return None
    row = rs.rows[0]
    return CustomerAccount(email=row[0], name=row[1], tier=row[2], plan=row[3], mrr_usd=row[4])


def upsert_account(account: CustomerAccount) -> None:
    client = get_client()
    try:
        client.execute(
            "INSERT INTO accounts (email, name, tier, plan, mrr_usd) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(email) DO UPDATE SET name=excluded.name, tier=excluded.tier, "
            "plan=excluded.plan, mrr_usd=excluded.mrr_usd",
            [account.email, account.name, account.tier, account.plan, account.mrr_usd],
        )
    finally:
        client.close()


# --- tickets ------------------------------------------------------------


def create_ticket(user_email: str, query: str, chat_context: str, reason: str) -> TicketRecord:
    ticket = TicketRecord(
        id=str(uuid.uuid4())[:8],
        user_email=user_email,
        query=query,
        chat_context=chat_context,
        status=TicketStatus.OPEN,
        reason=reason,
        created_at=_now(),
    )
    client = get_client()
    try:
        client.execute(
            "INSERT INTO tickets (id, user_email, query, chat_context, status, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [ticket.id, ticket.user_email, ticket.query, ticket.chat_context, ticket.status.value, ticket.reason, ticket.created_at],
        )
    finally:
        client.close()
    return ticket


def count_tickets_for_user_since(user_email: str, since_iso: str) -> int:
    """Used by the 2-tickets-per-login cap — count tickets created since this login."""
    client = get_client()
    try:
        rs = client.execute(
            "SELECT COUNT(*) FROM tickets WHERE user_email = ? AND created_at >= ?",
            [user_email, since_iso],
        )
    finally:
        client.close()
    return int(rs.rows[0][0]) if rs.rows else 0


def _row_to_ticket(row) -> TicketRecord:
    return TicketRecord(
        id=row[0],
        user_email=row[1],
        query=row[2],
        chat_context=row[3],
        status=TicketStatus(row[4]),
        reason=row[5],
        draft_subject=row[6],
        draft_body=row[7],
        answer=row[8],
        created_at=row[9],
        resolved_at=row[10],
    )


_TICKET_COLUMNS = (
    "id, user_email, query, chat_context, status, reason, draft_subject, draft_body, answer, created_at, resolved_at"
)


def get_ticket(ticket_id: str) -> TicketRecord | None:
    client = get_client()
    try:
        rs = client.execute(f"SELECT {_TICKET_COLUMNS} FROM tickets WHERE id = ?", [ticket_id])
    finally:
        client.close()
    return _row_to_ticket(rs.rows[0]) if rs.rows else None


def list_tickets(status: TicketStatus | None = None) -> list[TicketRecord]:
    client = get_client()
    try:
        if status:
            rs = client.execute(
                f"SELECT {_TICKET_COLUMNS} FROM tickets WHERE status = ? ORDER BY created_at DESC",
                [status.value],
            )
        else:
            rs = client.execute(f"SELECT {_TICKET_COLUMNS} FROM tickets ORDER BY created_at DESC")
    finally:
        client.close()
    return [_row_to_ticket(row) for row in rs.rows]


def save_draft(ticket_id: str, subject: str, body: str) -> None:
    client = get_client()
    try:
        client.execute(
            "UPDATE tickets SET draft_subject = ?, draft_body = ? WHERE id = ?",
            [subject, body, ticket_id],
        )
    finally:
        client.close()


def resolve_ticket(ticket_id: str, answer: str) -> None:
    client = get_client()
    try:
        client.execute(
            "UPDATE tickets SET status = ?, answer = ?, resolved_at = ? WHERE id = ?",
            [TicketStatus.ANSWERED.value, answer, _now(), ticket_id],
        )
    finally:
        client.close()
