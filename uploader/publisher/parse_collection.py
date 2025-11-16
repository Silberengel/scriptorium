from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import re


@dataclass
class SectionNode:
    title: str
    content: str
    index_path: List[str]  # [collection?, book, chapter, section-id]


@dataclass
class ChapterNode:
    title: str
    sections: List[SectionNode] = field(default_factory=list)


@dataclass
class BookNode:
    title: str
    chapters: List[ChapterNode] = field(default_factory=list)


@dataclass
class CollectionTree:
    title: str
    books: List[BookNode] = field(default_factory=list)


HEADING_RE = re.compile(r"^(=+)\s+(.*)$")


def parse_adoc_structure(
    adoc_text: str,
    *,
    has_collection: bool = True,
    collection_title: Optional[str] = None,
) -> CollectionTree:
    """
    Very simple AsciiDoc parser that uses heading levels:
      = collection title (optional if has_collection)
      == book
      === chapter
      ==== section
    Content under a ==== heading is the section content.
    """
    lines = adoc_text.splitlines()
    current_book: Optional[BookNode] = None
    current_chapter: Optional[ChapterNode] = None
    current_section_title: Optional[str] = None
    current_section_lines: List[str] = []

    books: List[BookNode] = []
    top_title = collection_title or "Collection"

    def flush_section():
        nonlocal current_section_title, current_section_lines, current_chapter
        if current_section_title is None or current_chapter is None:
            return
        content = "\n".join(current_section_lines).strip()
        section = SectionNode(
            title=current_section_title,
            content=content,
            index_path=[],
        )
        current_chapter.sections.append(section)
        current_section_title = None
        current_section_lines = []

    for ln in lines:
        m = HEADING_RE.match(ln)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            # On new heading, flush prior section if needed
            if level <= 4:
                flush_section()
            if has_collection and level == 1:
                top_title = title or top_title
                continue
            if (level == 1 and not has_collection) or level == 2:
                # book
                current_book = BookNode(title=title)
                books.append(current_book)
                current_chapter = None
                continue
            if level == 3:
                # chapter
                if current_book is None:
                    # create implicit book
                    current_book = BookNode(title="Book")
                    books.append(current_book)
                current_chapter = ChapterNode(title=title)
                current_book.chapters.append(current_chapter)
                continue
            if level == 4:
                # section
                current_section_title = title if title else "Preamble"
                current_section_lines = []
                continue
            # deeper levels are appended to current section as text
            current_section_lines.append(ln)
        else:
            # body line
            if current_section_title is not None:
                current_section_lines.append(ln)
            # ignore global text outside sections for now

    flush_section()
    tree = CollectionTree(title=top_title, books=books)
    # Fill index_path for sections
    for bi, b in enumerate(tree.books, 1):
        for ci, c in enumerate(b.chapters, 1):
            for si, s in enumerate(c.sections, 1):
                if has_collection:
                    s.index_path = [tree.title, b.title, str(ci), str(si)]
                else:
                    s.index_path = [b.title, str(ci), str(si)]
    return tree


