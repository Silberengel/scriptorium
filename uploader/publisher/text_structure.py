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
    section_re = re.compile(section_regex) if section_regex else None

    lines = adoc_text.splitlines()
    # Split inline section markers into standalone heading lines where possible
    if section_re:
        split_lines = []
        for line in lines:
            work = line
            progressed = True
            while progressed:
                progressed = False
                m = section_re.search(work)
                if not m:
                    break
                pre = work[: m.start()].rstrip()
                marker = work[m.start() : m.end()].strip()
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
            if insert_preamble and section_re:
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
                    if section_re.match(nxt):
                        break
                    saw_text = True
                    break
                if saw_text:
                    out.append(f"{h(section_level)} Preamble")
                    out.append("")
            continue

        # Section detection
        if section_re and section_re.match(stripped):
            out.append(f"{h(section_level)} {stripped}")
            out.append("")
            i += 1
            continue

        # Default: pass-through
        out.append(line)
        i += 1

    return "\n".join(out) + "\n"


