"""Drafting agent — writes (and redrafts, on admin feedback) the reply for a ticket.

The admin always reviews and approves the result before anything is emailed."""

from pydantic_ai import Agent

from support_chat.agents.llm import get_model
from support_chat.schemas import CustomerAccount, KBMatch, ReplyDraft

# No default model: it is supplied per call (get_model() is thread-local, see llm.py).
draft_agent = Agent(
    output_type=ReplyDraft,
    retries=2,
    instructions=(
        "Draft a concise, professional reply that a support agent will review before it is sent. "
        "Base every statement of fact on the KB context or the account details provided. "
        "You cannot look anything up, investigate, or act on an account, so describe next steps as "
        "things the team WILL do ('our billing team will review this charge and follow up'), never as "
        "things already done. For any refund, credit, charge dispute or exception, say the request has "
        "been passed to the responsible team for review and that a team member will follow up; the "
        "decision stays with the team. When the KB does not cover the request, say so plainly and say "
        "who will follow up. When the customer asks for more than a limit stated in the KB, quote the "
        "limit and say plainly that the request is above it. Address the customer by "
        "name when the account details give it. Sign off "
        "as 'Cogent Labs Support' and never leave bracketed placeholders. "
        "Set mentions_refund_or_credit true only if the reply itself offers or confirms money back or credits."
    ),
)


def _prompt(
    query: str,
    kb_matches: list[KBMatch],
    account: CustomerAccount | None,
    reason: str,
    chat_context: str,
    admin_notes: str | None,
    previous_draft: str | None,
) -> str:
    kb_text = (
        "\n".join(f"- [{m.article_id}] {m.title} (score={m.score}): {m.excerpt}" for m in kb_matches)
        if kb_matches
        else "No KB article matched."
    )
    account_text = (
        f"{account.name} <{account.email}>"
        if account
        else "Account not found."
    )
    prompt = (
        f"Customer query:\n{query}\n\n"
        f"Why this needed a human: {reason}\n\n"
        f"Account:\n{account_text}\n\n"
        f"Knowledge base:\n{kb_text}\n\n"
    )
    if chat_context:
        prompt += f"Conversation so far:\n{chat_context}\n\n"
    if admin_notes and previous_draft:
        prompt += (
            f"Current draft:\n{previous_draft}\n\n"
            "Revise the current draft according to the admin notes below. Keep every part the "
            "notes don't ask you to change exactly as it is, including wording the admin edited.\n\n"
        )
    if admin_notes:
        prompt += f"Admin notes (follow this):\n{admin_notes}\n\n"
    return prompt + "Write the reply."


def _with_subject(draft: ReplyDraft) -> ReplyDraft:
    if not draft.subject.strip():
        return draft.model_copy(update={"subject": "Re: your support ticket"})
    return draft


def draft_ticket_reply(
    query: str,
    kb_matches: list[KBMatch],
    account: CustomerAccount | None,
    *,
    reason: str = "",
    chat_context: str = "",
    admin_notes: str | None = None,
    previous_draft: str | None = None,
) -> ReplyDraft:
    """Drafts (or redrafts, with admin_notes) a ticket reply. Takes plain query/
    reason/context strings rather than a MessageAssessment — by the time a
    ticket is being reviewed, only the saved TicketRecord is available, not
    the original assessment object."""
    prompt = _prompt(query, kb_matches, account, reason, chat_context, admin_notes, previous_draft)
    return _with_subject(draft_agent.run_sync(prompt, model=get_model()).output)


async def draft_ticket_reply_async(
    query: str,
    kb_matches: list[KBMatch],
    account: CustomerAccount | None,
    *,
    reason: str = "",
    chat_context: str = "",
    admin_notes: str | None = None,
    previous_draft: str | None = None,
) -> ReplyDraft:
    """Same as draft_ticket_reply, for callers that already run in an event loop (the evals)."""
    prompt = _prompt(query, kb_matches, account, reason, chat_context, admin_notes, previous_draft)
    return _with_subject((await draft_agent.run(prompt, model=get_model())).output)
