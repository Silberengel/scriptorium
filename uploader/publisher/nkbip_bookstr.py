from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Any, Tuple, Set
import orjson
import re

from .parse_collection import CollectionTree, SectionEntry
from .util import slugify_strict, compress_slug_parts, sha256_hex


def normalize_nkbip08_tag_value(text: str) -> str:
    """
    Normalize tag values according to NKBIP-08 (NIP-54 rules):
    - Remove quotes
    - Convert any non-letter character to a hyphen
    - Convert all letters to lowercase
    - Numbers are preserved (not converted to hyphens)
    - Collapse multiple hyphens to single hyphen
    - Trim leading/trailing hyphens
    
    IMPORTANT: This handles hierarchical paths with colons (e.g., "part-1:question-2:article-3")
    by converting colons to hyphens, resulting in "part-1-question-2-article-3" as per NKBIP-08 spec.
    """
    if not text:
        return ""
    # Remove quotes (single and double)
    text = text.strip().strip('"\'')
    # Normalize: lowercase, convert non-letter non-number to hyphen
    # Per NKBIP-08: "Section identifiers cannot contain colons in tag values.
    # Hierarchical paths with colons MUST be normalized: colons → hyphens"
    normalized = ""
    for char in text:
        if char.isalnum():
            normalized += char.lower()
        else:
            # Non-alphanumeric (including colons) becomes hyphen (but don't add consecutive hyphens)
            if normalized and normalized[-1] != "-":
                normalized += "-"
    # Collapse multiple hyphens
    normalized = re.sub(r"-+", "-", normalized)
    # Trim leading/trailing hyphens
    normalized = normalized.strip("-")
    return normalized


@dataclass
class Event:
    kind: int
    tags: List[List[str]]
    content: str

    def to_json(self) -> str:
        return orjson.dumps({"kind": self.kind, "tags": self.tags, "content": self.content}).decode("utf-8")


def _add_book_t_tags(tags: List[List[str]], book_title: str, book_title_map: dict[str, dict[str, str] | str] | None) -> None:
    """
    Add all three T tags for a book: display, canonical-long, and canonical-short.
    This allows searching by any variant: T=The Book of Genesis, T=Genesis, or T=Gen
    """
    if not book_title:
        return
    
    # Get canonical info from map if available
    canon_info = None
    if book_title_map:
        canon_info = book_title_map.get(book_title.lower())
    
    # Add T tag for display title (normalized)
    display_tag = normalize_nkbip08_tag_value(book_title)
    if display_tag:
        tags.append(["T", display_tag])
    
    # Add T tags for canonical names if available
    if canon_info:
        if isinstance(canon_info, dict):
            canon_long = canon_info.get("canonical-long", "")
            canon_short = canon_info.get("canonical-short", "")
            
            # Add canonical-long T tag (normalized)
            canon_long_tag = None
            if canon_long:
                canon_long_tag = normalize_nkbip08_tag_value(canon_long)
                if canon_long_tag and canon_long_tag != display_tag:  # Avoid duplicates
                    tags.append(["T", canon_long_tag])
            
            # Add canonical-short T tag (normalized)
            if canon_short and canon_short != canon_long:  # Only add if different from long
                canon_short_tag = normalize_nkbip08_tag_value(canon_short)
                if canon_short_tag and canon_short_tag != display_tag:
                    # Also check against canonical-long tag if it was added
                    if canon_long_tag is None or canon_short_tag != canon_long_tag:
                        tags.append(["T", canon_short_tag])
        else:
            # Old format: single canonical string
            canon_tag = normalize_nkbip08_tag_value(str(canon_info))
            if canon_tag and canon_tag != display_tag:  # Avoid duplicates
                tags.append(["T", canon_tag])


