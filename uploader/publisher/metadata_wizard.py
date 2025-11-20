from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from pathlib import Path
import yaml

from .util import slugify


@dataclass
class MetadataDraft:
    title: str
    author: str
    language: str
    collection_id: str
    has_collection: bool
    levels: Dict[str, str]
    wikistr_mappings: List[Dict[str, str]]
    use_bookstr: bool
    book_title_mapping_file: str | None
    book_metadata: List[Dict[str, Any]]
    chapter_metadata: List[Dict[str, Any]] | None
    section_metadata: List[Dict[str, Any]] | None
    # NKBIP-01 standard fields
    published_on: str | None = None
    published_by: str | None = None
    summary: str | None = None
    type: str = "book"
    auto_update: str = "ask"
    source: str | None = None
    image: str | None = None
    version: str | None = None
    # Derivative works
    derivative_author: str | None = None
    derivative_event: str | None = None
    derivative_relay: str | None = None
    derivative_pubkey: str | None = None
    # Additional tags
    additional_tags: List[List[str]] | None = None


def draft_metadata_from_document(
    *,
    inferred_title: str,
    inferred_author: str | None = None,
    inferred_language: str = "en",
    has_collection: bool = False,
    book_titles: Optional[List[str]] = None,
    base_dir: Optional[Path] = None,
) -> MetadataDraft:
    collection_id = slugify(inferred_title or "publication")
    books = [{"title": t} for t in (book_titles or [])]
    
    # Check if book_title_map.yml exists in the base directory
    book_title_mapping_file = None
    if base_dir:
        book_title_map_path = base_dir / "book_title_map.yml"
        if book_title_map_path.exists():
            book_title_mapping_file = "book_title_map.yml"
    
    return MetadataDraft(
        title=inferred_title or "Untitled",
        author=inferred_author or "",
        language=inferred_language,
        collection_id=collection_id,
        has_collection=has_collection,
        levels={"collection": "Collection", "book": "Book", "chapter": "Chapter", "verse": "Verse"},
        wikistr_mappings=[],
        use_bookstr=True,
        book_title_mapping_file=book_title_mapping_file,
        book_metadata=books,
        chapter_metadata=None,
        section_metadata=None,
        # NKBIP-01 standard fields with defaults
        published_on=None,
        published_by=None,
        summary=None,
        type="book",
        auto_update="ask",
        source=None,
        image=None,
        version=None,
        derivative_author=None,
        derivative_event=None,
        derivative_relay=None,
        derivative_pubkey=None,
        additional_tags=None,
    )


def write_metadata_yaml(path: str, draft: MetadataDraft) -> None:
    data = asdict(draft)
    
    # Always include all NKBIP-01 standard fields, even if None
    # This helps users see what fields are available and fill them in
    nkbip01_fields = [
        'published_on', 'published_by', 'summary', 'type', 'auto_update',
        'source', 'image', 'version',
        'derivative_author', 'derivative_event', 'derivative_relay', 'derivative_pubkey',
        'additional_tags'
    ]
    
    # Core fields that should always be present
    core_fields = ['title', 'author', 'language', 'collection_id', 'has_collection', 
                   'use_bookstr', 'book_title_mapping_file']
    
    # Build output with all standard fields in a logical order
    output_data = {}
    
    # 1. Core required fields
    for field in core_fields:
        if field in data:
            output_data[field] = data[field]
    
    # 2. NKBIP-01 standard fields (ALWAYS include, even if None)
    for field in nkbip01_fields:
        output_data[field] = data.get(field)  # This will be None if not set
    
    # 3. Other fields (only if they have values)
    for k, v in data.items():
        if k not in core_fields and k not in nkbip01_fields and v is not None:
            # Include non-standard fields only if they have values
            if isinstance(v, (list, dict)) and len(v) == 0:
                # Include empty lists/dicts for important fields
                if k in ['wikistr_mappings', 'book_metadata']:
                    output_data[k] = v
            else:
                output_data[k] = v
    
    # Write YAML - use represent_none to show null explicitly
    def represent_none(self, _):
        return self.represent_scalar('tag:yaml.org,2002:null', 'null')
    
    yaml.add_representer(type(None), represent_none)
    
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(output_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False, 
                       explicit_start=False, explicit_end=False)


