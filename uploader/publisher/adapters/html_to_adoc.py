from bs4 import BeautifulSoup
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

    lines = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "blockquote", "pre", "ol", "ul", "li", "em", "strong"]):
        name = el.name.lower()
        text = _strip_invisible(el.get_text(" ", strip=True))
        if not text:
            continue
        if name == "h1":
            lines.append(f"= {text}")
        elif name == "h2":
            lines.append(f"== {text}")
        elif name == "h3":
            lines.append(f"=== {text}")
        elif name == "h4":
            lines.append(f"==== {text}")
        elif name in ("p", "blockquote", "pre"):
            lines.append(text)
        elif name in ("ol", "ul", "li"):
            # naive list item render
            if name == "li":
                lines.append(f"* {text}")
        elif name in ("em", "strong"):
            # already captured via text walk; skip
            continue

    header = [
        f":doctype: article",
        f":lang: {language}",
        "",
    ]
    return "\n".join(header + lines) + "\n"


