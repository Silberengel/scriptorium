import argparse
import sys
from pathlib import Path

from .config import load_config
from .io_layout import Layout
from .adapters.html_to_adoc import html_to_adoc
from .adapters.adoc_identity import normalize_adoc
from .metadata_wizard import draft_metadata_from_document, write_metadata_yaml
from .parse_collection import parse_adoc_structure
from .nkbip_bookstr import serialize_bookstr
from .nostr_client import publish_events_ndjson
import asyncio
import json
from .metadata import load_metadata, load_title_mapping


def _cmd_init_metadata(args: argparse.Namespace) -> int:
    cfg = load_config()
    src_path = Path(args.input)
    if not src_path.exists():
        print(f"Input not found: {src_path}", file=sys.stderr)
        return 1
    # very naive title inference from filename
    inferred_title = src_path.parent.name.replace("-", " ").title()
    draft = draft_metadata_from_document(
        inferred_title=inferred_title,
        inferred_author=None,
        inferred_language="en",
        has_collection=bool(args.has_collection),
        book_titles=None,
    )
    out_yaml = src_path.parent / "@metadata.yml"
    write_metadata_yaml(str(out_yaml), draft)
    print(f"Wrote metadata draft: {out_yaml}")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    cfg = load_config(source_type=args.source_type)
    layout = Layout(cfg.out_dir)
    layout.ensure()
    src = Path(args.input)
    if not src.exists():
        print(f"Input not found: {src}", file=sys.stderr)
        return 1
    if cfg.source_type == "HTML":
        adoc = html_to_adoc(src.read_bytes())
    elif cfg.source_type == "ADOC":
        adoc = normalize_adoc(src.read_text(encoding="utf-8"))
    else:
        print(f"Unsupported source type for generate: {cfg.source_type}", file=sys.stderr)
        return 2
    # store a single normalized AsciiDoc as proof of pipeline
    out_file = layout.adoc_dir / "normalized-publication.adoc"
    out_file.write_text(adoc, encoding="utf-8")
    print(f"Generated AsciiDoc: {out_file}")
    # Load metadata if present
    base_dir = Path(args.input).parent
    md = load_metadata(base_dir)
    has_collection = bool(args.has_collection) if hasattr(args, "has_collection") and args.has_collection else (md.has_collection if md else True)
    language = (md.language if md and md.language else "en")
    collection_id = md.collection_id if md and md.collection_id else base_dir.name
    # Parse collection structure
    tree = parse_adoc_structure(adoc, has_collection=has_collection)
    # Serialize bookstr events
    title_map = load_title_mapping(base_dir, md)
    use_bookstr = md.use_bookstr if md else True
    events = serialize_bookstr(
        tree,
        collection_id=collection_id,
        language=language,
        use_bookstr=use_bookstr,
        book_title_map=title_map,
    )
    # Write events to NDJSON
    events_path = layout.events_dir / "events.ndjson"
    with events_path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(e.to_json())
            f.write("\n")
    print(f"Wrote events: {events_path}")
    # Write simple cache index for determinism/resume
    idx_path = layout.cache_dir / "event_index.json"
    d_list = []
    for e in events:
        d = None
        for tag in e.tags:
            if tag and tag[0] == "d":
                d = tag[1]
                break
        if d:
            d_list.append(d)
    with idx_path.open("w", encoding="utf-8") as f:
        json.dump({"count": len(d_list), "d": d_list}, f, ensure_ascii=False, indent=2)
    print(f"Wrote cache index: {idx_path}")
    return 0


def _cmd_publish(args: argparse.Namespace) -> int:
    cfg = load_config()
    layout = Layout(cfg.out_dir)
    events_path = layout.events_dir / "events.ndjson"
    if not events_path.exists():
        print(f"No events found at {events_path}", file=sys.stderr)
        return 1
    asyncio.run(
        publish_events_ndjson(
            cfg.relay_url,
            cfg.secret_key_hex,
            str(events_path),
            max_in_flight=cfg.max_batch,
        )
    )
    print(f"Published events to {cfg.relay_url}")
    return 0*** End Patch*** }```">


def _cmd_qc(args: argparse.Namespace) -> int:
    # Placeholder: will implement QC in later steps
    cfg = load_config()
    print(f"Will QC events on {cfg.relay_url}")
    return 0


def _cmd_all(args: argparse.Namespace) -> int:
    e1 = _cmd_generate(args)
    if e1 != 0:
        return e1
    e2 = _cmd_publish(args)
    if e2 != 0:
        return e2
    e3 = _cmd_qc(args)
    return e3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="publisher", description="Nostr Bookstr Publisher")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--input", required=True, help="Path to input source file (e.g., publication.html)")
    common.add_argument("--source-type", default="HTML", help="HTML|ADOC|MARKDOWN|RTF|EPUB")

    sp = sub.add_parser("init-metadata", parents=[common], help="Generate @metadata.yml from source")
    sp.add_argument("--has-collection", action="store_true", help="Indicate the source has a collection level")
    sp.set_defaults(func=_cmd_init_metadata)

    sp = sub.add_parser("generate", parents=[common], help="Generate events without publishing")
    sp.add_argument("--has-collection", action="store_true", help="Indicate the source has a collection level")
    sp.set_defaults(func=_cmd_generate)

    sp = sub.add_parser("publish", help="Publish events to relay")
    sp.set_defaults(func=_cmd_publish)

    sp = sub.add_parser("qc", help="Quality control: verify and republish missing")
    sp.set_defaults(func=_cmd_qc)

    sp = sub.add_parser("all", parents=[common], help="Run generate→publish→qc")
    sp.set_defaults(func=_cmd_all)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())


