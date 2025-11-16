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
import asyncio
import json
from .metadata import load_metadata, load_title_mapping
from .util import to_ascii_text, strip_invisible_text, unwrap_hard_wraps, ensure_blank_before_headings, ensure_blank_before_attributes, remove_discrete_attributes, ensure_blank_between_paragraphs
from .text_structure import promote_headings


class HelpOnErrorArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print("", file=sys.stderr)
        self.print_usage(sys.stderr)
        self.exit(2, f"\nerror: {message}\n\nUse -h or --help for detailed usage.\n\n")
    def print_help(self, file=None):
        if file is None:
            file = sys.stdout
        print("", file=file)
        super().print_help(file)
        print("", file=file)

class RichHelpFormatter(argparse.RawDescriptionHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass

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
    # Promote structural headings if patterns provided or preset requested
    if getattr(args, "promote_default_structure", False) or getattr(args, "chapter_pattern", None) or getattr(args, "section_pattern", None) or getattr(args, "verse_pattern", None):
        chapter_pat = args.chapter_pattern if getattr(args, "chapter_pattern", None) else r"^[A-Za-z][^\n]*\sChapter\s+\d+\.*$"
        # prefer section_pattern, fallback to legacy verse_pattern, then default (allow trailing period optional)
        section_pat = (
            args.section_pattern
            if getattr(args, "section_pattern", None)
            else (args.verse_pattern if getattr(args, "verse_pattern", None) else r"^\d+:\d+\.?$")
        )
        # If using default structure promotion and user didn't explicitly choose levels,
        # use chapter=3, section=4 to match pattern document.
        chapter_level = getattr(args, "chapter_level", 3 if getattr(args, "promote_default_structure", False) else 4)
        section_level = getattr(args, "section_level", 4 if getattr(args, "promote_default_structure", False) else 5)
        adoc = promote_headings(
            adoc,
            chapter_regex=chapter_pat,
            section_regex=section_pat,
            chapter_level=chapter_level,
            section_level=section_level,
            insert_preamble=not getattr(args, "no_preamble", False),
        )
    # Additional sanitation options
    if hasattr(args, "ascii_only") and args.ascii_only:
        adoc = to_ascii_text(adoc)
    else:
        adoc = strip_invisible_text(adoc)
    if hasattr(args, "unwrap_lines") and args.unwrap_lines:
        adoc = unwrap_hard_wraps(adoc, min_level=getattr(args, "unwrap_level", 4))
    # Remove [discrete] blocks entirely
    adoc = remove_discrete_attributes(adoc)
    # Final formatting: ensure blank before attribute blocks, then headings (noop if none)
    adoc = ensure_blank_before_attributes(adoc)
    adoc = ensure_blank_before_headings(adoc)
    # Enforce paragraph separation at the very end
    adoc = ensure_blank_between_paragraphs(adoc)
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
    # Lazy import to avoid requiring monstr for generate-only runs
    from .nostr_client import publish_events_ndjson
    asyncio.run(
        publish_events_ndjson(
            cfg.relay_url,
            cfg.secret_key_hex,
            str(events_path),
            max_in_flight=cfg.max_batch,
        )
    )
    print(f"Published events to {cfg.relay_url}")
    return 0


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
    epilog = (
        "Examples:\n"
        "  publisher init-metadata \\\n"
        "    --input uploader/input_data/DRM-Bible/publication.html \\\n"
        "    --has-collection\n"
        "\n"
        "  publisher generate \\\n"
        "    --input uploader/input_data/DRM-Bible/publication.html \\\n"
        "    --source-type HTML\n"
        "\n"
        "  publisher publish\n"
        "  publisher qc\n"
        "\n"
        "  publisher all \\\n"
        "    --input uploader/input_data/DRM-Bible/publication.html \\\n"
        "    --source-type HTML\n"
        "\n"
        "Environment:\n"
        "  SCRIPTORIUM_KEY    nsec... or 64-hex (lowercased automatically)\n"
        "  SCRIPTORIUM_RELAY  Relay URL (default wss://thecitadel.nostr1.com)\n"
        "  SCRIPTORIUM_SOURCE Source type default (HTML)\n"
        "  SCRIPTORIUM_OUT    Output dir (default uploader/publisher/out)\n"
    )
    welcome = (
        "Welcome to the Scriptorium Uploader (Nostr bookstr)\n"
        "----------------------------------------------------\n"
        "Convert sources to AsciiDoc, scaffold metadata, generate hierarchical bookstr events,\n"
        "publish to your relay, and verify via QC.\n"
    )
    p = HelpOnErrorArgumentParser(
        prog="publisher",
        description=f"{welcome}",
        epilog=epilog,
        formatter_class=RichHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # Add extra help aliases for convenience
    p.add_argument("-help", "--h", action="help", help="Show this help message and exit")

    common = argparse.ArgumentParser(add_help=False, formatter_class=RichHelpFormatter)
    common.add_argument(
        "--input",
        required=True,
        help="Path to input source file (e.g., publication.html or publication.adoc)",
        metavar="PATH",
    )
    common.add_argument(
        "--source-type",
        default="HTML",
        help="Source type: HTML | ADOC | MARKDOWN | RTF | EPUB (HTML/ADOC implemented)",
        choices=["HTML", "ADOC", "MARKDOWN", "RTF", "EPUB"],
    )

    sp = sub.add_parser(
        "init-metadata",
        parents=[common],
        help="Generate @metadata.yml from the source without publishing",
        description="Infer a starter @metadata.yml (title/author/language, collection flags). You can edit it before generation.",
        formatter_class=RichHelpFormatter,
    )
    sp.add_argument("--has-collection", action="store_true", help="Indicate the source has a collection (top-level) index")
    sp.set_defaults(func=_cmd_init_metadata)

    sp = sub.add_parser(
        "generate",
        parents=[common],
        help="Normalize to AsciiDoc, parse structure, and write serialized events (no publish)",
        description=(
            "Convert source to normalized AsciiDoc, parse Collection→Book→Chapter→Section, and write NDJSON events.\n"
            "\n"
            "Sanitization options:\n"
            "  --ascii-only     Transliterate to plain ASCII and drop non-ASCII\n"
            "  --unwrap-lines   Merge hard-wrapped lines within paragraphs (inside level N and deeper)\n"
            "  --unwrap-level N Specify heading level threshold for unwrapping (default: 4)\n"
            "\n"
            "Structure promotion:\n"
            "  --promote-default-structure        Promote 'X Chapter N' to level-4 and 'N:N.' to level-5 headings\n"
            "  --chapter-pattern REGEX            Custom regex to detect chapter lines\n"
            "  --section-pattern REGEX            Custom regex to detect section lines\n"
            "  --chapter-level N                  Heading level for chapter matches (default: 4)\n"
            "  --section-level N                  Heading level for section matches (default: 5)\n"
            "  --no-preamble                      Do not insert a 'Preamble' under chapters\n"
        ),
        formatter_class=RichHelpFormatter,
    )
    sp.add_argument("--has-collection", action="store_true", help="Indicate the source has a collection (top-level) index")
    sp.add_argument("--ascii-only", action="store_true", help="Transliterate output to plain ASCII and drop non-ASCII characters")
    sp.add_argument("--unwrap-lines", action="store_true", help="Merge hard-wrapped lines within paragraphs into single lines")
    sp.add_argument(
        "--unwrap-level",
        type=int,
        default=4,
        metavar="N",
        help="Only unwrap inside sections at heading level N and deeper (default: 4)",
    )
    # Structural promotion options
    sp.add_argument("--promote-default-structure", action="store_true", help="Promote 'X Chapter N' to level-4 and 'N:N.' to level-5 headings, with preamble insertion")
    sp.add_argument("--chapter-pattern", help="Regex to detect chapter lines to promote (overrides default)")
    sp.add_argument("--section-pattern", help="Regex to detect section lines to promote (overrides default)")
    # legacy aliases (hidden)
    sp.add_argument("--verse-pattern", help=argparse.SUPPRESS)
    sp.add_argument("--chapter-level", type=int, default=4, help="Heading level to assign for chapter matches")
    sp.add_argument("--section-level", type=int, default=5, help="Heading level to assign for section matches")
    # legacy alias (hidden)
    sp.add_argument("--verse-level", type=int, help=argparse.SUPPRESS)
    sp.add_argument("--no-preamble", action="store_true", help="Do not auto-insert a Preamble heading after chapter lines")
    sp.set_defaults(func=_cmd_generate)

    sp = sub.add_parser(
        "publish",
        help="Publish events to the configured relay",
        description="Publish previously generated events (NDJSON) to the relay using SCRIPTORIUM_KEY.",
        formatter_class=RichHelpFormatter,
    )
    sp.set_defaults(func=_cmd_publish)

    sp = sub.add_parser(
        "qc",
        help="Quality control: verify presence on relay and republish missing",
        description="Read back events by kind+d+author and republish any missing or mismatched content.",
        formatter_class=RichHelpFormatter,
    )
    sp.set_defaults(func=_cmd_qc)

    sp = sub.add_parser(
        "all",
        parents=[common],
        help="Run generate → publish → qc in sequence",
        description="One-swoop mode: generate events from source, publish them, and run QC.",
        formatter_class=RichHelpFormatter,
    )
    sp.set_defaults(func=_cmd_all)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    # Show help when no args supplied
    if not argv:
        print("", file=sys.stderr)
        parser.print_help(sys.stderr)
        print("", file=sys.stderr)
        return 2
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())


