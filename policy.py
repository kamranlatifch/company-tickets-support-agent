"""Hard gate — escalation rules live here, not in the prompt.

Same principle as Week4/Day05's shared/policy.py: the model only extracts
structured facts (schemas.MessageAssessment); this module, plain Python,
decides what happens with them. The model never decides whether to escalate.
"""

from config import KB_CONFIDENCE_MIN, KB_MIN_RETRIEVAL_SCORE, VIP_TIERS
from schemas import ChatOutcome, CustomerAccount, MessageAssessment


def should_escalate(
    analysis: MessageAssessment, account: CustomerAccount | None, kb_score: float | None = None
) -> tuple[bool, str]:
    """kb_score: similarity of the best KB match for this question (None = not searched)."""
    if analysis.wants_human:
        return True, "user asked to talk to a human"
    if analysis.is_urgent:
        return True, "urgent"
    if analysis.is_angry:
        return True, "angry customer tone"
    if analysis.mentions_billing_or_refund:
        return True, "billing/refund — never auto-resolved via chat"
    if account and account.tier.lower() in VIP_TIERS:
        return True, f"high-value account tier={account.tier}"
    if analysis.needs_account_data:
        return True, "asks about their own account data — needs a person to look it up"
    if kb_score is not None and kb_score < KB_MIN_RETRIEVAL_SCORE:
        return True, f"KB has nothing relevant to this question (best match {kb_score:.2f})"
    if analysis.confidence < KB_CONFIDENCE_MIN:
        return True, "low confidence — can't answer this confidently from the KB"
    return False, ""


def decide_outcome(
    analysis: MessageAssessment, account: CustomerAccount | None, kb_score: float | None = None
) -> tuple[ChatOutcome, str]:
    escalate, reason = should_escalate(analysis, account, kb_score)
    if escalate:
        return ChatOutcome.ESCALATE, reason
    return ChatOutcome.ANSWER, "confident, low-stakes — answered directly from the KB"
