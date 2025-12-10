"""
Text processing and normalization functions for AsciiDoc content.
"""
from .normalization import (
    normalize_ambiguous_unicode,
    normalize_headings,
    strip_invisible_text,
    to_ascii_text,
)
from .formatting import (
    ensure_blank_before_attributes,
    ensure_blank_before_headings,
    ensure_blank_between_paragraphs,
    remove_discrete_attributes,
    unwrap_hard_wraps,
)
from .slug import (
    compress_slug_parts,
    slugify,
    slugify_strict,
)

__all__ = [
    # Normalization
    "normalize_ambiguous_unicode",
    "normalize_headings",
    "strip_invisible_text",
    "to_ascii_text",
    # Formatting
    "ensure_blank_before_attributes",
    "ensure_blank_before_headings",
    "ensure_blank_between_paragraphs",
    "remove_discrete_attributes",
    "unwrap_hard_wraps",
    # Slug
    "compress_slug_parts",
    "slugify",
    "slugify_strict",
]

