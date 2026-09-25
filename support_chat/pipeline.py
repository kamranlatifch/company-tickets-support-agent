"""The routing pipeline for one customer message: assess -> search the KB -> gate.

Kept out of the Streamlit page so the app and the evals (/evals) run exactly the same code.
"""

import asyncio
from dataclasses import dataclass

from support_chat.agents import assess_message, assess_message_async
from support_chat.policy import decide_outcome
from support_chat.rag.answer import search_kb
from support_chat.schemas import ChatOutcome, MessageAssessment

HISTORY_WINDOW = 12  # messages of chat history the assessment agent sees


@dataclass
class GateResult:
    assessment: MessageAssessment
    hits: list[dict]  # KB passages for this message ([] for small talk, which skips the search)
    kb_score: float | None  # best match's similarity; None when the search was skipped
    outcome: ChatOutcome
    reason: str


def history_text(history: list[dict]) -> str:
    lines = []
    for msg in history[-HISTORY_WINDOW:]:
        speaker = "Customer" if msg["role"] == "user" else "Assistant"
        lines.append(f"{speaker}: {msg['content']}")
    return "\n".join(lines)


def assess_and_route(message: str, history: list[dict]) -> GateResult:
    """`history` is the conversation BEFORE `message` ({"role", "content"} dicts)."""
    assessment = assess_message(message, history=history_text(history))
    hits, kb_score = [], None  # small talk skips the KB search and the relevance check
    if not assessment.is_small_talk:
        hits = search_kb(message, assessment.summary, history)
        kb_score = hits[0]["score"] if hits else 0.0
    outcome, reason = decide_outcome(assessment, kb_score)
    return GateResult(assessment, hits, kb_score, outcome, reason)


async def assess_and_route_async(message: str, history: list[dict]) -> GateResult:
    """Same as assess_and_route, for callers already inside an event loop (the evals). The LLM
    call is awaited; the KB search (sync OpenAI + Chroma) runs in a worker thread so it doesn't
    block the loop."""
    assessment = await assess_message_async(message, history=history_text(history))
    hits, kb_score = [], None
    if not assessment.is_small_talk:
        hits = await asyncio.to_thread(search_kb, message, assessment.summary, history)
        kb_score = hits[0]["score"] if hits else 0.0
    outcome, reason = decide_outcome(assessment, kb_score)
    return GateResult(assessment, hits, kb_score, outcome, reason)