def _d_for(*parts: str) -> str:
    """
    Build a strict d-tag using only ASCII letters, digits, and hyphens.
    Join hierarchy with single hyphens (no slashes) and trim to <=75 chars.
    
    Improvements:
    - Removes common stop words that cause repetition
    - Deduplicates repeated segments
    - Uses abbreviations for common collection/part names
    - Compresses verbose titles to essential parts only
    """
    norm = [slugify_strict(p) for p in parts if p]
    # Drop generic 'adoc' segment if present
    norm = [p for p in norm if p and p != "adoc"]
    # Remove empties
    norm = [p for p in norm if p]
    
    if not norm:
        return ""
    
    # Special handling: if a segment is just a number (verse/section), preserve it as-is
    # This ensures verse numbers like "3:16" -> "3-16" are preserved
    for i, seg in enumerate(norm):
        # Check if segment is a verse pattern like "3-16" or just a number
        if re.match(r'^\d+(-\d+)*$', seg):
            # This is a verse/section number - keep it as-is, don't process further
            continue
    
    # Abbreviation map for common collection/part names
    # Used for both full segment matches and individual word matches
    segment_abbrev_map = {
        "old-testament": "ot",
        "new-testament": "nt",
        "according": "acc",
        "verse": "v",
        "chapter": "ch",
        "section": "s",
        "introduction": "intro",
        "book": "bk",
        "book-of": "bk",
        "book-of-the": "bk",
        "act": "a"
    }
    
    # Common stop words to remove from middle segments (keep in first/last)
    stop_words = {"the", "of", "to", "and", "a", "an", "in", "on", "at", "for", "with", "by", "st", "saint"}
    
    # Process segments to remove stop words, deduplicate, and abbreviate
    processed = []
    seen_words = set()
    
    # Heuristics to identify book title segments (segments that likely contain book names)
    # These keywords suggest a segment is a book title
    book_title_keywords = {"gospel", "book", "epistle", "prophecy", "psalm", "proverb", "kings", "machabees", 
                          "paralipomenon", "esdras", "corinthians", "thessalonians", "timothy", "titus", 
                          "peter", "john", "jude", "revelation", "apocalypse", "acts", "romans", "hebrews"}
    
    # Track which processed segments are book titles (by index) - initialize before loop
    book_title_indices = set()
    
    for i, segment in enumerate(norm):
        # Check if this is a verse/section number pattern (e.g., "3-16", "3", "16")
        # If it matches the pattern for a section (has multiple numbers like "1-31"), add "s-" prefix
        if re.match(r'^\d+(-\d+)+$', segment):
            # This is a section number (multiple numbers separated by hyphens) - add "s-" prefix
            # e.g., "1-31" -> "s-1-31"
            processed.append(f"s-{segment}")
            continue
        elif re.match(r'^\d+$', segment):
            # Single number - could be verse or chapter number, preserve as-is
            processed.append(segment)
            continue
        
        # First, check if the entire segment matches an abbreviation
        if segment in segment_abbrev_map:
            abbrev_segment = segment_abbrev_map[segment]
            processed.append(abbrev_segment)
            seen_words.add(abbrev_segment)
            continue
        
        # Check if this segment looks like a book title
        # If it contains book title keywords, preserve it more fully
        segment_lower = segment.lower()
        is_book_title = any(keyword in segment_lower for keyword in book_title_keywords)
        
        # Check if segment contains "old-testament" or "new-testament" and replace
        # This handles cases where "old-testament" appears as part of a longer segment
        if "old-testament" in segment:
            segment = segment.replace("old-testament", "ot")
        elif "new-testament" in segment:
            segment = segment.replace("new-testament", "nt")
        
        # Split segment into words
        words = segment.split("-")
        filtered_words = []
        
        # Process individual words
        for word_idx, word in enumerate(words):
            # Apply abbreviations from segment_abbrev_map
            if word in segment_abbrev_map:
                word = segment_abbrev_map[word]
            # Special handling: "old" -> "ot" (but only if not already part of "old-testament" which was replaced above)
            elif word == "old":
                word = "ot"
            # Special handling: "new" -> "nt" (but only if not already part of "new-testament" which was replaced above)
            elif word == "new":
                word = "nt"
            
            # For book titles: preserve all significant words (don't remove stop words or deduplicate)
            # This ensures "mark" vs "matthew" are preserved
            if is_book_title:
                # Only skip very short stop words (1-2 chars) from book titles, keep everything else
                if word in stop_words and len(word) <= 2:
                    continue
                filtered_words.append(word)
                # Don't track words from book titles in seen_words to avoid deduplication
                continue
            
            # For non-book-title segments: apply normal filtering
            # For middle segments, skip stop words (but keep them in first and last segments)
            if (i > 0 and i < len(norm) - 1) and word in stop_words:
                continue
            
            # Skip if we've seen this exact word recently (deduplicate)
            # BUT: don't skip numbers (verse/section numbers) or chapter numbers
            is_number = word.isdigit()
            if word in seen_words and len(processed) > 0 and not is_number:
                # Only skip if it's a very common word or short
                if word in stop_words or len(word) <= 2:
                    continue
            
            filtered_words.append(word)
            if not is_number:  # Don't track numbers in seen_words (they can repeat)
                seen_words.add(word)
        
        # Special handling: if we have "ot" and "t" together (from "old" + "testament"), combine to "ot"
        # This handles cases where "old-testament" was split before replacement
        if len(filtered_words) >= 2:
            for j in range(len(filtered_words) - 1):
                if filtered_words[j] == "ot" and filtered_words[j + 1] == "t":
                    # Combine "ot" + "t" -> "ot" (old + testament)
                    filtered_words.pop(j + 1)
                    break
                elif filtered_words[j] == "nt" and filtered_words[j + 1] == "t":
                    # Combine "nt" + "t" -> "nt" (new + testament)
                    filtered_words.pop(j + 1)
                    break
        
        if filtered_words:
            processed_segment = "-".join(filtered_words)
            # Collapse any double hyphens that might have been created
            processed_segment = re.sub(r"-+", "-", processed_segment)
            processed_segment = processed_segment.strip("-")
            # Only add non-empty segments
            if processed_segment:
                processed.append(processed_segment)
                # Track if this is a book title segment
                if is_book_title:
                    book_title_indices.add(len(processed) - 1)
    
    # If processing removed everything, fall back to original
    if not processed:
        processed = norm
    
    # Additional compression: remove duplicate book names and words
    # Handle cases like:
    # - "aggeus-aggeus-2-5" -> "aggeus-2-5" (duplicate segment)
    # - "genesis-genesis-1-2" -> "genesis-1-2" (duplicate segment)
    # - "book-genesis" followed by "genesis-1-2" -> "book-genesis-1-2" (word at boundary)
    # BUT: be careful not to remove numbers (verse/section numbers)
    
    # Pass 1: Remove exact duplicate consecutive segments
    i = 0
    while i < len(processed) - 1:
        if processed[i] == processed[i + 1]:
            processed.pop(i)
            continue
        i += 1
    
    # Pass 2: Remove segments that are prefixes of the next segment
    # e.g., "genesis" followed by "genesis-chapter-3" -> remove "genesis"
    # BUT: Don't remove book title segments
    i = 0
    while i < len(processed) - 1:
        current = processed[i]
        next_seg = processed[i + 1]
        
        # Don't remove book title segments
        if i in book_title_indices or (i + 1) in book_title_indices:
            i += 1
            continue
        
        # If current is a single word and next starts with it, remove current
        if len(current.split("-")) == 1 and next_seg.startswith(current + "-"):
            processed.pop(i)
            # Adjust book_title_indices after removal
            book_title_indices = {idx - 1 if idx > i else idx for idx in book_title_indices}
            continue
        
        # If next is a single word and current ends with it, remove next
        if len(next_seg.split("-")) == 1 and current.endswith("-" + next_seg):
            processed.pop(i + 1)
            # Adjust book_title_indices after removal
            book_title_indices = {idx - 1 if idx > i + 1 else idx for idx in book_title_indices}
            continue
        
        i += 1
    
    # Pass 3: Remove duplicate words at segment boundaries
    # e.g., "book-genesis" followed by "genesis-1-2" -> "book-genesis-1-2"
    # BUT: Don't deduplicate words from book title segments
    i = 0
    while i < len(processed) - 1:
        # Don't deduplicate if either segment is a book title
        if i in book_title_indices or (i + 1) in book_title_indices:
            i += 1
            continue
        
        current_words = processed[i].split("-")
        next_words = processed[i + 1].split("-")
        
        if current_words and next_words:
            last_word = current_words[-1]
            first_word = next_words[0]
            
            # Don't deduplicate numbers
            if (not last_word.isdigit() and not first_word.isdigit() and 
                last_word == first_word and len(last_word) > 2):
                
                # Remove duplicate from next segment (remove first word)
                if len(next_words) > 1:
                    next_words = next_words[1:]
                    processed[i + 1] = "-".join(next_words)
                else:
                    # Next segment becomes empty, remove it
                    processed.pop(i + 1)
                    # Adjust book_title_indices after removal
                    book_title_indices = {idx - 1 if idx > i + 1 else idx for idx in book_title_indices}
                    continue
        
        i += 1
    
    # Pass 4: Final cleanup - remove any remaining exact duplicates
    i = 0
    while i < len(processed) - 1:
        if processed[i] == processed[i + 1]:
            processed.pop(i)
            continue
        i += 1
    
    # Bible-like tail compression:
    # If the penultimate segment looks like "<book>-chapter-<num>"
    # and the last looks like "<n>-<m>" (verse indices),
    # drop the "-chapter-<num>" suffix so we keep "<book>-<n>-<m>"
    if len(processed) >= 2:
        import re as _re
        penult = processed[-2]
        last = processed[-1]
        m_pen = _re.match(r"^(?P<book>.+)-chapter-\d+$", penult)
        m_last = _re.match(r"^\d+(?:-\d+.*)?$", last)
        if m_pen and m_last:
            # Replace penultimate with just the book base
            processed[-2] = m_pen.group("book")
    
    # Final cleanup: collapse any remaining double hyphens and remove empty segments
    final_parts = []
    for part in processed:
        # Collapse double hyphens within each part
        cleaned = re.sub(r"-+", "-", part).strip("-")
        # Only add non-empty parts
        if cleaned:
            final_parts.append(cleaned)
    
    if not final_parts:
        final_parts = processed
    
    # Join and enforce length
    result = compress_slug_parts(final_parts, max_len=75)
    # Final safety check: collapse any double hyphens in the final result
    # This handles cases where compress_slug_parts might create double hyphens
    result = re.sub(r"-+", "-", result).strip("-")
    return result


