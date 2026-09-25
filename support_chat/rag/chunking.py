"""Section-aware chunking for KB documents (generic heading detection, no
document-specific vocabulary — adapted from role-rag-app's rag/chunking.py)."""

import re

from support_chat.config import CHUNK_OVERLAP, CHUNK_SIZE
from support_chat.rag.extract import LoadedDocument, TextBlock

NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+\S")


def _is_metadata_line(line: str) -> bool:
    return line.startswith(("[LINKS]", "Links:"))


def _is_bullet(line: str) -> bool:
    return line.lstrip().startswith(("•", "-", "*", "●", "–", "○"))


def _is_heading(line: str, next_line: str | None = None) -> bool:
    line = line.strip()
    if not line or len(line) > 100:
        return False
    if _is_metadata_line(line) or _is_bullet(line):
        return False
    if NUMBERED_HEADING_RE.match(line):
        return True

    words = line.split()
    if not (1 <= len(words) <= 12 and len(line) <= 80):
        return False
    if ")" in line and not line.startswith("("):
        return False
    if "," in line and len(words) > 4:
        return False
    if line.endswith((".", "?", "!", ";")):
        return line.endswith(":") and len(words) <= 8
    if not (line[0].isupper() or line.isupper()):
        return False

    if next_line is None:
        return len(words) <= 5
    next_line = next_line.strip()
    if not next_line:
        return len(words) <= 8
    if _is_bullet(next_line):
        return True
    if len(next_line) > len(line):
        return True
    return False


def _split_long_section(section: str, text: str, page: int) -> list[dict]:
    if len(text) <= CHUNK_SIZE:
        return [{"section": section, "text": text, "page": page}]

    chunks = []
    start = 0
    part = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        # Prefer to break between bullets (or table rows) rather than mid-item, so an
        # item's label stays in the same chunk as its details.
        boundary = text.rfind(" • ", start + CHUNK_SIZE // 2, end) if end < len(text) else -1
        if boundary != -1:
            end = boundary
        piece = text[start:end]
        title = section if part == 0 else f"{section} (cont.)"
        chunks.append({"section": title, "text": piece, "page": page})
        if end >= len(text):
            break
        start = boundary + 1 if boundary != -1 else end - CHUNK_OVERLAP
        part += 1
    return chunks


def chunk_document(doc: LoadedDocument) -> list[dict]:
    lines_with_page: list[tuple[int, str]] = []
    for block in doc.blocks:
        for line in block.text.split("\n"):
            stripped = line.strip()
            if stripped:
                lines_with_page.append((block.page, stripped))

    if not lines_with_page:
        return []

    sections: list[dict] = []
    current_title = doc.filename
    current_lines: list[str] = []
    current_pages: list[int] = []

    def flush() -> None:
        nonlocal current_lines, current_pages, current_title
        if not current_lines:
            return
        text = " ".join(current_lines)
        sections.extend(_split_long_section(current_title, text, min(current_pages)))
        current_lines = []
        current_pages = []

    for i, (page, line) in enumerate(lines_with_page):
        next_line = lines_with_page[i + 1][1] if i + 1 < len(lines_with_page) else None

        if line.startswith("[LINKS]"):
            current_lines.append(line.replace("[LINKS]", "Links:").strip())
            current_pages.append(page)
            continue

        if _is_heading(line, next_line):
            flush()
            current_title = line.rstrip(":")
            current_pages = [page]
            continue

        current_lines.append(line)
        current_pages.append(page)

    flush()
    return sections
