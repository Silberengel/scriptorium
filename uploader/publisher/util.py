import binascii
import hashlib
import re
from typing import Optional

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


