"""Pydantic AI agents — the only place the LLM interprets raw text.
Same pattern as Week4/Day05's triage_pydantic/agents.py."""

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from config import API_KEY, BASE_URL, MODEL
from schemas import CustomerAccount, KBMatch, MessageAssessment, ReplyDraft

if not API_KEY:
    raise SystemExit("Set COGENT_OPRNROUTER_KEY in .env")

_model = OpenAIChatModel(
    MODEL,
    provider=OpenAIProvider(base_url=BASE_URL, api_key=API_KEY),
)

assess_agent = Agent(
    _model,
    output_type=MessageAssessment,
    retries=2,
    instructions=(
        "You triage Cogent Labs support chat messages. Extract structured fields only. "
        "category MUST be exactly one of: general, billing, technical, feature, complaint, other. "
        "Set confidence high when the message is a general question about company policy or how "
        "something works (the KB covers policies such as leave, loans, medical, hardware, trips, "
        "plus account basics). Follow-ups like 'how much is the maximum?' inherit the topic of the "
        "conversation so far. Lower confidence only for genuinely ambiguous or multi-part requests. "
        "Set is_small_talk true ONLY for a pure greeting, thanks, acknowledgement or goodbye "
        "(hi, hello, good morning, thanks, ok, bye) that contains no question or request; a "
        "greeting followed by a question ('hi, how do I reset my password') is NOT small talk. "
        "Set needs_account_data true when the user asks about their own records or requests "
        "(their balance, payslip, application status, personal data), which no KB article can answer. "
        "Detect urgency (outage, broken workflow, time pressure), anger/frustration, "
        "any billing or refund/credit mention with a dollar amount, and any explicit request "
        "to talk to a human or support agent."
    ),
)

draft_agent = Agent(
    _model,
    output_type=ReplyDraft,
    retries=2,
    instructions=(
        "Draft a concise, professional support reply for a resolved ticket. "
        "Use the KB context and account info when relevant. "
        "Do not promise refunds or credits unless quoting policy explicitly. "
        "Set mentions_refund_or_credit true if the reply offers money back or credits."
    ),
)


def assess_message(message: str, history: str = "") -> MessageAssessment:
    prompt = f"Conversation so far:\n{history}\n\nLatest message:\n{message}" if history else message
    result = assess_agent.run_sync(prompt)
    return result.output


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
    kb_text = (
        "\n".join(f"- [{m.article_id}] {m.title} (score={m.score}): {m.excerpt}" for m in kb_matches)
        if kb_matches
        else "No KB article matched."
    )
    account_text = (
        f"{account.name} <{account.email}> — {account.tier} tier, {account.plan} plan"
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
    prompt += "Write the reply."
    result = draft_agent.run_sync(prompt)
    draft = result.output
    if not draft.subject.strip():
        draft = draft.model_copy(update={"subject": "Re: your support ticket"})
    return draft
