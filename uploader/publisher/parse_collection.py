from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import re


HEADING_RE = re.compile(r"^(=+)\s+(.*)$")


@dataclass
class SectionEntry:
    # Titles from top heading down to the verse leaf (inclusive of ancestors)
    path_titles: List[str]
    # Heading levels corresponding to path_titles (same length)
    path_levels: List[int]
    # The leaf verse content
    content: str


@dataclass
class CollectionTree:
    # All verse entries discovered
    sections: List[SectionEntry]
    # The heading level used for verses (leaf level)
    section_level: int


def parse_adoc_structure(
    adoc_text: str,
    *,
    has_collection: bool = True,  # retained for compatibility, not strictly required now
    collection_title: Optional[str] = None,  # unused in generic parser
    has_verses: bool = True,  # If False, treat all content as sections (no verses)
) -> CollectionTree:
    """
    Generic AsciiDoc heading parser:
      - Tracks a stack of headings by level (e.g., =, ==, ===, ====, ...)
      - Accumulates content lines under the current heading
      - Determines the deepest heading level that contains content and treats that as 'section_level' (verse level)
      - Produces SectionEntry for each verse leaf at section_level with full path of ancestor titles
    """
    lines = adoc_text.splitlines()

    # Stack of (level, title, content_lines)
    stack: List[Tuple[int, str, List[str]]] = []
    # Collected nodes: list of tuples for later pass
    nodes: List[Tuple[List[Tuple[int, str]], List[str]]] = []

    def start_heading(level: int, title: str):
        nonlocal stack
        # Pop until we are below the new level
        while stack and stack[-1][0] >= level:
            lvl, ttl, buf = stack.pop()
            # Save node snapshot (path, content) for later analysis
            nodes.append(([(lv, tt) for lv, tt, _ in stack] + [(lvl, ttl)], buf))
        # Push new heading
        stack.append((level, title, []))

    def append_line(line: str):
        if stack:
            stack[-1][2].append(line)

    for ln in lines:
        m = HEADING_RE.match(ln)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip() or "Preamble"
            start_heading(level, title)
        else:
            append_line(ln)

    # Close remaining headings
    while stack:
        lvl, ttl, buf = stack.pop()
        nodes.append(([(lv, tt) for lv, tt, _ in stack] + [(lvl, ttl)], buf))

    # Determine verse level: deepest level that has any non-empty content (after strip)
    # If has_verses is False, set section_level to a very high number so all content is treated as sections
    if not has_verses:
        section_level = 999  # High number so no level matches it
    else:
        contentful_levels: List[int] = []
        for path, buf in nodes:
            content = "\n".join(buf).strip()
            if content:
                contentful_levels.append(path[-1][0])
        section_level = max(contentful_levels) if contentful_levels else 4
    
    # Debug: count sections by level
    level_counts: Dict[int, int] = {}
    for path, buf in nodes:
        if buf:
            content = "\n".join(buf).strip()
            if content:
                level = path[-1][0]
                level_counts[level] = level_counts.get(level, 0) + 1

    # Build SectionEntry list for verse nodes at section_level with non-empty content
    # Also capture content at all other levels that aren't at section_level - these become "-section" events
    sections: List[SectionEntry] = []
    for path, buf in nodes:
        if not buf:
            continue
        level = path[-1][0]
        content = "\n".join(buf).strip()
        if not content:
            continue
        
        # Include content at section_level (verses) - these are the main content
        if level == section_level:
            # Standard verse content
            path_titles = [t for _, t in path]
            path_levels = [lv for lv, _ in path]
            sections.append(SectionEntry(path_titles=path_titles, path_levels=path_levels, content=content))
        else:
            # Content at any other level - treat as a section
            # This captures introduction sections, preambles, and any other content not at verse level
            path_titles = [t for _, t in path]
            path_levels = [lv for lv, _ in path]
            sections.append(SectionEntry(path_titles=path_titles, path_levels=path_levels, content=content))

    # Debug output
    if level_counts:
        print(f"  Content by level: {dict(sorted(level_counts.items()))}")
        print(f"  Verse level (section_level): {section_level}")
        verse_count = level_counts.get(section_level, 0)
        section_count = sum(count for level, count in level_counts.items() if level != section_level)
        print(f"  Verses (level {section_level}): {verse_count}, Sections (other levels): {section_count}")

    return CollectionTree(sections=sections, section_level=section_level)


