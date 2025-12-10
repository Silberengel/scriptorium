"""
Publish command handler - publishes events to Nostr relay.
"""
import asyncio
import sys

from ..config import load_config
from ..io_layout import Layout
from ..nostr_client import publish_events_ndjson


def cmd_publish(args) -> int:
    """Publish events to Nostr relay."""
    cfg = load_config()
    layout = Layout(cfg.out_dir)
    events_path = layout.events_dir / "events.ndjson"
    if not events_path.exists():
        print(f"No events found at {events_path}", file=sys.stderr)
        return 1
    try:
        verification = asyncio.run(
            publish_events_ndjson(
                cfg.relay_url,
                cfg.secret_key_hex,
                str(events_path),
                max_in_flight=cfg.max_batch,
            )
        )
        if verification and verification.get("interrupted"):
            # Already handled in the function
            return 130  # Standard exit code for Ctrl+C
        elif verification and verification.get("verified"):
            print(f"✓ Published and verified events on {cfg.relay_url}")
            return 0
        else:
            # Check if publish succeeded even if verification failed
            publish_succeeded = verification.get("publish_succeeded", False) if verification else False
            published_count = verification.get("published_count", 0) if verification else 0
            error_msg = verification.get("error", "Unknown error") if verification else "No verification performed"
            
            if publish_succeeded and published_count > 0:
                # Events were published successfully, verification just failed
                print(f"✓ Published {published_count} events to {cfg.relay_url} (verification failed: {error_msg})")
                return 0
            else:
                # Actual publish failure
                print(f"Failed to publish events to {cfg.relay_url}: {error_msg}", file=sys.stderr)
                return 1
    except KeyboardInterrupt:
        # Fallback in case KeyboardInterrupt escapes the async function
        print(f"\n\n⚠ Publishing interrupted by user.", file=sys.stderr)
        return 130  # Standard exit code for Ctrl+C

