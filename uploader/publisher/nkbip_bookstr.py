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
    book_title_map: dict[str, dict[str, str] | str] | None = None,  # Supports both new format (dict) and old format (str)
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
    emitted: Set[str] = set()  # Track emitted d-tags for index events (kind 30040)
    emitted_verse_d_tags: Set[str] = set()  # Track emitted d-tags for verse content events (kind 30041)
    d_tag_to_parent_d: Dict[str, str] = {}  # Track parent d-tags for a-tag generation
    parent_section_count: Dict[str, int] = {}  # Track section count per parent for unique d-tags

    def emit_index(d_path: List[str], title: str, maybe_book_title: str | None = None, is_collection_root: bool = False, is_book: bool = False, is_chapter: bool = False):
        d = _d_for(collection_id, *d_path)
        if d in emitted:
            return
        emitted.add(d)
        # NKBIP-01 requires "title" tag (not "t"), and "d" tag
        tags = [["d", d], ["title", title], ["L", language], ["m", "text/asciidoc"]]
        
        # Track parent d-tag for a-tag generation (parent is prefix of d_path)
        if len(d_path) > 1:
            parent_d = _d_for(collection_id, *d_path[:-1])
            d_tag_to_parent_d[d] = parent_d
        if use_bookstr and book_title_map and maybe_book_title:
            # Case-insensitive lookup
            canon_info = book_title_map.get(maybe_book_title.lower())
            if canon_info:
                # Support both old format (string) and new format (dict)
                if isinstance(canon_info, dict):
                    canon = canon_info.get("canonical-long", "")
                else:
                    canon = str(canon_info)
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
                canon_info = None
                if book_title_map:
                    # Case-insensitive lookup
                    canon_info = book_title_map.get(maybe_book_title.lower())
                if canon_info:
                    # Support both old format (string) and new format (dict)
                    if isinstance(canon_info, dict):
                        canon_long = canon_info.get("canonical-long", "")
                        canon_short = canon_info.get("canonical-short", "")
                        if canon_long:
                            book_tag_long = slugify_strict(canon_long).lower()
                            tags.append(["book", book_tag_long])
                        if canon_short and canon_short != canon_long:
                            book_tag_short = slugify_strict(canon_short).lower()
                            tags.append(["book", book_tag_short])
                    else:
                        # Old format: single canonical name
                        canon = str(canon_info)
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
        
        # Check if this is content at a level other than verse_level - these become "-section" events
        # Content at verse_level is handled as normal verses below
        current_level = levels[leaf_idx] if leaf_idx < len(levels) else verse_level
        is_section_content = current_level != verse_level
        
        if is_section_content:
            # Content at non-verse level (e.g., introduction, preambles) - emit as kind 30041 with "-section" suffix
            # Determine parent d-tag based on path structure
            parent_d_tag = None
            
            # Emit indexes for all ancestors up to the parent
            if len(titles) > 1:
                # Has parent(s) - emit indexes for ancestors
                for i in range(len(titles) - 1):
                    is_root = (i == 0)
                    emit_index(titles[: i + 1], titles[i], is_collection_root=is_root)
                # Get parent d-tag (the immediate parent)
                parent_d_tag = _d_for(collection_id, *titles[:-1])
            elif len(titles) == 1:
                # Only one title - parent is collection root
                is_root = True
                emit_index(titles[:1], titles[0], is_collection_root=is_root)
                parent_d_tag = _d_for(collection_id, titles[0])
            
            # Emit content as kind 30041
            # Use parent d-tag with "-section-N" appended (N is incrementing counter per parent)
            if parent_d_tag:
                # Increment counter for this parent
                if parent_d_tag not in parent_section_count:
                    parent_section_count[parent_d_tag] = 0
                parent_section_count[parent_d_tag] += 1
                section_num = parent_section_count[parent_d_tag]
                verse_d = f"{parent_d_tag}-section-{section_num}"
            else:
                # Fallback: use collection_id-section if no parent
                if collection_id not in parent_section_count:
                    parent_section_count[collection_id] = 0
                parent_section_count[collection_id] += 1
                section_num = parent_section_count[collection_id]
                verse_d = f"{collection_id}-section-{section_num}"
            
            verse_title = titles[-1] if titles else "Section"
            s_tags = [["d", verse_d], ["title", verse_title], ["L", language], ["m", "text/asciidoc"]]
            
            # Add type tag
            pub_type = metadata.type if metadata and hasattr(metadata, "type") and metadata.type else "book"
            s_tags.append(["type", pub_type])
            
            # Add version tag if available
            if metadata and hasattr(metadata, "version") and metadata.version:
                s_tags.append(["version", metadata.version.lower()])
            
            # Track parent d-tag for a-tag generation
            if parent_d_tag:
                d_tag_to_parent_d[verse_d] = parent_d_tag
            
            events.append(Event(kind=30041, tags=s_tags, content=entry.content))
            continue
        
        # Standard book/chapter/verse structure
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
        
        # Check if this d-tag has already been emitted (deduplicate)
        if verse_d in emitted_verse_d_tags:
            # Skip duplicate verse - this can happen if the same verse appears multiple times
            # in the document structure. We'll keep the first occurrence.
            continue
        
        emitted_verse_d_tags.add(verse_d)
        verse_title = titles[-1]
        # NKBIP-01 requires "title" tag (not "t") for kind 30041
        s_tags = [["d", verse_d], ["title", verse_title], ["L", language], ["m", "text/asciidoc"]]
        
        # Track parent d-tag (chapter d-tag) for a-tag generation
        if chapter_idx >= 0 and chapter_idx < len(titles):
            parent_d = _d_for(collection_id, *titles[:chapter_idx + 1])
            d_tag_to_parent_d[verse_d] = parent_d
        
        # Add bookstr macro tags for searchability
        if use_bookstr:
            # Add type tag from metadata (default to "book")
            pub_type = metadata.type if metadata and hasattr(metadata, "type") and metadata.type else "book"
            s_tags.append(["type", pub_type])
            
            # Extract and add book tag (canonical name, lowercase, hyphenated)
            if book_idx >= 0 and book_idx < len(titles):
                book_title = titles[book_idx]
                canon_info = None
                if book_title_map:
                    # Case-insensitive lookup
                    canon_info = book_title_map.get(book_title.lower())
                if canon_info:
                    # Support both old format (string) and new format (dict)
                    if isinstance(canon_info, dict):
                        canon_long = canon_info.get("canonical-long", "")
                        canon_short = canon_info.get("canonical-short", "")
                        if canon_long:
                            book_tag_long = slugify_strict(canon_long).lower()
                            s_tags.append(["book", book_tag_long])
                        if canon_short and canon_short != canon_long:
                            book_tag_short = slugify_strict(canon_short).lower()
                            s_tags.append(["book", book_tag_short])
                    else:
                        # Old format: single canonical name
                        canon = str(canon_info)
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
            # Case-insensitive lookup
            canon_info = book_title_map.get(titles[book_idx].lower()) if book_idx < len(titles) else None
            if canon_info:
                # Support both old format (string) and new format (dict)
                if isinstance(canon_info, dict):
                    canon = canon_info.get("canonical-long", "")
                else:
                    canon = str(canon_info)
                if canon:
                    s_tags.append(["name", canon])
        
        events.append(Event(kind=30041, tags=s_tags, content=entry.content))

    # Build parent -> children mapping for a-tag generation
    # Format: parent d-tag -> list of (child_kind, child_d_tag)
    parent_d_to_children: Dict[str, List[Tuple[int, str]]] = {}
    
    # Add parent d-tag references to events and build child map
    for event in events:
        d_tag = None
        parent_d = None
        for tag in event.tags:
            if tag and len(tag) > 0:
                if tag[0] == "d":
                    d_tag = tag[1] if len(tag) > 1 else None
                elif tag[0] == "_parent_d":
                    parent_d = tag[1] if len(tag) > 1 else None
        
        # If this event has a parent, add it to the parent's children list
        if d_tag and parent_d:
            if parent_d not in parent_d_to_children:
                parent_d_to_children[parent_d] = []
            parent_d_to_children[parent_d].append((event.kind, d_tag))
        
        # Also check d_tag_to_parent_d for events that don't have _parent_d tag yet
        if d_tag and d_tag in d_tag_to_parent_d:
            parent_d = d_tag_to_parent_d[d_tag]
            event.tags.append(["_parent_d", parent_d])
            if parent_d not in parent_d_to_children:
                parent_d_to_children[parent_d] = []
            parent_d_to_children[parent_d].append((event.kind, d_tag))
    
    # Add a-tags to kind 30040 events (index events)
    # Use placeholder pubkey "0000000000000000000000000000000000000000000000000000000000000000"
    # This will be replaced with the actual pubkey during publishing
    PLACEHOLDER_PUBKEY = "0000000000000000000000000000000000000000000000000000000000000000"
    for event in events:
        if event.kind == 30040:
            d_tag = None
            for tag in event.tags:
                if tag and len(tag) > 0 and tag[0] == "d":
                    d_tag = tag[1] if len(tag) > 1 else None
                    break
            
            # Add a-tags for all children of this index event
            if d_tag and d_tag in parent_d_to_children:
                for child_kind, child_d in parent_d_to_children[d_tag]:
                    # Format: ["a", "<kind>:<pubkey>:<d-tag>"]
                    a_tag = ["a", f"{child_kind}:{PLACEHOLDER_PUBKEY}:{child_d}"]
                    event.tags.append(a_tag)

    return events


