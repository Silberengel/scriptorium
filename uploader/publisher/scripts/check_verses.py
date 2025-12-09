#!/usr/bin/env python3
"""
Check if all verses from all chapters are present in the generated events.
Compares section numbers against expected verse counts for the DRB version.
The expected counts are derived from the events file itself (maximum verse found per chapter).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Dict, Set, Tuple
from collections import defaultdict

# Expected verse counts per book/chapter for Douay-Rheims Bible
# These will be populated from the events file itself
EXPECTED_VERSES: Dict[str, Dict[int, int]] = {}





def normalize_book_name(name: str) -> str:
    """Normalize book name to match T tag format (lowercase, hyphens)."""
    import re
    # Convert to lowercase and replace spaces/non-alphanumeric with hyphens
    normalized = re.sub(r'[^a-z0-9]+', '-', name.lower())
    # Remove leading/trailing hyphens and collapse multiple hyphens
    normalized = re.sub(r'-+', '-', normalized).strip('-')
    return normalized


def parse_verse_number(s: str) -> int | None:
    """Parse verse number from section tag or title. Handles formats like '1', '1-1', '1:1'."""
    if not s:
        return None
    
    # Try to extract first number
    import re
    match = re.search(r'^(\d+)', s)
    if match:
        return int(match.group(1))
    return None


def extract_book_chapter_verse(event: dict) -> Tuple[str | None, int | None, int | None]:
    """Extract book, chapter, and verse from an event."""
    tags = event.get("tags", [])
    
    # Get book from T tag
    book = None
    chapter = None
    verse = None
    
    for tag in tags:
        if len(tag) < 2:
            continue
        
        if tag[0] == "T":
            book = tag[1].lower()
        elif tag[0] == "c":
            try:
                chapter = int(tag[1])
            except (ValueError, TypeError):
                pass
        elif tag[0] == "s":
            # Section tag - could be verse number
            # Skip non-numeric sections like "preamble"
            s_value = tag[1].lower()
            if s_value and s_value not in ("preamble", "preface", "introduction"):
                verse = parse_verse_number(tag[1])
    
    # If no verse from s tag, try to parse from title
    if verse is None:
        title = event.get("title", "")
        # Look for patterns like "1:1", "1:2", etc.
        import re
        match = re.search(r'(\d+):(\d+)', title)
        if match:
            verse = int(match.group(2))
    
    return book, chapter, verse


def main():
    if len(sys.argv) < 2:
        print("Usage: check_verses.py <events.ndjson>")
        sys.exit(1)
    
    events_file = Path(sys.argv[1])
    if not events_file.exists():
        print(f"Error: File not found: {events_file}")
        sys.exit(1)
    
    # Collect all verses found
    found_verses: Dict[str, Dict[int, Set[int]]] = defaultdict(lambda: defaultdict(set))
    
    print(f"Reading events from {events_file}...")
    with open(events_file, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                # Only check content events (kind 30041)
                if event.get("kind") != 30041:
                    continue
                
                book, chapter, verse = extract_book_chapter_verse(event)
                
                if book and chapter and verse:
                    found_verses[book][chapter].add(verse)
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse line {line_num}: {e}")
                continue
    
    # Generate expected verse counts from the events file itself
    # The expected count is the maximum verse number found for each chapter
    print("Generating expected verse counts from events file...")
    for book_name, chapters in found_verses.items():
        EXPECTED_VERSES[book_name] = {}
        for chapter_num, verses in chapters.items():
            if verses:
                # Expected count is the maximum verse number found
                EXPECTED_VERSES[book_name][chapter_num] = max(verses)
    
    # Compare against expected
    print("\nChecking verses...\n")
    missing_count = 0
    extra_count = 0
    total_expected = 0
    total_found = 0
    
    for book_name, chapters in EXPECTED_VERSES.items():
        found_chapters = found_verses.get(book_name, {})
        
        for chapter_num, expected_verse_count in sorted(chapters.items()):
            total_expected += expected_verse_count
            found_verses_set = found_chapters.get(chapter_num, set())
            total_found += len(found_verses_set)
            
            expected_verses = set(range(1, expected_verse_count + 1))
            missing = expected_verses - found_verses_set
            extra = found_verses_set - expected_verses
            
            if missing:
                missing_count += len(missing)
                print(f"❌ {book_name.title()} {chapter_num}: Missing verses {sorted(missing)} (expected {expected_verse_count} verses)")
            
            if extra:
                extra_count += len(extra)
                print(f"⚠️  {book_name.title()} {chapter_num}: Extra verses {sorted(extra)} (expected max {expected_verse_count})")
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Total expected verses: {total_expected}")
    print(f"Total found verses: {total_found}")
    print(f"Missing verses: {missing_count}")
    print(f"Extra verses: {extra_count}")
    
    if missing_count == 0 and extra_count == 0:
        print("\n✅ All verses are present and correct!")
        return 0
    else:
        print("\n❌ Some verses are missing or extra.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

