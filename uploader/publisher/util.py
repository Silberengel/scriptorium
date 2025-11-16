import binascii
import hashlib
import re
from typing import Optional
import unicodedata

try:
    # Optional, nicer bech32 library if available
    from bech32 import bech32_decode, convertbits
except Exception:
    bech32_decode = None
    convertbits = None

_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


def _bech32_decode_nsec(nsec: str) -> Optional[bytes]:
    """
    Decode bech32 'nsec' into raw 32-byte secret key.
    Returns None on failure.
    """
    if bech32_decode is None or convertbits is None:
        return None
    hrp, data = bech32_decode(nsec)
    if hrp != "nsec" or data is None:
        return None
    decoded = bytes(convertbits(data, 5, 8, False) or [])
    if len(decoded) != 32:
        return None
    return decoded


def normalize_secret_key_to_hex(key: str) -> str:
    """
    Accepts bech32 (nsec...) or hex. Returns lowercase hex string (64 chars).
    """
    key = key.strip()
    if key.startswith("nsec"):
        raw = _bech32_decode_nsec(key)
        if raw is None:
            raise ValueError("Invalid nsec bech32 secret key")
        return raw.hex()
    # assume hex
    if not _HEX_RE.match(key):
        raise ValueError("Secret key must be bech32 nsec... or hex")
    # ensure even-length and 32 bytes
    if len(key) != 64:
        # try to normalize odd-len or uppercase
        try:
            raw = binascii.unhexlify(key)
        except Exception as e:
            raise ValueError(f"Invalid hex secret key: {e}")
        if len(raw) != 32:
            raise ValueError("Hex secret key must be 32 bytes (64 hex chars)")
        return raw.hex()
    return key.lower()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def slugify(text: str) -> str:
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
        import unicodedata
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


def strip_invisible_text(text: str) -> str:
    """
    Remove a broad set of invisible/control characters and normalize spaces.
    - Removes all codepoints in Unicode category 'C*' except tab/newline
    - Converts NBSP and NNBSP to regular spaces
    - Removes ZWJ/ZWNJ and similar joiners
    - Collapses repeated spaces
    """
    if not text:
        return text
    # Map common space variants to regular space
    text = (
        text.replace("\u00A0", " ")  # NBSP
        .replace("\u202F", " ")      # NNBSP
        .replace("\u2007", " ")      # figure space
    )
    cleaned_chars = []
    for ch in text:
        if ch in ("\t", "\n", "\r"):
            cleaned_chars.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("C"):  # Control/Other (Cc, Cf, Cs, Co, Cn)
            # drop control/invisible chars
            continue
        cleaned_chars.append(ch)
    cleaned = "".join(cleaned_chars)
    # Remove zero-width joiners explicitly (in case categorized differently)
    cleaned = cleaned.replace("\u200B", "").replace("\u200C", "").replace("\u200D", "").replace("\ufeff", "")
    # Collapse runs of spaces
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    # Trim trailing spaces on lines
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned


def to_ascii_text(text: str) -> str:
    """
    Best-effort transliteration to ASCII.
    - Unicode NFKD decomposition
    - Drop non-ASCII codepoints
    """
    if not text:
        return text
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii")


def unwrap_hard_wraps(text: str, *, min_level: int = 4) -> str:
    """
    Merge hard-wrapped lines within paragraphs into single lines,
    but only inside level-4 sections (==== heading) and deeper.
    Rules:
      - Track current heading level based on leading '='
      - Only unwrap when current_level >= 4 (section content)
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
        # accumulate paragraph line only if inside section (level >= 4)
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


