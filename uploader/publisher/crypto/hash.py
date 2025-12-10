"""
Hash functions for cryptographic operations.
"""
import hashlib


def sha256_hex(data: bytes) -> str:
    """Compute SHA256 hash and return as hex string."""
    return hashlib.sha256(data).hexdigest()

