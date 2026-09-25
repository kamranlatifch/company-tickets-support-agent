import logfire

from support_chat.config import LOGFIRE_TOKEN  # importing config also loads .env, before logfire reads the token

_configured = False


def setup_tracing(**configure_overrides) -> None:
    global _configured
    if _configured:
        return
    logfire.configure(
        **{
            "service_name": "cogent-support-chat",
            "send_to_logfire": "if-token-present",
            "console": False,  # don't flood the Streamlit terminal with spans
            **configure_overrides,
        }
    )
    logfire.instrument_pydantic_ai()  # every agent run: prompt, output, token usage, latency
    logfire.instrument_openai()  # embeddings + the streamed KB answer (support_chat/rag/client.py)
    _configured = True


def tracing_enabled() -> bool:
    return bool(LOGFIRE_TOKEN)


def chat_turn():

    return logfire.span("chat turn")


def log_gate_decision(*, outcome: str, reason: str, kb_score: float | None, assessment) -> None:
    logfire.info(
        "gate decision: {outcome}",
        outcome=outcome,
        reason=reason,
        kb_score=kb_score,
        confidence=assessment.confidence,
        category=str(getattr(assessment.category, "value", assessment.category)),
        is_small_talk=assessment.is_small_talk,
        needs_account_data=assessment.needs_account_data,
        is_urgent=assessment.is_urgent,
        is_angry=assessment.is_angry,
        mentions_billing_or_refund=assessment.mentions_billing_or_refund,
        wants_human=assessment.wants_human,
    )
