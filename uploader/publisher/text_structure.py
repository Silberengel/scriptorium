from __future__ import annotations
import re
from typing import Optional


def promote_headings(
    adoc_text: str,
    *,
    chapter_regex: Optional[str] = None,
    section_regex: Optional[str] = None,
    chapter_level: int = 4,
    section_level: int = 5,
    insert_preamble: bool = True,
) -> str:
    """
    Promote plain-text lines that look like structural markers into AsciiDoc headings.
    - chapter_regex: lines matching this become heading at level chapter_level
    - verse_regex: lines matching this become heading at level verse_level
    - insert_preamble: after a chapter heading, if there is body text before the first verse heading,
      insert a 'Preamble' heading at verse_level.
    This is generic; supply patterns via CLI/metadata to adapt to different corpora.
    """
    if not adoc_text:
        return adoc_text

    chapter_re = re.compile(chapter_regex) if chapter_regex else None
    # Build two regexes for section detection:
    # - section_re_line: anchored (original) for full-line matches to become headings
    # - section_re_any: unanchored variant for splitting inline occurrences out to their own line
    section_re_line = re.compile(section_regex) if section_regex else None
    section_re_any = None
    if section_regex:
        pat_any = section_regex
        if pat_any.startswith("^"):
            pat_any = pat_any[1:]
        if pat_any.endswith("$"):
            pat_any = pat_any[:-1]
        section_re_any = re.compile(pat_any)

    lines = adoc_text.splitlines()
    # Split inline section markers into standalone heading lines where possible
    if section_re_any:
        split_lines = []
        for line in lines:
            work = line
            progressed = True
            while progressed:
                progressed = False
                m = section_re_any.search(work)
                if not m:
                    break
                # Only treat as a section marker if it appears at the start of the line
                # (to avoid accidentally splitting numbers like years or references in the middle).
                if m.start() != 0:
                    break
                pre = work[: m.start()].rstrip()
                marker = work[m.start() : m.end()].strip()
                # Normalize marker like 'N:N.' → 'N:N' for heading text
                marker = re.sub(r"\.$$", "", marker)
                post = work[m.end() :].lstrip()
                if pre:
                    split_lines.append(pre)
                split_lines.append(marker)  # will be converted to heading below
                work = post
                progressed = True
            if work:
                split_lines.append(work)
        lines = split_lines
    out = []

    # Helper to build heading prefix
    def h(level: int) -> str:
        return "=" * max(1, level)

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Keep existing headings as-is
        if stripped.startswith("="):
            out.append(line)
            out.append("")  # ensure blank after any heading
            i += 1
            continue

        # Chapter detection
        if chapter_re and chapter_re.match(stripped):
            out.append(f"{h(chapter_level)} {stripped}")
            out.append("")
            i += 1
            # Optionally add Preamble if immediate following text before next section
            if insert_preamble and section_re_line:
                # Look ahead: if next non-empty non-heading non-section is text, inject preamble
                j = i
                saw_text = False
                while j < len(lines):
                    nxt = lines[j].strip()
                    if not nxt:
                        j += 1
                        continue
                    if nxt.startswith("="):
                        break
                    if section_re_line.match(nxt):
                        break
                    saw_text = True
                    break
                if saw_text:
                    out.append(f"{h(section_level)} Preamble")
                    out.append("")
            continue

        # Section detection
        if section_re_line and section_re_line.match(stripped):
            # Normalize 'N:N.' → 'N:N' for heading text
            heading_text = re.sub(r"\.$$", "", stripped)
            out.append(f"{h(section_level)} {heading_text}")
            out.append("")
            i += 1
            continue

        # Default: pass-through
        out.append(line)
        i += 1

    return "\n".join(out) + "\n"


