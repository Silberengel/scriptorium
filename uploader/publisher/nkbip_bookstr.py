from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Dict, List, Any
import orjson

from .parse_collection import CollectionTree
from .util import slugify, sha256_hex


@dataclass
class Event:
    kind: int
    tags: List[List[str]]
    content: str

    def to_json(self) -> str:
        return orjson.dumps({"kind": self.kind, "tags": self.tags, "content": self.content}).decode("utf-8")


def _d_for(*parts: str) -> str:
    norm = [slugify(p) for p in parts if p]
    return "/".join(norm)


def serialize_bookstr(
    tree: CollectionTree,
    *,
    collection_id: str,
    language: str = "en",
    use_bookstr: bool = True,
    book_title_map: dict[str, str] | None = None,
) -> List[Event]:
    """
    Convert parsed tree into bookstr-like events.
    - Indexes (collection/book/chapter) emitted as kind 30040 (placeholder)
    - Sections (content pages) emitted as kind 30041
    """
    events: List[Event] = []

    # collection index
    c_d = _d_for(collection_id)
    tags = [["d", c_d], ["t", tree.title], ["L", language], ["m", "text/asciidoc"]]
    events.append(
        Event(
            kind=30040,
            tags=tags,
            content="",
        )
    )

    for b in tree.books:
        b_d = _d_for(collection_id, b.title)
        b_tags = [["d", b_d], ["t", b.title], ["L", language], ["m", "text/asciidoc"]]
        if use_bookstr and book_title_map:
            canon = book_title_map.get(b.title)
            if canon:
                b_tags.append(["name", canon])
        events.append(
            Event(
                kind=30040,
                tags=b_tags,
                content="",
            )
        )
        for ci, c in enumerate(b.chapters, 1):
            c_d = _d_for(collection_id, b.title, str(ci))
            c_tags = [["d", c_d], ["t", c.title], ["L", language], ["m", "text/asciidoc"]]
            if use_bookstr and book_title_map:
                canon = book_title_map.get(b.title)
                if canon:
                    c_tags.append(["name", canon])
            events.append(
                Event(
                    kind=30040,
                    tags=c_tags,
                    content="",
                )
            )
            for si, s in enumerate(c.sections, 1):
                s_d = _d_for(collection_id, b.title, str(ci), str(si))
                title = s.title or f"{b.title} {ci}:{si}"
                s_tags = [["d", s_d], ["t", title], ["L", language], ["m", "text/asciidoc"]]
                if use_bookstr and book_title_map:
                    canon = book_title_map.get(b.title)
                    if canon:
                        s_tags.append(["name", canon])
                events.append(
                    Event(
                        kind=30041,
                        tags=s_tags,
                        content=s.content,
                    )
                )
    return events


