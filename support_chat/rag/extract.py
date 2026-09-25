import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md"}


@dataclass
class TextBlock:
    page: int
    text: str
    links: list[str] = field(default_factory=list)


@dataclass
class LoadedDocument:
    filename: str
    blocks: list[TextBlock]


def _normalize(text: str) -> str:
    text = text.replace(" ", " ").replace("﻿", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _inline_links(text: str, links: list[str]) -> str:
    if not links:
        return text
    missing = [url for url in links if url and url not in text]
    if missing:
        text = f"{text}\n\n[LINKS] {' | '.join(missing)}"
    return text


_LONE_BULLET_RE = re.compile(r"^[ \t]*([•●○▪◦])[ \t]*\n(?=[ \t]*\S)", re.MULTILINE)


def _join_lone_bullets(text: str) -> str:
    """Some PDFs emit the bullet glyph on its own line, with the item text on the
    next one. Left alone, the chunker mistakes that text for a heading and the
    item's content ends up in section metadata instead of the chunk."""
    return _LONE_BULLET_RE.sub(r"\1 ", text.replace("​", ""))


def _clean_cell(cell) -> str:
    return " ".join((cell or "").split())


def _table_to_lines(rows: list[list]) -> list[str]:
    """One self-contained line per data row ("Row label — Header: value; ..."), so a
    row can be retrieved on its own. The leading bullet keeps the chunker from
    mistaking a short row for a heading."""
    if len(rows) < 2:
        return []
    header = [_clean_cell(c) for c in rows[0]]
    lines = []
    for row in rows[1:]:
        cells = [_clean_cell(c) for c in row]
        if not any(cells):
            continue
        pairs = [f"{h}: {c}" if h else c for h, c in zip(header[1:], cells[1:]) if c]
        label = cells[0]
        lines.append(f"• {label} — {'; '.join(pairs)}" if label and pairs else f"• {' '.join(c for c in cells if c)}")
    return lines


def _page_text(page) -> str:
    """Page text in reading order, with tables rendered row-by-row instead of as
    the scrambled cell-by-cell text get_text() produces."""
    tables = page.find_tables().tables
    if not tables:
        return _join_lone_bullets(page.get_text())

    table_rects = [pymupdf.Rect(t.bbox) for t in tables]
    items: list[tuple[float, str]] = []
    for x0, y0, x1, y1, text, _no, block_type in page.get_text("blocks"):
        centre = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)
        if block_type == 0 and not any(centre in rect for rect in table_rects):
            items.append((y0, text))
    for table, rect in zip(tables, table_rects):
        items.append((rect.y0, "\n".join(_table_to_lines(table.extract())) + "\n"))
    items.sort(key=lambda item: item[0])
    return _join_lone_bullets("".join(text if text.endswith("\n") else text + "\n" for _, text in items))


def load_pdf(path: Path) -> LoadedDocument:
    doc = pymupdf.open(path)
    blocks: list[TextBlock] = []
    try:
        for page_num, page in enumerate(doc, start=1):
            text = _normalize(_page_text(page))
            links = [link["uri"] for link in page.get_links() if link.get("uri")]
            text = _inline_links(text, links)
            if text:
                blocks.append(TextBlock(page=page_num, text=text, links=links))
    finally:
        doc.close()
    return LoadedDocument(filename=path.name, blocks=blocks)


def load_text_file(path: Path) -> LoadedDocument:
    text = _normalize(path.read_text(encoding="utf-8"))
    if not text:
        return LoadedDocument(filename=path.name, blocks=[])
    return LoadedDocument(filename=path.name, blocks=[TextBlock(page=1, text=text, links=[])])


def load_document(path: Path) -> LoadedDocument:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(path)
    if suffix in {".txt", ".md"}:
        return load_text_file(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")
