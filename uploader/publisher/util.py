"""
Compatibility shim for util.py - redirects to new module structure.

This module maintains backward compatibility by re-exporting functions
from the new organized modules.
"""
# Crypto functions
from .crypto import normalize_secret_key_to_hex, sha256_hex

# Text processing functions
from .text import (
    compress_slug_parts,
    ensure_blank_before_attributes,
    ensure_blank_before_headings,
    ensure_blank_between_paragraphs,
    normalize_ambiguous_unicode,
    normalize_headings,
    remove_discrete_attributes,
    slugify,
    slugify_strict,
    strip_invisible_text,
    to_ascii_text,
    unwrap_hard_wraps,
)

__all__ = [
    # Crypto
    "normalize_secret_key_to_hex",
    "sha256_hex",
    # Text processing
    "compress_slug_parts",
    "ensure_blank_before_attributes",
    "ensure_blank_before_headings",
    "ensure_blank_between_paragraphs",
    "normalize_ambiguous_unicode",
    "normalize_headings",
    "remove_discrete_attributes",
    "slugify",
    "slugify_strict",
    "strip_invisible_text",
    "to_ascii_text",
    "unwrap_hard_wraps",
]
