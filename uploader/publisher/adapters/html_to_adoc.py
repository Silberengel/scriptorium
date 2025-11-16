from bs4 import BeautifulSoup, NavigableString
import re
from ..util import strip_invisible_text

INVISIBLE_CHARS = [
    "\u200b",  # zero width space
    "\u200c",  # zero width non-joiner
    "\u200d",  # zero width joiner
    "\ufeff",  # BOM
]


def _strip_invisible(text: str) -> str:
    # Backward compatibility: keep explicit removal list, then broad clean
    for ch in INVISIBLE_CHARS:
        text = text.replace(ch, "")
    return strip_invisible_text(text)


def html_to_adoc(html_bytes: bytes, *, language: str = "en") -> str:
    """
    Minimal HTML → AsciiDoc normalization:
    - remove invisible chars
    - map basic headings and paragraphs
    - preserve italics/strong as AsciiDoc
    """
    soup = BeautifulSoup(html_bytes, "lxml")

    # Remove scripts/styles
    for bad in soup(["script", "style"]):
        bad.decompose()

    # Paragraph normalization rules:
    # - <p> blocks must be surrounded by exactly one blank line above and below
    # - <br> tags inside <p> become hard newlines
    # - all other newlines/soft wraps inside <p> collapse to a single space
    BR_TOKEN = "<<BR>>"
    INPARA_SENTINEL = "<<INP>>"
    PARA_BREAK = "<<PARA>>"

    def normalize_paragraph_text(block_el) -> str:
        # Work on a local clone of the block HTML to avoid mutating the main soup
        local = BeautifulSoup(str(block_el), "lxml")
        target = local.find(block_el.name)
        if target is None:
            return ""
        for br in target.find_all("br"):
            br.replace_with(NavigableString(BR_TOKEN))

        raw = target.get_text(" ", strip=True)
        raw = _strip_invisible(raw)

        # Preserve BRs as in-paragraph newlines while collapsing other whitespace
        raw = raw.replace(BR_TOKEN, "<<<BR_NL>>>")
        raw = re.sub(r"\s+", " ", raw).strip()
        raw = raw.replace("<<<BR_NL>>>", "\n")
        return raw

    def normalize_pre_text(pre_el) -> str:
        # Preserve verbatim whitespace and newlines inside preformatted blocks
        local = BeautifulSoup(str(pre_el), "lxml")
        target = local.find(pre_el.name)
        if target is None:
            return ""
        # If <br> exists inside <pre>, treat it as a real newline
        for br in target.find_all("br"):
            br.replace_with(NavigableString("\n"))
        raw = target.get_text("", strip=False)
        raw = _strip_invisible(raw)
        # Normalize line endings
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")
        # Trim only leading/trailing blank lines, keep internal spacing
        lines_pre = raw.split("\n")
        # remove leading empty lines
        while lines_pre and lines_pre[0].strip() == "":
            lines_pre.pop(0)
        # remove trailing empty lines
        while lines_pre and lines_pre[-1].strip() == "":
            lines_pre.pop()
        return "\n".join(lines_pre)

    doc_title = None
    saw_first_post_title_heading = False
    saw_first_h2_after_title = False
    lines = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "blockquote", "pre", "ol", "ul", "li", "em", "strong"]):
        name = el.name.lower()
        # Use space separator to avoid introducing artificial newlines from inline boundaries
        # BR tokens (inserted earlier) will be expanded later inside normalize_paragraph_text
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if name == "h1":
            lines.append(f"= {text}")
            lines.append("")
        elif name == "h2":
            lines.append(f"== {text}")
            lines.append("")
        elif name == "h3":
            lines.append(f"=== {text}")
            lines.append("")
        elif name == "h4":
            lines.append(f"==== {text}")
            lines.append("")
        elif name in ("p", "blockquote", "pre"):
            # Skip Gutenberg 'Title :' line if present; header will carry :title:
            # Handle cases where HTML splits 'Title' and ':' across a line break
            collapsed = " ".join(text.split())
            if re.match(r"^title\s*:", collapsed, flags=re.IGNORECASE):
                continue
            if name == "p":
                norm = normalize_paragraph_text(el)
                # Ensure exactly one blank line above the paragraph (force add; later dedupe will keep max one)
                if len(lines) > 0:
                    lines.append(PARA_BREAK)
                parts = norm.split("\n")
                for idx, part in enumerate(parts):
                    if idx == 0:
                        lines.append(part)
                    else:
                        # Mark lines produced by <br> so later formatting does NOT insert a blank between them
                        lines.append(f"{INPARA_SENTINEL}{part}")
                # Ensure exactly one blank line below the paragraph
                lines.append(PARA_BREAK)
            elif name == "blockquote":
                norm = normalize_paragraph_text(el)
                if len(lines) > 0 and lines[-1].strip() != "":
                    lines.append(PARA_BREAK)
                for part in norm.split("\n"):
                    lines.append(part)
                lines.append(PARA_BREAK)
            elif name == "pre":
                norm = normalize_pre_text(el)
                if len(lines) > 0 and lines[-1].strip() != "":
                    lines.append(PARA_BREAK)
                for part in norm.split("\n"):
                    lines.append(part)
                lines.append(PARA_BREAK)
            else:
                # Fallback for other block elements handled here (blockquote, pre)
                for part in text.splitlines():
                    part = " ".join(part.strip().split())
                    if part:
                        lines.append(part)
                lines.append(PARA_BREAK)
        elif name in ("ol", "ul", "li"):
            # naive list item render
            if name == "li":
                lines.append(f"* {text}")
                lines.append("")
        elif name in ("em", "strong"):
            # already captured via text walk; skip
            continue

    # No document attribute header (:title:) — use the = Title heading instead
    header = []

    # Keep paragraph break tokens for downstream passes (promotion), dedupe them here logically
    normalized = []
    last_blank = False
    for ln in lines:
        if ln == PARA_BREAK or ln.strip() == "":
            if not last_blank:
                normalized.append(PARA_BREAK)
            last_blank = True
        else:
            normalized.append(ln)
            last_blank = False

    # Ensure exactly one blank line between plain paragraph lines.
    # Do not interfere with headings, lists, attribute blocks, or fenced blocks.
    enforced = []
    for i, ln in enumerate(normalized):
        if ln == PARA_BREAK:
            # propagate token as-is
            enforced.append(ln)
            continue
        if enforced:
            prev = enforced[-1]
            if prev not in (PARA_BREAK, "") and ln.strip() != "":
                prev_is_structural = (
                    prev.lstrip().startswith(("=", "* ", "- ", ". "))
                    or re.match(r"^\d+\.\s", prev.lstrip()) is not None
                    or (prev.strip().startswith("[") and prev.strip().endswith("]"))
                )
                curr_is_structural = (
                    ln.lstrip().startswith(("=", "* ", "- ", ". "))
                    or re.match(r"^\d+\.\s", ln.lstrip()) is not None
                    or (ln.strip().startswith("[") and ln.strip().endswith("]"))
                )
                # Do not insert breaks between lines that are part of the same paragraph
                # (originating from <br> inside a <p>), which are marked with INPARA_SENTINEL.
                prev_is_inpara = prev.lstrip().startswith(INPARA_SENTINEL)
                curr_is_inpara = ln.lstrip().startswith(INPARA_SENTINEL)
                if not prev_is_structural and not curr_is_structural and not prev_is_inpara and not curr_is_inpara:
                    enforced.append(PARA_BREAK)  # insert missing blank between plain blocks
        enforced.append(ln)

    # Finalize here by keeping tokens; they will be turned into blanks at the CLI final pass
    return "\n".join(header + enforced) + "\n"