def serialize_bookstr(
    tree: CollectionTree,
    *,
    collection_id: str,
    language: str = "en",
    use_bookstr: bool = True,
    book_title_map: dict[str, dict[str, str] | str] | None = None,  # Supports both new format (dict) and old format (str)
    metadata: Any | None = None,  # Metadata object with title, author, published_by, published_on, summary, etc.
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
    d_tag_to_event_type: Dict[str, str] = {}  # Track event type: "book" (T-level), "chapter" (c-level), or "collection"

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
        # Note: "name" tag removed - using NKBIP-08 T tag instead
        
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
            if hasattr(metadata, "published_on") and metadata.published_on:
                tags.append(["published_on", str(metadata.published_on)])
            if hasattr(metadata, "published_by") and metadata.published_by:
                tags.append(["published_by", str(metadata.published_by)])
            if hasattr(metadata, "summary") and metadata.summary:
                tags.append(["summary", metadata.summary])
            if hasattr(metadata, "source") and metadata.source:
                tags.append(["source", metadata.source])
            if hasattr(metadata, "image") and metadata.image:
                tags.append(["image", metadata.image])
            
            # Add derivative works tags (p and E) if specified
            # Per NKBIP-01: p tag identifies original author, E tag immediately follows with original event reference
            if hasattr(metadata, "derivative_author") and metadata.derivative_author:
                tags.append(["p", metadata.derivative_author])
                # E tag must immediately follow p tag per NKBIP-01
                # Format: ["E", "<original_event_id>", "<relay_url>", "<pubkey>"]
                if hasattr(metadata, "derivative_event") and metadata.derivative_event:
                    relay_url = ""
                    pubkey = ""
                    if hasattr(metadata, "derivative_relay") and metadata.derivative_relay:
                        relay_url = metadata.derivative_relay
                    if hasattr(metadata, "derivative_pubkey") and metadata.derivative_pubkey:
                        pubkey = metadata.derivative_pubkey
                    elif hasattr(metadata, "derivative_author") and metadata.derivative_author:
                        # Use derivative_author as fallback for pubkey
                        pubkey = metadata.derivative_author
                    tags.append(["E", metadata.derivative_event, relay_url, pubkey])
            
            # Add any additional tags specified by the user
            if hasattr(metadata, "additional_tags") and metadata.additional_tags:
                for tag in metadata.additional_tags:
                    # Ensure tag is a list and has at least one element
                    if isinstance(tag, list) and len(tag) > 0:
                        tags.append(tag)
        
        # Add type tag (for all index events)
        tags.append(["type", pub_type])
        
        # Add auto-update tag (required per NKBIP-01)
        auto_update_val = "ask"  # Default value
        if metadata and hasattr(metadata, "auto_update") and metadata.auto_update:
            auto_update_val = metadata.auto_update
        tags.append(["auto-update", auto_update_val])
        
        # Add image and summary to ALL events (unless overridden at chapter/section level)
        # TODO: Support chapter/section-level overrides in the future
        if metadata:
            if hasattr(metadata, "image") and metadata.image:
                tags.append(["image", metadata.image])
            if hasattr(metadata, "summary") and metadata.summary:
                tags.append(["summary", metadata.summary])
        
        # Add NKBIP-08 tags for book wikilinks (hierarchical - each level includes parent tags)
        # Per NKBIP-08 spec:
        # - T tag is MANDATORY (only T tag must be present)
        # - C, c, s, v tags are optional
        # - All tags MAY be repeated to support multiple aliases (optional feature)
        # - Tag values MUST contain only lowercase ASCII letters, numbers, and hyphens
        # - Hierarchical paths with colons are normalized (colons → hyphens)
        # C tag (collection) - add to ALL events if collection_id is defined
        if collection_id:
            c_tag_value = normalize_nkbip08_tag_value(collection_id)
            if c_tag_value:
                tags.append(["C", c_tag_value])
        
        # T tag (title) - for title/book events (collection root or book index)
        if is_collection_root or is_book:
            if is_collection_root and metadata and hasattr(metadata, "title") and metadata.title:
                # Collection root uses metadata title (single T tag)
                t_tag_value = normalize_nkbip08_tag_value(metadata.title)
                if t_tag_value:
                    tags.append(["T", t_tag_value])
            elif is_book and maybe_book_title:
                # Book index: add all three T tags (display, canonical-long, canonical-short)
                _add_book_t_tags(tags, maybe_book_title, book_title_map)
        
        # For chapter events, we need to inherit T tag from parent book
        # We'll compute it from the path structure
        if is_chapter:
            # Find book title from path (parent of chapter)
            if len(d_path) > 0:
                # The book should be at the level before chapter
                # For now, we'll try to find it from maybe_book_title or from the path
                book_title_for_t = maybe_book_title
                if not book_title_for_t and len(d_path) > 1:
                    # Try to get book title from parent path
                    book_title_for_t = d_path[-2] if len(d_path) >= 2 else None
                
                if book_title_for_t:
                    # Add all three T tags (display, canonical-long, canonical-short)
                    _add_book_t_tags(tags, book_title_for_t, book_title_map)
            
            # c tag (chapter) - for chapter index events
            chapter_match = re.search(r'chapter\s+(\d+)', title, re.IGNORECASE)
            if chapter_match:
                chapter_num = chapter_match.group(1)
                c_tag_value = normalize_nkbip08_tag_value(chapter_num)
            else:
                # Use normalized title as chapter identifier
                c_tag_value = normalize_nkbip08_tag_value(title)
            if c_tag_value:
                tags.append(["c", c_tag_value])
        
        # v tag (version) - add to ALL events when version is specified
        if metadata and hasattr(metadata, "version") and metadata.version:
            v_tag_value = normalize_nkbip08_tag_value(metadata.version)
            if v_tag_value:
                tags.append(["v", v_tag_value])
        
        # Track event type for a-tag filtering (per NKBIP-08: T-level events should only contain c-level events)
        if is_book:
            d_tag_to_event_type[d] = "book"  # T-level event
        elif is_chapter:
            d_tag_to_event_type[d] = "chapter"  # c-level event
        elif is_collection_root:
            d_tag_to_event_type[d] = "collection"  # Collection root
        
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
            
            # Check for duplicate d-tag (should not happen, but verify)
            if verse_d in emitted_verse_d_tags:
                # This is a duplicate - skip it
                continue
            
            emitted_verse_d_tags.add(verse_d)
            verse_title = titles[-1] if titles else "Section"
            s_tags = [["d", verse_d], ["title", verse_title], ["L", language], ["m", "text/asciidoc"]]
            
            # Add type tag (formatting hint for clients, default to "book")
            pub_type = metadata.type if metadata and hasattr(metadata, "type") and metadata.type else "book"
            s_tags.append(["type", pub_type])
            
            # Add NKBIP-08 tags for section content events (hierarchical - include parent tags)
            # C tag (collection) - add to ALL events if collection_id is defined
            if collection_id:
                c_tag_value = normalize_nkbip08_tag_value(collection_id)
                if c_tag_value:
                    s_tags.append(["C", c_tag_value])
            
            # T tag (title) - try to find book title from parent path
            if len(titles) > 0:
                # Try to find book title (usually at index 0 or 1)
                book_title_for_tag = None
                for i, t in enumerate(titles):
                    # Heuristic: if we have a book_title_map, check if this title matches
                    if book_title_map and t.lower() in book_title_map:
                        book_title_for_tag = t
                        break
                if not book_title_for_tag and len(titles) > 0:
                    book_title_for_tag = titles[0]  # Use first title as fallback
                
                if book_title_for_tag:
                    # Add all three T tags (display, canonical-long, canonical-short)
                    _add_book_t_tags(s_tags, book_title_for_tag, book_title_map)
            
            # c tag (chapter) - try to find chapter from parent path if available
            # Look for a title that contains "chapter" in the path (excluding the last one which is the section)
            if len(titles) > 1:
                for i in range(len(titles) - 1):
                    chapter_title = titles[i]
                    if "chapter" in chapter_title.lower():
                        # Extract chapter number from title
                        chapter_match = re.search(r'chapter\s+(\d+)', chapter_title, re.IGNORECASE)
                        if chapter_match:
                            chapter_num = chapter_match.group(1)
                            c_tag_value = normalize_nkbip08_tag_value(chapter_num)
                        else:
                            # Use normalized title as chapter identifier
                            c_tag_value = normalize_nkbip08_tag_value(chapter_title)
                        if c_tag_value:
                            s_tags.append(["c", c_tag_value])
                        break  # Use first chapter found
            
            # s tag (section) - from section title
            s_tag_value = normalize_nkbip08_tag_value(verse_title)
            if s_tag_value:
                s_tags.append(["s", s_tag_value])
            
            # v tag (version) - add to ALL events when version is specified
            if metadata and hasattr(metadata, "version") and metadata.version:
                v_tag_value = normalize_nkbip08_tag_value(metadata.version)
                if v_tag_value:
                    s_tags.append(["v", v_tag_value])
            
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
        
        # Add type tag (formatting hint for clients, default to "book")
        pub_type = metadata.type if metadata and hasattr(metadata, "type") and metadata.type else "book"
        s_tags.append(["type", pub_type])
        
        # Add image and summary to ALL events (unless overridden at chapter/section level)
        # TODO: Support chapter/section-level overrides in the future
        if metadata:
            if hasattr(metadata, "image") and metadata.image:
                s_tags.append(["image", metadata.image])
            if hasattr(metadata, "summary") and metadata.summary:
                s_tags.append(["summary", metadata.summary])
        
        # Add NKBIP-08 tags for book wikilinks (for verse content events - hierarchical: C, T, c, s)
        # C tag (collection) - add to ALL events if collection_id is defined
        if collection_id:
            c_tag_value = normalize_nkbip08_tag_value(collection_id)
            if c_tag_value:
                s_tags.append(["C", c_tag_value])
        
        # T tag (title/book) - from book title
        if book_idx >= 0 and book_idx < len(titles):
            book_title = titles[book_idx]
            # Add all three T tags (display, canonical-long, canonical-short)
            _add_book_t_tags(s_tags, book_title, book_title_map)
        
        # c tag (chapter) - from chapter
        if chapter_idx >= 0 and chapter_idx < len(titles):
            chapter_title = titles[chapter_idx]
            # Extract chapter number from title
            chapter_match = re.search(r'chapter\s+(\d+)', chapter_title, re.IGNORECASE)
            if chapter_match:
                chapter_num = chapter_match.group(1)
                c_tag_value = normalize_nkbip08_tag_value(chapter_num)
            else:
                # Use normalized title as chapter identifier
                c_tag_value = normalize_nkbip08_tag_value(chapter_title)
            if c_tag_value:
                s_tags.append(["c", c_tag_value])
        
        # s tag (section/verse) - from verse number or title
        # Extract verse number from verse title (e.g., "1:1" -> "1", "2:4" -> "4")
        verse_match = re.match(r'^(\d+):(\d+)$', verse_title.strip())
        if verse_match:
            verse_num = verse_match.group(2)  # Just the verse number
            s_tag_value = normalize_nkbip08_tag_value(verse_num)
        else:
            # Use normalized title as section identifier
            s_tag_value = normalize_nkbip08_tag_value(verse_title)
        if s_tag_value:
            s_tags.append(["s", s_tag_value])
        
        # v tag (version) - add to ALL events when version is specified
        if metadata and hasattr(metadata, "version") and metadata.version:
            v_tag_value = normalize_nkbip08_tag_value(metadata.version)
            if v_tag_value:
                s_tags.append(["v", v_tag_value])
        
        # Note: "name" tag removed - using NKBIP-08 T tag instead
        
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
    # Per NKBIP-08: T-level events (book/title) SHOULD only contain other 30040 events (chapters)
    # c-level events (chapter) SHOULD contain at least one 30041 event and MAY contain 30040 events (subchapters)
    # Use placeholder pubkey "0000000000000000000000000000000000000000000000000000000000000000"
    # This will be replaced with the actual pubkey during publishing
    PLACEHOLDER_PUBKEY = "0000000000000000000000000000000000000000000000000000000000000000"
    
    # Track which T-level events need a Preamble chapter
    book_d_to_preamble_d: Dict[str, str] = {}  # Maps book d-tag to preamble chapter d-tag
    
    # First pass: identify T-level events with direct 30041 children and create Preamble chapters
    for event in events:
        if event.kind == 30040:
            d_tag = None
            for tag in event.tags:
                if tag and len(tag) > 0 and tag[0] == "d":
                    d_tag = tag[1] if len(tag) > 1 else None
                    break
            
            if d_tag and d_tag in parent_d_to_children:
                event_type = d_tag_to_event_type.get(d_tag, "unknown")
                
                # Check if this T-level event has direct 30041 children
                if event_type == "book":
                    direct_30041_children = [
                        (child_kind, child_d) 
                        for child_kind, child_d in parent_d_to_children[d_tag]
                        if child_kind == 30041
                    ]
                    
                    if direct_30041_children:
                        # Create a Preamble chapter for this book
                        # Preamble d-tag: book_d_tag + "-preamble"
                        preamble_d = f"{d_tag}-preamble"
                        book_d_to_preamble_d[d_tag] = preamble_d
                        
                        # Create the Preamble chapter event (30040)
                        preamble_pub_type = metadata.type if metadata and hasattr(metadata, "type") and metadata.type else "book"
                        preamble_tags = [
                            ["d", preamble_d],
                            ["title", "Preamble"],
                            ["L", language],
                            ["m", "text/asciidoc"],
                            ["type", preamble_pub_type],
                            ["auto-update", "ask"],
                        ]
                        
                        # Add NKBIP-08 tags for Preamble chapter
                        # C tag (collection) - if collection_id is defined
                        if collection_id:
                            c_tag_value = normalize_nkbip08_tag_value(collection_id)
                            if c_tag_value:
                                preamble_tags.append(["C", c_tag_value])
                        
                        # T tag (title) - inherit from parent book
                        # Find the book title from the book event's T tag
                        book_t_tag = None
                        for tag in event.tags:
                            if tag and len(tag) > 0 and tag[0] == "T":
                                book_t_tag = tag[1] if len(tag) > 1 else None
                                break
                        if book_t_tag:
                            preamble_tags.append(["T", book_t_tag])
                        
                        # c tag (chapter) - "preamble"
                        preamble_tags.append(["c", "preamble"])
                        
                        # v tag (version) - if version is specified
                        if metadata and hasattr(metadata, "version") and metadata.version:
                            v_tag_value = normalize_nkbip08_tag_value(metadata.version)
                            if v_tag_value:
                                preamble_tags.append(["v", v_tag_value])
                        
                        # Track parent relationship
                        d_tag_to_parent_d[preamble_d] = d_tag
                        d_tag_to_event_type[preamble_d] = "chapter"
                        
                        # Create and add the Preamble event
                        preamble_event = Event(kind=30040, tags=preamble_tags, content="")
                        events.append(preamble_event)
                        
                        # Update parent references for the 30041 children to point to Preamble
                        for child_kind, child_d in direct_30041_children:
                            # Find the child event and update its parent reference
                            for child_event in events:
                                child_d_tag = None
                                for tag in child_event.tags:
                                    if tag and len(tag) > 0 and tag[0] == "d":
                                        child_d_tag = tag[1] if len(tag) > 1 else None
                                        break
                                
                                if child_d_tag == child_d:
                                    # Update _parent_d tag to point to Preamble
                                    for i, tag in enumerate(child_event.tags):
                                        if tag and len(tag) > 0 and tag[0] == "_parent_d":
                                            child_event.tags[i] = ["_parent_d", preamble_d]
                                            break
                                    else:
                                        # Add _parent_d tag if not present
                                        child_event.tags.append(["_parent_d", preamble_d])
                                    
                                    # Update d_tag_to_parent_d mapping
                                    d_tag_to_parent_d[child_d] = preamble_d
                                    
                                    # Update parent_d_to_children mapping
                                    # Remove from book's children
                                    if d_tag in parent_d_to_children:
                                        parent_d_to_children[d_tag] = [
                                            (k, d) for k, d in parent_d_to_children[d_tag]
                                            if not (k == child_kind and d == child_d)
                                        ]
                                    
                                    # Add to Preamble's children
                                    if preamble_d not in parent_d_to_children:
                                        parent_d_to_children[preamble_d] = []
                                    parent_d_to_children[preamble_d].append((child_kind, child_d))
                                    break
    
    # Second pass: add a-tags to all 30040 events
    for event in events:
        if event.kind == 30040:
            d_tag = None
            for tag in event.tags:
                if tag and len(tag) > 0 and tag[0] == "d":
                    d_tag = tag[1] if len(tag) > 1 else None
                    break
            
            # Add a-tags for children of this index event
            # Format per NKBIP-01: ["a", "<kind:pubkey:dtag>", "<relay hint>", "<event id>"]
            # Relay hint and event id are optional, but we support the format
            if d_tag and d_tag in parent_d_to_children:
                event_type = d_tag_to_event_type.get(d_tag, "unknown")
                
                for child_kind, child_d in parent_d_to_children[d_tag]:
                    # Per NKBIP-08: T-level events (book/title) should ONLY contain c-level events (30040)
                    # If this is a book with direct 30041 children, they should now be under Preamble
                    if event_type == "book" and child_kind == 30041:
                        # This shouldn't happen after Preamble creation, but skip just in case
                        continue
                    
                    # Format: ["a", "<kind>:<pubkey>:<d-tag>", "<relay hint>", "<event id>"]
                    # Relay hint and event id are optional - we'll use empty strings as placeholders
                    # The actual event IDs will be filled in after events are published
                    a_tag = ["a", f"{child_kind}:{PLACEHOLDER_PUBKEY}:{child_d}", "", ""]
                    event.tags.append(a_tag)
            
            # If this is a book that has a Preamble, add the Preamble to its a-tags
            if d_tag in book_d_to_preamble_d:
                preamble_d = book_d_to_preamble_d[d_tag]
                a_tag = ["a", f"30040:{PLACEHOLDER_PUBKEY}:{preamble_d}", "", ""]
                event.tags.append(a_tag)

    return events


