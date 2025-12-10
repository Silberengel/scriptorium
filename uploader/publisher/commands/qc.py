"""
QC (Quality Control) command handler - checks events on relay.
"""
import asyncio
import sys

from ..config import load_config
from ..io_layout import Layout
from ..nostr_client import qc_check_events


def cmd_qc(args) -> int:
    """Check events on relay for quality control."""
    cfg = load_config()
    layout = Layout(cfg.out_dir)
    events_path = layout.events_dir / "events.ndjson"
    if not events_path.exists():
        print(f"No events found at {events_path}", file=sys.stderr)
        return 1
    
    republish = getattr(args, "republish", False)
    
    result = asyncio.run(
        qc_check_events(
            cfg.relay_url,
            cfg.secret_key_hex,
            str(events_path),
            republish_missing=republish,
        )
    )
    
    # Print results
    print(f"\nQC Results:")
    print(f"  Total events: {result['total']}")
    print(f"  Found on relay: {result['found']}")
    if 'found_by_id' in result:
        print(f"    - Found by exact event ID (latest version): {result['found_by_id']}")
        print(f"    - Found by d-tag (any version): {result['found_by_d_tag']}")
    print(f"  Missing (latest version not found): {result['missing']}")
    
    if result['errors']:
        print(f"\n  Errors ({len(result['errors'])}):")
        for err in result['errors'][:10]:
            print(f"    - {err}")
        if len(result['errors']) > 10:
            print(f"    ... and {len(result['errors']) - 10} more")
    
    if result['missing'] > 0:
        print(f"\n  Missing events (first 10):")
        for i, event_data in enumerate(result['missing_events'][:10]):
            d_tag = None
            for tag in event_data.get("tags", []):
                if tag and len(tag) > 0 and tag[0] == "d":
                    d_tag = tag[1] if len(tag) > 1 else None
                    break
            kind = event_data.get("kind", "?")
            print(f"    {i+1}. kind={kind}, d={d_tag}")
        if len(result['missing_events']) > 10:
            print(f"    ... and {len(result['missing_events']) - 10} more")
        
        if not republish:
            print(f"\n  To republish missing events, run:")
            print(f"    python -m uploader.publisher.cli qc --republish")
    
    if result['missing'] == 0 and not result['errors']:
        print(f"\n✓ All events are present on the relay!")
        return 0
    elif result['missing'] > 0:
        return 1
    else:
        return 0

