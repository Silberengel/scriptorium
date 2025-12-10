"""
Initialize metadata command handler.
"""
import sys
from pathlib import Path

from ..metadata_wizard import draft_metadata_from_document, write_metadata_yaml
from ..config import load_config


def cmd_init_metadata(args) -> int:
    """Initialize metadata file from document."""
    cfg = load_config()
    src_path = Path(args.input)
    if not src_path.exists():
        print(f"Input not found: {src_path}", file=sys.stderr)
        return 1
    # very naive title inference from filename
    inferred_title = src_path.parent.name.replace("-", " ").title()
    base_dir = src_path.parent
    draft = draft_metadata_from_document(
        inferred_title=inferred_title,
        inferred_author=None,
        inferred_language="en",
        has_collection=bool(args.has_collection),
        book_titles=None,
        base_dir=base_dir,
    )
    out_yaml = src_path.parent / "@metadata.yml"
    write_metadata_yaml(str(out_yaml), draft)
    print(f"Wrote metadata draft: {out_yaml}")
    return 0

