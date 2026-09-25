from support_chat.config import TOP_K
from support_chat.rag.client import embed_query
from support_chat.rag.store import search


def format_source(meta: dict | None) -> str:
    meta = meta or {}
    source = meta.get("source", "unknown")
    section = meta.get("section", "")
    page = meta.get("page")
    label = source
    if section and section != source:
        label = f"{source} — {section}"
    if page:
        label = f"{label} (p.{page})"
    return label


def retrieve(question: str, top_k: int = TOP_K) -> list[dict]:
    result = search(embed_query(question), top_k)
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    hits = []
    for doc, meta, dist in zip(docs, metas, distances or [None] * len(docs)):
        score = round(1 - dist, 3) if dist is not None else None
        hits.append(
            {
                "text": doc,
                "source": (meta or {}).get("source", "unknown"),
                "section": (meta or {}).get("section", ""),
                "page": (meta or {}).get("page"),
                "label": format_source(meta),
                "score": score,
            }
        )
    return hits


def format_context(hits: list[dict]) -> str:
    if not hits:
        return "(no matching KB passages)"
    parts = []
    for i, hit in enumerate(hits, 1):
        parts.append(f"[{i}] ({hit['label']})\n{hit['text']}")
    return "\n\n".join(parts)
