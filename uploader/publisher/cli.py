import argparse
import sys

from .commands import cmd_generate, cmd_init_metadata, cmd_publish, cmd_qc
from .config import load_config


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

def _cmd_all(args: argparse.Namespace) -> int:
    """Run generate → publish → qc in sequence."""
    e1 = cmd_generate(args)
    if e1 != 0:
        return e1
    e2 = cmd_publish(args)
    if e2 != 0:
        return e2
    e3 = cmd_qc(args)
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
        "Scripts:\n"
        "  read_publication <event_ref> <relay_url>\n"
        "    Read and display a publication from a relay (recursively fetches all events)\n"
        "    event_ref can be: nevent, naddr, or hex event ID\n"
        "\n"
        "  broadcast_publication <event_ref> <relay_url> [--key KEY]\n"
        "    Broadcast an entire publication to a relay (recursively fetches all events)\n"
        "    event_ref can be: nevent, naddr, or hex event ID\n"
        "\n"
        "  delete_publication <event_ref> <relay_url> [--key KEY]\n"
        "    Delete an entire publication from a relay (creates kind 5 deletion events)\n"
        "    event_ref can be: nevent, naddr, or hex event ID\n"
        "\n"
        "  All scripts support fallback to wss://thecitadel.nostr1.com if no relay hint\n"
        "  is provided or if the event is not found on the specified relay.\n"
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
    sp.set_defaults(func=cmd_init_metadata)

    sp = sub.add_parser(
        "generate",
        parents=[common],
        help="Normalize to AsciiDoc, parse structure, and write NKBIP-01 compliant events",
        description=(
            "Convert source to normalized AsciiDoc, parse Collection→Book→Chapter→Verse, and write NDJSON events.\n"
            "\n"
            "Events are generated with NKBIP-01 and NKBIP-08 compliant tags:\n"
            "\n"
            "  Collection root (kind 30040):\n"
            "    NKBIP-01: title, author, published_on, published_by, summary, type,\n"
            "              auto-update, source, image (if specified), p and E (for derivative works),\n"
            "              plus any additional_tags\n"
            "    NKBIP-08: C (collection), T (title), v (version if specified)\n"
            "\n"
            "  Book/Title events (kind 30040, T-level):\n"
            "    NKBIP-01: type, auto-update\n"
            "    NKBIP-08: C (collection), T (title/book), v (version if specified)\n"
            "    Note: T-level events only contain c-level (chapter) events. Any 30041 sections\n"
            "          directly under a T-level event are placed under a 'Preamble' 30040 chapter.\n"
            "\n"
            "  Chapter events (kind 30040, c-level):\n"
            "    NKBIP-01: type, auto-update\n"
            "    NKBIP-08: C (collection), T (title/book, inherited), c (chapter), v (version if specified)\n"
            "\n"
            "  Section/Verse content (kind 30041):\n"
            "    NKBIP-01: type\n"
            "    NKBIP-08: C (collection), T (title/book), c (chapter), s (section/verse), v (version if specified)\n"
            "\n"
            "  - Index events (kind 30040) get 'a' tags in format ['a', '<kind:pubkey:dtag>', '<relay hint>', '<event id>']\n"
            "    referencing child events (added during publishing)\n"
            "  - NKBIP-08 tags are hierarchical: each event includes tags from all higher levels\n"
            "  - All tag values are normalized using NIP-54 rules (lowercase, non-alphanumeric to hyphens)\n"
            "  - NKBIP-08 tags enable book wikilink resolution (e.g., [[book::bible | genesis 2:4 | kjv]])\n"
            "\n"
            "Metadata is loaded from @metadata.yml in the input directory. Set 'use_bookstr: true' and 'version'\n"
            "(e.g., 'DRB' for Douay-Rheims, 'KJV' for King James) to enable NKBIP-08 tags for searchability.\n"
            "The 'type' tag is a formatting hint for clients (default: 'book', can be 'bible', 'magazine', etc.).\n"
            "Additional NKBIP-01 tags can be specified via the 'additional_tags' field (e.g., ISBN, topics).\n"
            "\n"
            "Sanitization options:\n"
            "  --ascii-only     Transliterate to plain ASCII and drop non-ASCII\n"
            "  --unwrap-lines   Merge hard-wrapped lines within paragraphs (inside level N and deeper)\n"
            "  --unwrap-level N Specify heading level threshold for unwrapping (default: 4)\n"
            "\n"
            "Structure promotion:\n"
            "  --promote-default-structure        Promote 'X Chapter N' to level-4 and 'N:N.' to level-5 headings\n"
            "  --chapter-pattern REGEX            Custom regex to detect chapter lines\n"
            "  --verse-pattern REGEX              Custom regex to detect verse lines\n"
            "  --chapter-level N                  Heading level for chapter matches (default: 4)\n"
            "  --verse-level N                    Heading level for verse matches (default: 5)\n"
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
        help="Only unwrap inside verses at heading level N and deeper (default: 4)",
    )
    # Structural promotion options
    sp.add_argument("--promote-default-structure", action="store_true", help="Promote 'X Chapter N' to level-4 and 'N:N.' to level-5 headings, with preamble insertion")
    sp.add_argument("--chapter-pattern", help="Regex to detect chapter lines to promote (overrides default)")
    sp.add_argument("--verse-pattern", help="Regex to detect verse lines to promote (overrides default)")
    # legacy aliases (hidden)
    sp.add_argument("--section-pattern", help=argparse.SUPPRESS)
    sp.add_argument("--chapter-level", type=int, default=4, help="Heading level to assign for chapter matches")
    sp.add_argument("--verse-level", type=int, default=5, help="Heading level to assign for verse matches")
    # legacy alias (hidden)
    sp.add_argument("--section-level", type=int, help=argparse.SUPPRESS)
    sp.add_argument("--no-preamble", action="store_true", help="Do not auto-insert a Preamble heading after chapter lines")
    sp.set_defaults(func=cmd_generate)

    sp = sub.add_parser(
        "publish",
        help="Publish events to the configured relay with verification",
        description=(
            "Publish previously generated events (NDJSON) to the relay using SCRIPTORIUM_KEY.\n"
            "\n"
            "During publishing, 'a' tags are automatically added to kind 30040 index events\n"
            "to reference their child events (both 30040 and 30041).\n"
            "\n"
            "After publishing, verifies that the first event is present on the relay.\n"
            "Only reports success if verification passes.\n"
        ),
        formatter_class=RichHelpFormatter,
    )
    sp.set_defaults(func=cmd_publish)

    sp = sub.add_parser(
        "qc",
        help="Quality control: verify presence on relay and republish missing",
        description=(
            "Check which events from events.ndjson are present on the relay.\n"
            "\n"
            "Queries the relay for all events and compares with the generated events.\n"
            "Reports missing events and optionally republishes them.\n"
        ),
        formatter_class=RichHelpFormatter,
    )
    sp.add_argument(
        "--republish",
        action="store_true",
        help="Republish missing events to the relay",
    )
    sp.set_defaults(func=cmd_qc)

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


