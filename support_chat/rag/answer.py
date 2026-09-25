import re

from support_chat.config import MAX_HISTORY_TURNS, TOP_K
from support_chat.rag.client import chat_stream
from support_chat.rag.retrieve import format_context, retrieve
from support_chat.rag.store import get_collection

ANSWER_SYSTEM = (
    "You are a warm, helpful Cogent Labs support assistant. "
    "Answer using the KB details provided below — ground every claim in that info, "
    "never invent policy or product details. "
    "Write in plain, conversational language. "
    "NEVER use meta/document-referencing language ('the passages', 'the documents'). "
    "Speak directly: 'You can reset your password by...' not 'The documents mention...'. "
    "Keep answers concise but complete, and stay on the question asked: use only the KB details "
    "that answer it and leave out related information nobody asked for. "
    "If the customer sounds frustrated or rude, open with one short, calm acknowledgement and then "
    "answer the question."
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
    "thanks, goodbye, or a remark about you (which may be rude). Reply in one or two short sentences. "
    "If they are annoyed with you, apologise briefly and invite them to ask their question, or to "
    "ask for a person. When it fits, invite them to ask about company policies (leave, loans, "
    "medical, hardware, trips) or account help. Never state any policy or facts."
)


def prepare_smalltalk_stream(question: str, history: list[dict] | None = None):
    """Reply to a greeting/thanks without touching the KB."""
    messages = [
        {"role": "system", "content": SMALLTALK_SYSTEM},
        *_api_history(history or []),
        {"role": "user", "content": question},
    ]
    return chat_stream(messages)


def kb_overview() -> str:
    """The real list of documents in the KB, read from the index, for "what can you help with?"."""
    metas = get_collection().get(include=["metadatas"])["metadatas"]
    titles = {m.get("title") or m["source"].rsplit(".", 1)[0].replace("_", " ") for m in metas}
    if not titles:
        return "I don't have any documents loaded yet."
    titles = {title.removeprefix("Cogent Labs: ") for title in titles}
    bullets = "\n".join(f"- {title}" for title in sorted(titles))
    return f"I can answer questions about these topics:\n\n{bullets}\n\nJust ask me about any of them."


def search_kb(question: str, summary: str = "", history: list[dict] | None = None) -> list[dict]:
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
