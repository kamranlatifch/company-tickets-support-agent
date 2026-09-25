from pathlib import Path

from support_chat.config import KB_DIR
from support_chat.rag.chunking import chunk_document
from support_chat.rag.client import embed_texts
from support_chat.rag.extract import SUPPORTED_SUFFIXES, load_document
from support_chat.rag.store import upsert


def _doc_title(doc) -> str:
    first = doc.blocks[0].text.strip().splitlines()[0].lstrip("# ").strip()
    return first if 0 < len(first) <= 60 else Path(doc.filename).stem.replace("_", " ")


def _load_docs() -> list:
    docs = []
    for path in sorted(KB_DIR.glob("*")):
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        doc = load_document(path)
        if doc.blocks:
            docs.append(doc)
    return docs


def ingest_kb() -> int:
    if not KB_DIR.is_dir():
        raise SystemExit(f"Missing folder: {KB_DIR}")

    docs = _load_docs()
    if not docs:
        raise SystemExit(f"No supported files in {KB_DIR} ({', '.join(sorted(SUPPORTED_SUFFIXES))})")

    ids, documents, embed_inputs, metadatas = [], [], [], []
    for doc in docs:
        for i, chunk in enumerate(chunk_document(doc)):
            # A title-only chunk ("Hardware Issuance Policy") holds no information, but it matches
            # questions about the topic strongly and outranks the real content, so leave it out.
            if chunk["section"] == doc.filename and len(chunk["text"].strip()) < 60:
                continue
            doc_id = f"{doc.filename}_{i}"
            ids.append(doc_id)
            documents.append(chunk["text"])
            # Embed the document title AND section title with the text (the stored text is unchanged).
            # A chunk like "Eligibility: • probation not eligible" never says "medical"; without the
            # document title in front, a question about medical reimbursement can't find it.
            has_section = chunk["section"] != doc.filename
            header = f"{_doc_title(doc)} — {chunk['section']}" if has_section else _doc_title(doc)
            embed_inputs.append(f"{header}\n{chunk['text']}" if has_section else chunk["text"])
            metadatas.append(
                {
                    "source": doc.filename,
                    "title": _doc_title(doc),
                    "section": chunk["section"],
                    "page": int(chunk["page"]),
                    "chunk": i,
                }
            )

    embeddings = embed_texts(embed_inputs)
    upsert(ids, documents, embeddings, metadatas)
    return len(documents)


def main() -> None:
    n = ingest_kb()
    print(f"indexed {n} chunks from {KB_DIR}")


if __name__ == "__main__":
    main()
