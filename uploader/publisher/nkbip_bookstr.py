from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Any, Tuple, Set
import orjson

from .parse_collection import CollectionTree, SectionEntry
from .util import slugify_strict, compress_slug_parts, sha256_hex


@dataclass
class Event:
    kind: int
    tags: List[List[str]]
    content: str

    def to_json(self) -> str:
        return orjson.dumps({"kind": self.kind, "tags": self.tags, "content": self.content}).decode("utf-8")


def _d_for(*parts: str) -> str:
    """
    Build a strict d-tag using only ASCII letters, digits, and hyphens.
    Join hierarchy with single hyphens (no slashes) and trim to <=75 chars.
    """
    norm = [slugify_strict(p) for p in parts if p]
    # Drop generic 'adoc' segment if present
    norm = [p for p in norm if p and p != "adoc"]
    # Remove empties
    norm = [p for p in norm if p]
    # Bible-like tail compression:
    # If the penultimate segment looks like "<book>-chapter-<num>"
    # and the last looks like "<n>-<m>" (section indices),
    # drop the "-chapter-<num>" suffix so we keep "<book>-<n>-<m>"
    if len(norm) >= 2:
        import re as _re
        penult = norm[-2]
        last = norm[-1]
        m_pen = _re.match(r"^(?P<book>.+)-chapter-\d+$", penult)
        m_last = _re.match(r"^\d+(?:-\d+.*)?$", last)
        if m_pen and m_last:
            # Replace penultimate with just the book base
            norm[-2] = m_pen.group("book")
    # Join and enforce length
    return compress_slug_parts(norm, max_len=75)


def serialize_bookstr(
    tree: CollectionTree,
    *,
    collection_id: str,
    language: str = "en",
    use_bookstr: bool = True,
    book_title_map: dict[str, str] | None = None,
) -> List[Event]:
    """
    Convert generic multi-level CollectionTree into bookstr-like events:
    - Determine section_level from tree.section_level
    - For each SectionEntry, treat:
        ancestors before (section_level - 2) as collection indexes (0..N)
        ancestor at (section_level - 2) as book
        ancestor at (section_level - 1) as chapter
        leaf at (section_level) as section content (30041)
    - Emit unique index events (kind 30040) for each path prefix
    """
    events: List[Event] = []
    emitted: Set[str] = set()

    def emit_index(d_path: List[str], title: str, maybe_book_title: str | None = None):
        d = _d_for(collection_id, *d_path)
        if d in emitted:
            return
        emitted.add(d)
        tags = [["d", d], ["t", title], ["L", language], ["m", "text/asciidoc"]]
        if use_bookstr and book_title_map and maybe_book_title:
            canon = book_title_map.get(maybe_book_title)
            if canon:
                tags.append(["name", canon])
        events.append(Event(kind=30040, tags=tags, content=""))

    # Build indices and pages
    for entry in tree.sections:
        titles = entry.path_titles
        levels = entry.path_levels
        # Identify indices
        section_level = tree.section_level
        # Find leaf index
        leaf_idx = len(titles) - 1
        # Heuristics to detect chapter vs book:
        # Prefer the nearest ancestor whose title contains 'chapter' as chapter,
        # and the previous ancestor as book (even if same heading level).
        chapter_idx = None
        for i in range(leaf_idx - 1, -1, -1):
            t = titles[i].lower()
            if "chapter" in t:
                chapter_idx = i
                break
        if chapter_idx is None:
            # Fallback: last ancestor before leaf
            chapter_idx = max(0, leaf_idx - 1)
        book_idx = max(0, chapter_idx - 1)

        # Emit collection indexes for each prefix up to book
        for i in range(0, book_idx):
            emit_index(titles[: i + 1], titles[i])

        # Emit book and chapter indexes
        if book_idx >= 0 and book_idx < len(titles):
            book_title = titles[book_idx]
            emit_index(titles[: book_idx + 1], book_title, maybe_book_title=book_title)
        if chapter_idx >= 0 and chapter_idx < len(titles):
            chapter_title = titles[chapter_idx]
            emit_index(titles[: chapter_idx + 1], chapter_title, maybe_book_title=(titles[book_idx] if book_idx < len(titles) else None))

        # Emit section content
        section_d = _d_for(collection_id, *titles)
        section_title = titles[-1]
        s_tags = [["d", section_d], ["t", section_title], ["L", language], ["m", "text/asciidoc"]]
        if use_bookstr and book_title_map and len(titles) >= 2:
            canon = book_title_map.get(titles[book_idx]) if book_idx < len(titles) else None
            if canon:
                s_tags.append(["name", canon])
        events.append(Event(kind=30041, tags=s_tags, content=entry.content))

    return events


