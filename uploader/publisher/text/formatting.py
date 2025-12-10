"""
AsciiDoc formatting functions for ensuring proper structure and spacing.
"""
import re


def unwrap_hard_wraps(text: str, *, min_level: int = 4) -> str:
    """
    Merge hard-wrapped lines within paragraphs into single lines,
    but only inside level-4 verses (==== heading) and deeper.
    Rules:
      - Track current heading level based on leading '='
      - Only unwrap when current_level >= 4 (verse content)
      - Always preserve blank lines (paragraph separators)
      - Always preserve structural lines:
          headings, attribute lines (:name:), list items, block fences
      - Within an unwrap-eligible paragraph block, join lines with a single space
    """
    if not text:
        return text
    out_lines = []
    buffer = []
    current_level = 0

    def is_structural(line: str) -> bool:
        l = line.lstrip()
        if not l:
            return True
        # headings
        if l.startswith("="):
            return True
        # attributes
        if l.startswith(":"):
            return True
        # lists / numbered
        if l.startswith(("* ", "- ", ". ")):
            return True
        if re.match(r"^\d+\.\s", l):
            return True
        # block delimiters
        if l.startswith(("----", "====", "****", "____", "++++", "|===")):
            return True
        return False

    def flush_buffer():
        nonlocal buffer
        if buffer:
            joined = " ".join(s.strip() for s in buffer if s is not None)
            out_lines.append(joined)
            buffer = []

    heading_re = re.compile(r"^(=+)\s")

    for line in text.splitlines():
        # Track heading level
        m = heading_re.match(line.lstrip())
        if m:
            flush_buffer()
            current_level = len(m.group(1))
            out_lines.append(line)
            continue

        if not line.strip():  # blank line → paragraph break
            flush_buffer()
            out_lines.append("")
            continue
        if is_structural(line):
            flush_buffer()
            out_lines.append(line)
            continue
        # accumulate paragraph line only if inside verse (level >= 4)
        if current_level >= min_level:
            buffer.append(line)
        else:
            flush_buffer()
            out_lines.append(line)

    flush_buffer()
    return "\n".join(out_lines) + "\n"


def ensure_blank_before_headings(text: str) -> str:
    """
    Ensure there's exactly one blank line before any heading line (=, ==, etc.)
    to keep AsciiDoc valid and readable.
    Note: Do NOT insert a blank if the previous line is an attribute block like [discrete].
    """
    if not text:
        return text
    out = []
    for line in text.splitlines():
        is_heading = line.lstrip().startswith("=")
        if is_heading and out:
            prev = out[-1]
            prev_stripped = prev.strip()
            is_attribute_block = prev_stripped.startswith("[") and prev_stripped.endswith("]")
            # Treat the special paragraph-break token as an existing blank
            is_para_break_token = (prev_stripped == "<<PARA>>")
            if prev_stripped != "" and not is_attribute_block and not is_para_break_token:
                out.append("")  # insert blank line before heading unless preceded by attribute block
        out.append(line)
    return "\n".join(out) + "\n"


def ensure_blank_before_attributes(text: str) -> str:
    """
    Ensure there's a blank line before attribute blocks like [discrete],
    unless it's already at the start of the file or preceded by a blank.
    """
    if not text:
        return text
    out = []
    for line in text.splitlines():
        is_attr = False
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            is_attr = True
        if is_attr and out and out[-1].strip() != "":
            out.append("")
        out.append(line)
    return "\n".join(out) + "\n"


def remove_discrete_attributes(text: str) -> str:
    """
    Remove AsciiDoc [discrete] attribute lines entirely.
    """
    if not text:
        return text
    out = []
    for line in text.splitlines():
        if line.strip().lower() == "[discrete]":
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def ensure_blank_between_paragraphs(text: str) -> str:
    """
    Ensure there's exactly one blank line between adjacent plain paragraph lines
    (non-structural, non-heading, non-list, non-attribute).
    """
    if not text:
        return text
    out: list[str] = []
    INPARA_SENTINEL = "<<INP>>"
    PARA_BREAK = "<<PARA>>"
    for line in text.splitlines():
        # Treat any occurrence (even with surrounding whitespace) of the token as a paragraph break
        if line.strip() == PARA_BREAK or PARA_BREAK in line:
            # emit a blank line unconditionally for explicit paragraph breaks
            if out and out[-1] != "":
                out.append("")
            elif not out:
                out.append("")
            # keep a single blank; skip further processing for this line
            continue
        if out:
            prev = out[-1]
            if prev.strip() != "" and line.strip() != "":
                # Do not separate lines that are marked as in-paragraph (came from <br>)
                if prev.lstrip().startswith(INPARA_SENTINEL) or line.lstrip().startswith(INPARA_SENTINEL):
                    pass
                else:
                    prev_is_structural = (
                        prev.lstrip().startswith(("=", "* ", "- ", ". "))
                        or re.match(r"^\d+\.\s", prev.lstrip()) is not None
                        or (prev.strip().startswith("[") and prev.strip().endswith("]"))
                    )
                    curr_is_structural = (
                        line.lstrip().startswith(("=", "* ", "- ", ". "))
                        or re.match(r"^\d+\.\s", line.lstrip()) is not None
                        or (line.strip().startswith("[") and line.strip().endswith("]"))
                    )
                    if not prev_is_structural and not curr_is_structural:
                        out.append("")
        out.append(line)
    # Strip sentinel markers
    cleaned = [l.replace(INPARA_SENTINEL, "") for l in out if l != PARA_BREAK]
    return "\n".join(cleaned) + "\n"

