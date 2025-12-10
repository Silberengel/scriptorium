"""
Slug generation and text normalization for identifiers.
"""
import re
import unicodedata


def slugify(text: str) -> str:
    """
    Convert text to a URL-friendly slug.
    """
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text


def slugify_strict(text: str) -> str:
    """
    Produce an ASCII slug using only [a-z0-9-].
    - Lowercases
    - Replaces any run of non [a-z0-9]+ with a single hyphen
    - Trims leading/trailing hyphens
    """
    s = text.strip().lower()
    # Decompose unicode then drop non-ascii
    try:
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    except Exception:
        pass
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s


def compress_slug_parts(parts: list[str], max_len: int = 75) -> str:
    """
    Join parts with '-' ensuring total length <= max_len.
    Strategy:
      1) Filter out empty parts
      2) If over, abbreviate non-leaf parts (all but last 2) to 6 chars
      3) If over, abbreviate non-leaf parts to 3 chars
      4) If still over, drop oldest leftmost parts until fits (keep last 2-3)
    """
    filtered = [p for p in parts if p]
    if not filtered:
        return ""
    def join(ps: list[str]) -> str:
        return "-".join(ps)
    d = join(filtered)
    if len(d) <= max_len:
        return d
    # Step 2: abbreviate non-leaf (all but last 2)
    if len(filtered) > 2:
        abr = [ (p[:6] if i < len(filtered) - 2 else p) for i,p in enumerate(filtered) ]
        d2 = join(abr)
        if len(d2) <= max_len:
            return d2
        # Step 3: abbreviate to 3 chars
        abr3 = [ (p[:3] if i < len(filtered) - 2 else p) for i,p in enumerate(filtered) ]
        d3 = join(abr3)
        if len(d3) <= max_len:
            return d3
        filtered = abr3
    # Step 4: drop from left until fits, keep at least last 2
    while len(join(filtered)) > max_len and len(filtered) > 2:
        filtered = filtered[1:]
    return join(filtered)

