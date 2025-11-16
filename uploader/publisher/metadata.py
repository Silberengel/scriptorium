from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import yaml


@dataclass
class Metadata:
    title: str
    author: str
    publisher: str
    year: str
    language: str
    collection_id: str
    has_collection: bool
    use_bookstr: bool
    book_title_mapping_file: Optional[str]
    wikistr_mappings: List[Dict[str, str]]


def load_metadata(base_dir: Path) -> Optional[Metadata]:
    meta_path = base_dir / "@metadata.yml"
    if not meta_path.exists():
        return None
    data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}

    def _get(key: str, default: Any = "") -> Any:
        return data.get(key, default)

    return Metadata(
        title=str(_get("title", "")),
        author=str(_get("author", "")),
        publisher=str(_get("publisher", "")),
        year=str(_get("year", "")),
        language=str(_get("language", "en")),
        collection_id=str(_get("collection_id", base_dir.name)),
        has_collection=bool(_get("has_collection", True)),
        use_bookstr=bool(_get("use_bookstr", True)),
        book_title_mapping_file=_get("book_title_mapping_file"),
        wikistr_mappings=list(_get("wikistr_mappings", [])),
    )


def load_title_mapping(base_dir: Path, md: Optional[Metadata]) -> Dict[str, str]:
    """
    Build a mapping from display titles -> canonical names (wikistr/bookstr).
    Priority:
      1) entries in md.wikistr_mappings
      2) entries from YAML file md.book_title_mapping_file if provided
    """
    mapping: Dict[str, str] = {}
    if md is None:
        return mapping
    # inline mappings
    for item in (md.wikistr_mappings or []):
        disp = str(item.get("display", "")).strip()
        canon = str(item.get("canonical", "")).strip()
        if disp and canon:
            mapping[disp] = canon
    # file mapping
    if md.book_title_mapping_file:
        p = (base_dir / md.book_title_mapping_file).resolve()
        try:
            y = yaml.safe_load(p.read_text(encoding="utf-8")) or []
            for item in y:
                disp = str(item.get("display", "")).strip()
                canon = str(item.get("canonical", "")).strip()
                if disp and canon:
                    mapping[disp] = canon
        except Exception:
            # ignore file errors deliberately to keep pipeline moving
            pass
    return mapping


