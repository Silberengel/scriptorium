from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Any, Tuple, Set
import orjson
import re

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
    # and the last looks like "<n>-<m>" (verse indices),
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
    metadata: Any | None = None,  # Metadata object with title, author, publisher, year, description
) -> List[Event]:
    """
    Convert generic multi-level CollectionTree into bookstr-like events:
    - Determine verse_level from tree.section_level
    - For each SectionEntry, treat:
        ancestors before (verse_level - 2) as collection indexes (0..N)
        ancestor at (verse_level - 2) as book
        ancestor at (verse_level - 1) as chapter
        leaf at (verse_level) as verse content (30041)
    - Emit unique index events (kind 30040) for each path prefix
    """
    events: List[Event] = []
    emitted: Set[str] = set()

    def emit_index(d_path: List[str], title: str, maybe_book_title: str | None = None, is_collection_root: bool = False, is_book: bool = False, is_chapter: bool = False):
        d = _d_for(collection_id, *d_path)
        if d in emitted:
            return
        emitted.add(d)
        # NKBIP-01 requires "title" tag (not "t"), and "d" tag
        tags = [["d", d], ["title", title], ["L", language], ["m", "text/asciidoc"]]
        if use_bookstr and book_title_map and maybe_book_title:
            canon = book_title_map.get(maybe_book_title)
            if canon:
                tags.append(["name", canon])
        
        # Get publication type from metadata (default to "book")
        pub_type = "book"
        if metadata and hasattr(metadata, "type") and metadata.type:
            pub_type = metadata.type
        
        # Add metadata fields for collection root events (per NKBIP-01)
        if is_collection_root and metadata:
            # Title is already added above, but ensure it uses metadata.title if available
            if hasattr(metadata, "title") and metadata.title:
                # Replace the title tag with metadata title
                tags = [[t[0], t[1]] if t[0] != "title" else ["title", metadata.title] for t in tags]
            if hasattr(metadata, "author") and metadata.author:
                tags.append(["author", metadata.author])
            if hasattr(metadata, "publisher") and metadata.publisher:
                tags.append(["publisher", metadata.publisher])
            if hasattr(metadata, "published_on") and metadata.published_on:
                tags.append(["published_on", str(metadata.published_on)])
            if hasattr(metadata, "published_by") and metadata.published_by:
                tags.append(["published_by", str(metadata.published_by)])
            if hasattr(metadata, "summary") and metadata.summary:
                tags.append(["summary", metadata.summary])
            
            # Add any additional tags specified by the user
            if hasattr(metadata, "additional_tags") and metadata.additional_tags:
                for tag in metadata.additional_tags:
                    # Ensure tag is a list and has at least one element
                    if isinstance(tag, list) and len(tag) > 0:
                        tags.append(tag)
        
        # Add type tag (for all index events)
        tags.append(["type", pub_type])
        
        # Add bookstr macro tags for book and chapter index events
        if use_bookstr and (is_book or is_chapter):
            
            # Add book tag if this is a book or chapter event
            if maybe_book_title:
                canon = None
                if book_title_map:
                    canon = book_title_map.get(maybe_book_title)
                if canon:
                    book_tag = slugify_strict(canon).lower()
                    tags.append(["book", book_tag])
                else:
                    book_tag = slugify_strict(maybe_book_title).lower()
                    tags.append(["book", book_tag])
            
            # Add chapter tag if this is a chapter event
            if is_chapter:
                chapter_match = re.search(r'chapter\s+(\d+)', title, re.IGNORECASE)
                if chapter_match:
                    chapter_num = chapter_match.group(1)
                    tags.append(["chapter", chapter_num])
            
            # Add version tag if available
            if metadata and hasattr(metadata, "version") and metadata.version:
                tags.append(["version", metadata.version.lower()])
        
        events.append(Event(kind=30040, tags=tags, content=""))

    # Build indices and pages
    for entry in tree.sections:
        titles = entry.path_titles
        levels = entry.path_levels
        # Identify indices
        verse_level = tree.section_level
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
            # First index (i == 0) is collection root - add metadata
            is_root = (i == 0)
            emit_index(titles[: i + 1], titles[i], is_collection_root=is_root)

        # Emit book and chapter indexes
        if book_idx >= 0 and book_idx < len(titles):
            book_title = titles[book_idx]
            emit_index(titles[: book_idx + 1], book_title, maybe_book_title=book_title, is_book=True)
        if chapter_idx >= 0 and chapter_idx < len(titles):
            chapter_title = titles[chapter_idx]
            emit_index(titles[: chapter_idx + 1], chapter_title, maybe_book_title=(titles[book_idx] if book_idx < len(titles) else None), is_chapter=True)

        # Emit verse content (kind 30041)
        verse_d = _d_for(collection_id, *titles)
        verse_title = titles[-1]
        # NKBIP-01 requires "title" tag (not "t") for kind 30041
        s_tags = [["d", verse_d], ["title", verse_title], ["L", language], ["m", "text/asciidoc"]]
        
        # Add bookstr macro tags for searchability
        if use_bookstr:
            # Add type tag from metadata (default to "book")
            pub_type = metadata.type if metadata and hasattr(metadata, "type") and metadata.type else "book"
            s_tags.append(["type", pub_type])
            
            # Extract and add book tag (canonical name, lowercase, hyphenated)
            if book_idx >= 0 and book_idx < len(titles):
                book_title = titles[book_idx]
                canon = None
                if book_title_map:
                    canon = book_title_map.get(book_title)
                if canon:
                    # Use canonical name, lowercase and hyphenated
                    book_tag = slugify_strict(canon).lower()
                    s_tags.append(["book", book_tag])
                else:
                    # Fallback to display title
                    book_tag = slugify_strict(book_title).lower()
                    s_tags.append(["book", book_tag])
            
            # Extract and add chapter tag
            if chapter_idx >= 0 and chapter_idx < len(titles):
                chapter_title = titles[chapter_idx]
                # Extract chapter number from title like "Genesis Chapter 1" or "1 Kings Chapter 1" or just "Chapter 1"
                chapter_match = re.search(r'chapter\s+(\d+)', chapter_title, re.IGNORECASE)
                if chapter_match:
                    chapter_num = chapter_match.group(1)
                    s_tags.append(["chapter", chapter_num])
            
            # Extract and add verse tag (if verse title matches verse pattern like "1:1" or "1:2")
            verse_match = re.match(r'^(\d+):(\d+)$', verse_title.strip())
            if verse_match:
                verse_num = verse_match.group(2)  # Just the verse number
                s_tags.append(["verse", verse_num])
            
            # Add version tag if available in metadata
            if metadata and hasattr(metadata, "version") and metadata.version:
                s_tags.append(["version", metadata.version.lower()])
        
        # Legacy name tag (for backward compatibility)
        if use_bookstr and book_title_map and len(titles) >= 2:
            canon = book_title_map.get(titles[book_idx]) if book_idx < len(titles) else None
            if canon:
                s_tags.append(["name", canon])
        
        events.append(Event(kind=30041, tags=s_tags, content=entry.content))

    return events


