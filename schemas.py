from enum import Enum

from pydantic import BaseModel, Field


class MessageCategory(str, Enum):
    GENERAL = "general"
    BILLING = "billing"
    TECHNICAL = "technical"
    FEATURE = "feature"
    COMPLAINT = "complaint"
    OTHER = "other"


class ChatOutcome(str, Enum):
    ANSWER = "answer"       # confident, low-stakes — RAG answers directly
    ESCALATE = "escalate"   # needs a human — becomes a ticket


class MessageAssessment(BaseModel):
    """Structured read on one user message — the only place the LLM interprets raw text."""

    category: MessageCategory
    summary: str = Field(description="One-sentence summary of what the user wants")
    confidence: float = Field(ge=0.0, le=1.0, description="How confidently this can be answered from the KB")
    is_urgent: bool = Field(description="Outage, broken workflow, time-sensitive, ASAP")
    is_angry: bool = Field(description="Hostile or very frustrated tone")
    mentions_billing_or_refund: bool
    requested_amount_usd: float | None = Field(
        default=None, description="Dollar amount if the user asks for a refund/credit, else null"
    )
    wants_human: bool = Field(description="User explicitly asked to talk to a person/support")
    is_small_talk: bool = Field(
        default=False,
        description="Only a greeting, thanks, acknowledgement or goodbye, with no question or request in it",
    )
    needs_account_data: bool = Field(
        default=False,
        description="Asks about their own records (balance, payslip, request status, personal data) "
        "that no general KB article can answer",
    )


class KBMatch(BaseModel):
    article_id: str
    title: str
    excerpt: str
    score: float


class CustomerAccount(BaseModel):
    email: str
    name: str
    tier: str
    plan: str
    mrr_usd: float = 0.0


class ReplyDraft(BaseModel):
    subject: str
    body: str
    mentions_refund_or_credit: bool = False
    refund_or_credit_amount_usd: float | None = None


class TicketStatus(str, Enum):
    OPEN = "open"
    ANSWERED = "answered"


class TicketRecord(BaseModel):
    id: str
    user_email: str
    query: str
    chat_context: str = ""
    status: TicketStatus = TicketStatus.OPEN
    reason: str = ""
    draft_subject: str | None = None
    draft_body: str | None = None
    answer: str | None = None
    created_at: str
    resolved_at: str | None = None
