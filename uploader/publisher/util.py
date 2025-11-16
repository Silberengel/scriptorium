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


def unwrap_hard_wraps(text: str) -> str:
    """
    Merge hard-wrapped lines within paragraphs into single lines.
    Rules:
      - Preserve blank lines (paragraph separators)
      - Preserve headings (=, ==, etc.), list items (*, -, . , numbered), block fences
      - Within a paragraph block, join lines with a single space
    """
    if not text:
        return text
    out_lines = []
    buffer = []

    def is_structural(line: str) -> bool:
        l = line.lstrip()
        if not l:
            return True
        # headings
        if l.startswith("="):
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

    for line in text.splitlines():
        if not line.strip():  # blank line → paragraph break
            flush_buffer()
            out_lines.append("")
            continue
        if is_structural(line):
            flush_buffer()
            out_lines.append(line)
            continue
        # accumulate paragraph line
        buffer.append(line)

    flush_buffer()
    return "\n".join(out_lines) + "\n"


