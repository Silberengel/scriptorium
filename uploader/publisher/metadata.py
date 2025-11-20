from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import yaml


@dataclass
class Metadata:
    title: str
    author: str
    # Fields with defaults must come after fields without defaults
    language: str = "en"
    collection_id: str = ""
    has_collection: bool = True
    use_bookstr: bool = True
    book_title_mapping_file: Optional[str] = None
    wikistr_mappings: List[Dict[str, str]] = field(default_factory=list)
    type: str = "book"  # Publication type (default: "book")
    published_on: Optional[str] = None  # Publication date (e.g., "2003-05-13" or "1899")
    published_by: Optional[str] = None  # Publication source (e.g., "public domain")
    summary: Optional[str] = None  # Publication summary/description
    version: Optional[str] = None  # Publication version (e.g., "KJV", "DRM", "3rd edition")
    additional_tags: List[List[str]] = field(default_factory=list)  # Additional NKBIP-01 tags (e.g., [["i", "isbn:..."], ["t", "fables"]])
    auto_update: Optional[str] = None  # Auto-update behavior: "yes", "ask", or "no" (default: "ask" if not specified)
    source: Optional[str] = None  # Source URL for the publication
    image: Optional[str] = None  # Image URL for the publication cover
    derivative_author: Optional[str] = None  # Pubkey of original author (for derivative works)
    derivative_event: Optional[str] = None  # Event ID of original event (for derivative works)
    derivative_relay: Optional[str] = None  # Relay URL for original event (for derivative works)
    derivative_pubkey: Optional[str] = None  # Pubkey for original event (for derivative works, typically same as derivative_author)


def load_metadata(base_dir: Path) -> Optional[Metadata]:
    meta_path = base_dir / "@metadata.yml"
    if not meta_path.exists():
        return None
    data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}

    def _get(key: str, default: Any = "") -> Any:
        return data.get(key, default)

    # Support both "year" (legacy) and "published_on" (NKBIP-01)
    published_on_val = _get("published_on") or _get("year")
    return Metadata(
        title=str(_get("title", "")),
        author=str(_get("author", "")),
        language=str(_get("language", "en")),
        collection_id=str(_get("collection_id", base_dir.name)),
        has_collection=bool(_get("has_collection", True)),
        use_bookstr=bool(_get("use_bookstr", True)),
        book_title_mapping_file=_get("book_title_mapping_file"),
        wikistr_mappings=list(_get("wikistr_mappings", [])),
        type=str(_get("type", "book")),  # Default to "book"
        published_on=str(published_on_val) if published_on_val else None,
        published_by=_get("published_by"),  # Optional published_by
        summary=_get("summary") or _get("description"),  # Support both "summary" (NKBIP-01) and "description" (legacy)
        version=_get("version"),  # Optional version
        additional_tags=_get("additional_tags", []),  # Additional tags as list of lists
        auto_update=_get("auto_update", "ask"),  # Auto-update behavior (default: "ask")
        source=_get("source"),  # Optional source URL
        image=_get("image"),  # Optional image URL
        derivative_author=_get("derivative_author"),  # Optional original author pubkey for derivative works
        derivative_event=_get("derivative_event"),  # Optional original event ID for derivative works
        derivative_relay=_get("derivative_relay"),  # Optional relay URL for original event
        derivative_pubkey=_get("derivative_pubkey"),  # Optional pubkey for original event
    )


def load_title_mapping(base_dir: Path, md: Optional[Metadata]) -> Dict[str, Dict[str, str]]:
    """
    Build a mapping from display titles -> canonical names (wikistr/bookstr).
    Returns a dict mapping display -> {"canonical-long": ..., "canonical-short": ...}
    Priority:
      1) entries in md.wikistr_mappings
      2) entries from YAML file md.book_title_mapping_file if provided
    """
    mapping: Dict[str, Dict[str, str]] = {}
    if md is None:
        return mapping
    # inline mappings
    for item in (md.wikistr_mappings or []):
        disp = str(item.get("display", "")).strip()
        # Support both old format (canonical) and new format (canonical-long, canonical-short)
        canon_long = str(item.get("canonical-long", item.get("canonical", ""))).strip()
        canon_short = str(item.get("canonical-short", item.get("canonical", ""))).strip()
        if disp and canon_long:
            # Store with lowercase key for case-insensitive matching
            mapping[disp.lower()] = {
                "canonical-long": canon_long,
                "canonical-short": canon_short if canon_short else canon_long
            }
    # file mapping
    if md.book_title_mapping_file:
        p = (base_dir / md.book_title_mapping_file).resolve()
        try:
            y = yaml.safe_load(p.read_text(encoding="utf-8")) or []
            for item in y:
                disp = str(item.get("display", "")).strip()
                # Support both old format (canonical) and new format (canonical-long, canonical-short)
                canon_long = str(item.get("canonical-long", item.get("canonical", ""))).strip()
                canon_short = str(item.get("canonical-short", item.get("canonical", ""))).strip()
                if disp and canon_long:
                    # Store with lowercase key for case-insensitive matching
                    mapping[disp.lower()] = {
                        "canonical-long": canon_long,
                        "canonical-short": canon_short if canon_short else canon_long
                    }
        except Exception:
            # ignore file errors deliberately to keep pipeline moving
            pass
    return mapping


