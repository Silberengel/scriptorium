"""
Generate command handler - converts source to normalized AsciiDoc and events.
"""
import json
import sys
from pathlib import Path

from ..adapters.html_to_adoc import html_to_adoc
from ..config import load_config
from ..io_layout import Layout
from ..metadata import load_metadata, load_title_mapping
from ..nkbip_bookstr import serialize_bookstr
from ..parse_collection import parse_adoc_structure
from ..text import (
    ensure_blank_before_attributes,
    ensure_blank_before_headings,
    ensure_blank_between_paragraphs,
    normalize_ambiguous_unicode,
    normalize_headings,
    remove_discrete_attributes,
    strip_invisible_text,
    to_ascii_text,
    unwrap_hard_wraps,
)
from ..text_structure import promote_headings


def cmd_generate(args) -> int:
    """Generate normalized AsciiDoc and events from source."""
    cfg = load_config(source_type=args.source_type)
    layout = Layout(cfg.out_dir)
    layout.ensure()
    src = Path(args.input)
    if not src.exists():
        print(f"Input not found: {src}", file=sys.stderr)
        return 1
    if cfg.source_type == "HTML":
        adoc = html_to_adoc(src.read_bytes())
    elif cfg.source_type == "ADOC":
        adoc = src.read_text(encoding="utf-8").lstrip()
    else:
        print(f"Unsupported source type for generate: {cfg.source_type}", file=sys.stderr)
        return 2
    # Promote structural headings if patterns provided or preset requested
    if getattr(args, "promote_default_structure", False) or getattr(args, "chapter_pattern", None) or getattr(args, "section_pattern", None) or getattr(args, "verse_pattern", None):
        # Allow titles starting with a digit (e.g., "4 Kings Chapter 1") as well as letters
        chapter_pat = args.chapter_pattern if getattr(args, "chapter_pattern", None) else r"^[A-Za-z0-9][^\n]*\sChapter\s+\d+\.?$"
        # prefer verse_pattern, fallback to legacy section_pattern, then default (allow trailing period optional)
        verse_pat = (
            args.verse_pattern
            if getattr(args, "verse_pattern", None)
            else (args.section_pattern if getattr(args, "section_pattern", None) else r"^\d+:\d+\.?$")
        )
        # If using default structure promotion and user didn't explicitly choose levels,
        # use chapter=3, verse=4 to match pattern document.
        chapter_level = getattr(args, "chapter_level", 3 if getattr(args, "promote_default_structure", False) else 4)
        verse_level = getattr(args, "verse_level", 4 if getattr(args, "promote_default_structure", False) else 5)
        adoc = promote_headings(
            adoc,
            chapter_regex=chapter_pat,
            verse_regex=verse_pat,
            chapter_level=chapter_level,
            verse_level=verse_level,
            insert_preamble=not getattr(args, "no_preamble", False),
        )
    # Normalize ambiguous unicode characters (always, before other processing)
    adoc = normalize_ambiguous_unicode(adoc)
    # Normalize heading format to ensure valid AsciiDoc
    adoc = normalize_headings(adoc)
    # Additional sanitation options
    if hasattr(args, "ascii_only") and args.ascii_only:
        adoc = to_ascii_text(adoc)
    else:
        adoc = strip_invisible_text(adoc)
    if hasattr(args, "unwrap_lines") and args.unwrap_lines:
        adoc = unwrap_hard_wraps(adoc, min_level=getattr(args, "unwrap_level", 4))
    # Remove [discrete] blocks entirely
    adoc = remove_discrete_attributes(adoc)
    # Final formatting: ensure blank before attribute blocks, then headings (noop if none)
    adoc = ensure_blank_before_attributes(adoc)
    adoc = ensure_blank_before_headings(adoc)
    # Enforce paragraph separation at the very end
    adoc = ensure_blank_between_paragraphs(adoc)
    # store a single normalized AsciiDoc as proof of pipeline
    out_file = layout.adoc_dir / "normalized-publication.adoc"
    out_file.write_text(adoc, encoding="utf-8")
    print(f"Generated AsciiDoc: {out_file}")
    # Load metadata if present
    base_dir = Path(args.input).parent
    md = load_metadata(base_dir)
    has_collection = bool(args.has_collection) if hasattr(args, "has_collection") and args.has_collection else (md.has_collection if md else True)
    language = (md.language if md and md.language else "en")
    collection_id = md.collection_id if md and md.collection_id else base_dir.name
    # Parse collection structure
    tree = parse_adoc_structure(adoc, has_collection=has_collection)
    # Serialize bookstr events
    title_map = load_title_mapping(base_dir, md)
    use_bookstr = md.use_bookstr if md else True
    events = serialize_bookstr(
        tree,
        collection_id=collection_id,
        language=language,
        use_bookstr=use_bookstr,
        book_title_map=title_map,
        metadata=md,
    )
    # Write events to NDJSON
    events_path = layout.events_dir / "events.ndjson"
    
    # Count event types for reporting
    index_count = sum(1 for e in events if e.kind == 30040)
    content_count = sum(1 for e in events if e.kind == 30041)
    
    # Check for duplicate d-tags
    d_tags_seen = {}
    duplicate_d_tags = []
    for idx, e in enumerate(events):
        d_tag = None
        for tag in e.tags:
            if tag and tag[0] == "d":
                d_tag = tag[1]
                break
        if d_tag:
            if d_tag in d_tags_seen:
                duplicate_d_tags.append((d_tag, d_tags_seen[d_tag], idx))
            else:
                d_tags_seen[d_tag] = idx
    
    if duplicate_d_tags:
        print(f"⚠ WARNING: Found {len(duplicate_d_tags)} duplicate d-tags:")
        for d_tag, first_idx, dup_idx in duplicate_d_tags[:10]:
            print(f"  d-tag '{d_tag}' appears at events {first_idx} and {dup_idx}")
        if len(duplicate_d_tags) > 10:
            print(f"  ... and {len(duplicate_d_tags) - 10} more duplicates")
        print(f"  This should not happen - events may be overwritten on relay!")
    else:
        print(f"✓ No duplicate d-tags found ({len(d_tags_seen)} unique d-tags)")
    
    with events_path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(e.to_json())
            f.write("\n")
    print(f"Wrote events: {events_path}")
    print(f"  Total events: {len(events)} ({index_count} index, {content_count} content)")
    # Write simple cache index for determinism/resume
    idx_path = layout.cache_dir / "event_index.json"
    d_list = []
    for e in events:
        d = None
        for tag in e.tags:
            if tag and tag[0] == "d":
                d = tag[1]
                break
        if d:
            d_list.append(d)
    with idx_path.open("w", encoding="utf-8") as f:
        json.dump({"count": len(d_list), "d": d_list}, f, ensure_ascii=False, indent=2)
    print(f"Wrote cache index: {idx_path}")
    return 0

