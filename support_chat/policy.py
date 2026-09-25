from support_chat.config import KB_CONFIDENCE_MIN, KB_MIN_RETRIEVAL_SCORE
from support_chat.schemas import ChatOutcome, MessageAssessment


def should_escalate(analysis: MessageAssessment, kb_score: float | None = None) -> tuple[bool, str]:
    if analysis.wants_human:
        return True, "user asked to talk to a human"
    if analysis.is_urgent:
        return True, "urgent"
    if analysis.mentions_billing_or_refund:
        return True, "billing/refund — never auto-resolved via chat"
    if analysis.is_small_talk or analysis.asks_what_you_cover:
        # A bare "hi", a remark about the bot, or "what can you help with?" has nothing for the KB
        # to match and isn't worth a ticket; the triggers above still win if it is urgent, etc.
        return False, ""
    if analysis.needs_account_data:
        return True, "asks about their own account data — needs a person to look it up"
    if kb_score is not None and kb_score < KB_MIN_RETRIEVAL_SCORE:
        return True, f"KB has nothing relevant to this question (best match {kb_score:.2f})"
    if analysis.confidence < KB_CONFIDENCE_MIN:
        return True, "low confidence — can't answer this confidently from the KB"
    return False, ""


def decide_outcome(analysis: MessageAssessment, kb_score: float | None = None) -> tuple[ChatOutcome, str]:
    escalate, reason = should_escalate(analysis, kb_score)
    if escalate:
        return ChatOutcome.ESCALATE, reason
    return ChatOutcome.ANSWER, "confident, low-stakes — answered directly from the KB"
