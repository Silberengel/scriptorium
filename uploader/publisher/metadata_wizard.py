from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
import yaml

from .util import slugify


@dataclass
class MetadataDraft:
    title: str
    author: str
    publisher: str
    year: int | str
    language: str
    description: str | None
    collection_id: str
    has_collection: bool
    levels: Dict[str, str]
    wikistr_mappings: List[Dict[str, str]]
    use_bookstr: bool
    book_title_mapping_file: str | None
    book_metadata: List[Dict[str, Any]]
    chapter_metadata: List[Dict[str, Any]] | None
    section_metadata: List[Dict[str, Any]] | None


def draft_metadata_from_document(
    *,
    inferred_title: str,
    inferred_author: str | None = None,
    inferred_language: str = "en",
    has_collection: bool = False,
    book_titles: Optional[List[str]] = None,
) -> MetadataDraft:
    collection_id = slugify(inferred_title or "publication")
    books = [{"title": t} for t in (book_titles or [])]
    return MetadataDraft(
        title=inferred_title or "Untitled",
        author=inferred_author or "",
        publisher="",
        year="",
        language=inferred_language,
        description=None,
        collection_id=collection_id,
        has_collection=has_collection,
        levels={"collection": "Collection", "book": "Book", "chapter": "Chapter", "section": "Section"},
        wikistr_mappings=[],
        use_bookstr=True,
        book_title_mapping_file=None,
        book_metadata=books,
        chapter_metadata=None,
        section_metadata=None,
    )


def write_metadata_yaml(path: str, draft: MetadataDraft) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(asdict(draft), f, allow_unicode=True, sort_keys=False)


