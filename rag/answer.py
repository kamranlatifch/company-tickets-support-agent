"""Generate the RAG answer for messages the policy gate cleared as ANSWER.
Simpler than role-rag-app's version: MessageAssessment (agents.py) already
handled category/confidence/small-talk upstream — this module's only job is
retrieve + generate."""

import re

from config import MAX_HISTORY_TURNS, TOP_K
from rag.client import chat_stream
from rag.retrieve import format_context, retrieve

ANSWER_SYSTEM = (
    "You are a warm, helpful Cogent Labs support assistant. "
    "Answer using the KB details provided below — ground every claim in that info, "
    "never invent policy or product details. "
    "Write in plain, conversational language. "
    "NEVER use meta/document-referencing language ('the passages', 'the documents'). "
    "Speak directly: 'You can reset your password by...' not 'The documents mention...'. "
    "Keep answers concise but complete."
)

FOLLOWUP_HINTS = re.compile(
    r"\b(elaborate|more details?|tell me more|explain (?:more|further|that|it|this)|"
    r"what about|how about|and that|same (?:one|thing)|go on|continue)\b",
    re.IGNORECASE,
)


def _api_history(history: list[dict]) -> list[dict]:
    trimmed = history[-MAX_HISTORY_TURNS * 2 :]
    return [
        {"role": msg["role"], "content": msg["content"]}
        for msg in trimmed
        if msg.get("role") in ("user", "assistant") and msg.get("content")
    ]


def _needs_wider_search(question: str, history: list[dict]) -> bool:
    return bool(history) and (bool(FOLLOWUP_HINTS.search(question)) or len(question.split()) <= 8)


SMALLTALK_SYSTEM = (
    "You are a warm, friendly Cogent Labs support assistant. The customer sent only a greeting, "
    "thanks, or goodbye. Reply in one or two short sentences. When it fits, invite them to ask "
    "about company policies (leave, loans, medical, hardware, trips) or account help. "
    "Never state any policy or facts."
)


def prepare_smalltalk_stream(question: str, history: list[dict] | None = None):
    """Reply to a greeting/thanks without touching the KB."""
    messages = [
        {"role": "system", "content": SMALLTALK_SYSTEM},
        *_api_history(history or []),
        {"role": "user", "content": question},
    ]
    return chat_stream(messages)


def search_kb(question: str, summary: str = "", history: list[dict] | None = None) -> list[dict]:
    """Retrieve KB passages for a message. `summary` is the assessment's one-line,
    context-resolved restatement — it turns a bare follow-up like 'ok how many max
    amount i can apply for?' into one that names the topic (loan) so it matches."""
    history = history or []
    top_k = TOP_K + 2 if _needs_wider_search(question, history) else TOP_K
    query = f"{question}\n{summary}" if summary else question
    return retrieve(query, top_k=top_k)


def prepare_answer_stream(question: str, history: list[dict] | None = None, hits: list[dict] | None = None) -> dict:
    history = history or []
    if hits is None:
        hits = search_kb(question, history=history)
    sources = sorted({h["label"] for h in hits})
    context = format_context(hits)

    messages = [
        {"role": "system", "content": ANSWER_SYSTEM},
        *_api_history(history),
        {"role": "user", "content": f"KB details:\n{context}\n\nQuestion: {question}"},
    ]
    return {
        "sources": sources,
        "hits": hits,
        "stream": chat_stream(messages),
    }
