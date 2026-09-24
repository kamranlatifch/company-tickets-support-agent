"""Build the Chroma index from data/kb/*.pdf, *.txt, *.md

Run: python3 -m rag.ingest
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import KB_DIR
from rag.chunking import chunk_document
from rag.client import embed_texts
from rag.extract import SUPPORTED_SUFFIXES, load_document
from rag.store import upsert


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
            doc_id = f"{doc.filename}_{i}"
            ids.append(doc_id)
            documents.append(chunk["text"])
            # Embed the section title with the text so "who is eligible for casual
            # leave" can match a chunk whose body never repeats "casual leave".
            has_section = chunk["section"] != doc.filename
            embed_inputs.append(f"{chunk['section']}\n{chunk['text']}" if has_section else chunk["text"])
            metadatas.append(
                {
                    "source": doc.filename,
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
