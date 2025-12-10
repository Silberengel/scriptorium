"""
Parsing utilities for Nostr event references and tags.
"""
from typing import Any, Dict

try:
    from bech32 import bech32_decode, convertbits
except ImportError:
    bech32_decode = None
    convertbits = None


def decode_nevent(nevent: str) -> Dict[str, Any]:
    """
    Decode a nevent (bech32 encoded event reference).
    Returns dict with: event_id, relay_hint, author_hint
    """
    if bech32_decode is None or convertbits is None:
        raise RuntimeError("bech32 library required for nevent decoding")
    
    if not nevent.startswith("nevent1"):
        raise ValueError(f"Invalid nevent format: {nevent}")
    
    # Decode bech32
    hrp, data = bech32_decode(nevent)
    if hrp != "nevent":
        raise ValueError(f"Invalid nevent HRP: {hrp}")
    
    # Convert from 5-bit to 8-bit
    decoded = convertbits(data, 5, 8, False)
    if decoded is None:
        raise ValueError("Failed to decode bech32 data")
    
    # Parse TLV format
    result = {}
    i = 0
    while i < len(decoded):
        if i + 1 >= len(decoded):
            break
        t = decoded[i]
        l = decoded[i + 1]
        if i + 2 + l > len(decoded):
            break
        v = decoded[i + 2:i + 2 + l]
        
        if t == 0:  # event ID (32 bytes)
            result["event_id"] = bytes(v).hex()
        elif t == 1:  # relay hint (string)
            result["relay_hint"] = bytes(v).decode('utf-8')
        elif t == 2:  # author hint (32 bytes)
            result["author_hint"] = bytes(v).hex()
        
        i += 2 + l
    
    if "event_id" not in result:
        raise ValueError("nevent missing event ID")
    
    return result


def decode_naddr(naddr: str) -> Dict[str, Any]:
    """
    Decode an naddr (bech32 encoded address: kind:pubkey:d-tag).
    Returns dict with: kind, pubkey, d_tag, relay_hint
    """
    if bech32_decode is None or convertbits is None:
        raise RuntimeError("bech32 library required for naddr decoding")
    
    if not naddr.startswith("naddr1"):
        raise ValueError(f"Invalid naddr format: {naddr}")
    
    # Decode bech32
    hrp, data = bech32_decode(naddr)
    if hrp != "naddr":
        raise ValueError(f"Invalid naddr HRP: {hrp}")
    
    # Convert from 5-bit to 8-bit
    decoded = convertbits(data, 5, 8, False)
    if decoded is None:
        raise ValueError("Failed to decode bech32 data")
    
    # Parse TLV format
    result = {}
    i = 0
    while i < len(decoded):
        if i + 1 >= len(decoded):
            break
        t = decoded[i]
        l = decoded[i + 1]
        if i + 2 + l > len(decoded):
            break
        v = decoded[i + 2:i + 2 + l]
        
        if t == 0:  # kind (varint, but we'll read as bytes and convert)
            # Kind is stored as a varint, but for simplicity, read as little-endian uint32
            kind_bytes = bytes(v)
            if len(kind_bytes) <= 4:
                kind = int.from_bytes(kind_bytes, byteorder='little')
                result["kind"] = kind
        elif t == 1:  # pubkey (32 bytes)
            result["pubkey"] = bytes(v).hex()
        elif t == 2:  # d-tag (string)
            result["d_tag"] = bytes(v).decode('utf-8')
        elif t == 3:  # relay hint (string)
            result["relay_hint"] = bytes(v).decode('utf-8')
        
        i += 2 + l
    
    if "kind" not in result or "pubkey" not in result or "d_tag" not in result:
        raise ValueError("naddr missing required fields (kind, pubkey, d_tag)")
    
    return result


def parse_event_reference(ref: str) -> Dict[str, Any]:
    """
    Parse an event reference in any format: nevent, naddr, or hex event ID.
    Returns dict with: event_id, relay_hint, author_hint (for nevent/hex)
                      or kind, pubkey, d_tag, relay_hint (for naddr)
    """
    ref = ref.strip()
    
    # Check if it's a hex event ID (64 hex characters)
    if len(ref) == 64 and all(c in '0123456789abcdefABCDEF' for c in ref):
        return {
            "event_id": ref.lower(),
            "relay_hint": None,
            "author_hint": None,
        }
    
    # Check if it's a nevent
    if ref.startswith("nevent1"):
        return decode_nevent(ref)
    
    # Check if it's an naddr
    if ref.startswith("naddr1"):
        return decode_naddr(ref)
    
    raise ValueError(f"Invalid event reference format. Expected nevent, naddr, or 64-char hex ID, got: {ref[:20]}...")


def parse_a_tag(a_tag_value: str) -> Dict[str, str]:
    """
    Parse an a-tag value: "<kind>:<pubkey>:<d-tag>"
    Returns dict with: kind, pubkey, d_tag
    """
    parts = a_tag_value.split(":", 2)
    if len(parts) != 3:
        raise ValueError(f"Invalid a-tag format. Expected 'kind:pubkey:d-tag', got: {a_tag_value}")
    
    return {
        "kind": parts[0],
        "pubkey": parts[1],
        "d_tag": parts[2],
    }

