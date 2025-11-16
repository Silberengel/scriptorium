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

    # Preserve explicit line breaks: convert <br> to newline nodes
    for br in soup.find_all("br"):
        br.replace_with(NavigableString("\n"))

    def normalize_paragraph_text(raw: str) -> str:
        # Strip invisible chars, then unwrap soft wraps within a paragraph
        # while preserving explicit \n that came from <br>
        raw = _strip_invisible(raw)
        parts = raw.split("\n")
        cleaned_lines = []
        for part in parts:
            # collapse internal whitespace to single spaces
            txt = " ".join(part.strip().split())
            cleaned_lines.append(txt)
        return "\n".join(cleaned_lines).strip()

    doc_title = None
    saw_first_post_title_heading = False
    saw_first_h2_after_title = False
    lines = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "blockquote", "pre", "ol", "ul", "li", "em", "strong"]):
        name = el.name.lower()
        # Use separator "\n" so <br> becomes a break in the extracted text
        text = el.get_text("\n", strip=True)
        if not text:
            continue
        if name == "h1":
            # Use only the first H1 as the document title heading; ignore all subsequent H1s
            if doc_title is None:
                doc_title = text
                lines.append(f"= {text}")
                lines.append("")
            # else: skip subsequent H1 entirely
        elif name == "h2":
            if not saw_first_h2_after_title:
                lines.append(f"== {text}")
                saw_first_h2_after_title = True
            else:
                # Demote subsequent H2 to level-3 to represent book-level under sub-collection
                lines.append(f"=== {text}")
            lines.append("")
        elif name == "h3":
            # If we already have a document title, promote the first subtitle to level-2
            if doc_title and not saw_first_post_title_heading:
                lines.append(f"== {text}")
                saw_first_post_title_heading = True
            else:
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
            norm = normalize_paragraph_text(text)
            for part in norm.split("\n"):
                lines.append(part)
            lines.append("")
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

    # Remove any accidental consecutive blank lines (keep max one)
    normalized = []
    last_blank = False
    for ln in lines:
        if ln.strip() == "":
            if not last_blank:
                normalized.append("")
            last_blank = True
        else:
            normalized.append(ln)
            last_blank = False

    return "\n".join(header + normalized) + "\n"


