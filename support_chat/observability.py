"""Tracing with Logfire (Pydantic's observability platform).

`setup_tracing()` is called once per process by the Streamlit entry points. It is safe to call
repeatedly. With no LOGFIRE_TOKEN nothing is sent anywhere, and the app behaves the same.

What ends up in a trace, per customer message:
  chat turn                      <- our span (one per message)
    ├─ agent run (assess)        <- PydanticAI instrumentation: prompt, structured output, tokens
    ├─ embeddings                <- OpenAI client instrumentation (the KB search)
    ├─ gate decision             <- our event: outcome, reason, KB score
    └─ chat completion           <- OpenAI client instrumentation (the streamed KB answer)
Admin drafting shows up as `agent run (draft)` spans.
"""

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
    """Span wrapping one customer message, so the agent/embedding/completion spans nest under it.
    The customer's email address is deliberately not recorded."""
    return logfire.span("chat turn")


def log_gate_decision(*, outcome: str, reason: str, kb_score: float | None, assessment) -> None:
    """One structured event per message: what the gate saw and what it decided."""
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
