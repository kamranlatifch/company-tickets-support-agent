from support_chat.config import MAX_TICKETS_PER_LOGIN
from support_chat.notifications.brevo import send_resolution_email
from support_chat.rag.retrieve import retrieve
from support_chat.schemas import CustomerAccount, KBMatch, TicketRecord, TicketStatus
from support_chat.storage import turso


def search_kb(query: str, limit: int = 3) -> list[KBMatch]:
    hits = retrieve(query, top_k=limit)
    return [
        KBMatch(article_id=h["source"], title=h["label"], excerpt=h["text"][:220], score=h["score"] or 0.0)
        for h in hits
    ]


def get_account(email: str) -> CustomerAccount | None:
    return turso.get_account(email)


def can_create_ticket(user_email: str, login_started_at: str) -> tuple[bool, int]:

    count = turso.count_tickets_for_user_since(user_email, login_started_at)
    return count < MAX_TICKETS_PER_LOGIN, count


def create_ticket(user_email: str, query: str, chat_context: str, reason: str) -> TicketRecord:
    return turso.create_ticket(user_email, query, chat_context, reason)


def get_ticket(ticket_id: str) -> TicketRecord | None:
    return turso.get_ticket(ticket_id)


def list_open_tickets() -> list[TicketRecord]:
    return turso.list_tickets(status=TicketStatus.OPEN)


def list_all_tickets() -> list[TicketRecord]:
    return turso.list_tickets()


def save_draft(ticket_id: str, subject: str, body: str) -> None:
    turso.save_draft(ticket_id, subject, body)


def resolve_and_email(ticket_id: str, subject: str, body: str, to_email: str) -> dict:
    turso.resolve_ticket(ticket_id, body)
    return send_resolution_email(to_email, subject, body)
