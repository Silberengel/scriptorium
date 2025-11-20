#!/usr/bin/env python3
"""
Broadcast an entire publication to a relay.

Usage:
    python -m uploader.publisher.scripts.broadcast_publication <nevent> <relay_url> [--key SCRIPTORIUM_KEY]

The script will:
1. Resolve the nevent to get the top-level 30040 event
2. Recursively fetch all child events via a-tags
3. Publish all events to the specified relay
"""

import asyncio
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Set, Any, Optional
import websockets

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from uploader.publisher.nostr_client import (
    _derive_pubkey,
    _sign_event,
    _compute_event_id,
    query_events_from_relay,
)
from uploader.publisher.util import normalize_secret_key_to_hex

try:
    from bech32 import bech32_decode, convertbits
except ImportError:
    print("ERROR: bech32 library not found. Install with: pip install bech32")
    sys.exit(1)


def decode_nevent(nevent: str) -> Dict[str, Any]:
    """
    Decode a nevent (bech32 encoded event reference).
    Returns dict with: event_id, relay_hint, author_hint
    """
    if not nevent.startswith("nevent1"):
        raise ValueError(f"Invalid nevent format: {nevent}")
    
    # Decode bech32
    hrp, data = bech32_decode(nevent)
    if hrp != "nevent":
        raise ValueError(f"Invalid nevent HRP: {hrp}")
    
    # Convert from 5-bit to 8-bit
    decoded = convertbits(data, 5, 8, False)
    if decoded is None:
        raise ValueError("Failed to decode bech32 data")
    
    # Parse TLV format
    result = {}
    i = 0
    while i < len(decoded):
        if i + 1 >= len(decoded):
            break
        t = decoded[i]
        l = decoded[i + 1]
        if i + 2 + l > len(decoded):
            break
        v = decoded[i + 2:i + 2 + l]
        
        if t == 0:  # event ID (32 bytes)
            result["event_id"] = bytes(v).hex()
        elif t == 1:  # relay hint (string)
            result["relay_hint"] = bytes(v).decode('utf-8')
        elif t == 2:  # author hint (32 bytes)
            result["author_hint"] = bytes(v).hex()
        
        i += 2 + l
    
    if "event_id" not in result:
        raise ValueError("nevent missing event ID")
    
    return result


async def fetch_event_by_id(relay_url: str, event_id: str, author_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch an event by its ID from a relay."""
    filters = [{"ids": [event_id]}]
    if author_hint:
        filters[0]["authors"] = [author_hint]
    
    events = await query_events_from_relay(relay_url, author_hint or "", filters, timeout=30.0)
    if events:
        return events[0]
    return None


def parse_a_tag(a_tag_value: str) -> Dict[str, str]:
    """
    Parse an a-tag value: "<kind>:<pubkey>:<d-tag>"
    Returns dict with: kind, pubkey, d_tag
    """
    parts = a_tag_value.split(":", 2)
    if len(parts) != 3:
        raise ValueError(f"Invalid a-tag format: {a_tag_value}")
    
    return {
        "kind": int(parts[0]),
        "pubkey": parts[1],
        "d_tag": parts[2],
    }


async def fetch_all_events_recursive(
    relay_url: str,
    root_event: Dict[str, Any],
    collected: Set[str],
    errors: List[str],
) -> List[Dict[str, Any]]:
    """
    Recursively fetch all events in a publication tree.
    
    Args:
        relay_url: Relay URL to query
        root_event: The root event to start from
        collected: Set of event IDs already collected (to avoid duplicates)
        errors: List to append errors to
    
    Returns:
        List of all events in the publication tree
    """
    all_events = []
    event_id = root_event.get("id")
    pubkey = root_event.get("pubkey")
    
    if event_id in collected:
        return all_events
    
    collected.add(event_id)
    all_events.append(root_event)
    
    # Extract a-tags from root event
    a_tags = []
    for tag in root_event.get("tags", []):
        if tag and len(tag) > 0 and tag[0] == "a":
            a_value = tag[1] if len(tag) > 1 else ""
            if a_value:
                a_tags.append(a_value)
    
    # Also check for e-tags (event references)
    e_tags = []
    for tag in root_event.get("tags", []):
        if tag and len(tag) > 0 and tag[0] == "e":
            e_value = tag[1] if len(tag) > 1 else ""
            if e_value:
                e_tags.append(e_value)
    
    # Fetch child events via a-tags
    for a_tag_value in a_tags:
        try:
            parsed = parse_a_tag(a_tag_value)
            child_kind = parsed["kind"]
            child_pubkey = parsed["pubkey"]
            child_d_tag = parsed["d_tag"]
            
            # Query for child event
            filters = [{
                "authors": [child_pubkey],
                "kinds": [child_kind],
                "#d": [child_d_tag],
            }]
            
            child_events = await query_events_from_relay(relay_url, child_pubkey, filters, timeout=30.0)
            
            if child_events:
                # Take the latest event (highest created_at)
                child_event = max(child_events, key=lambda e: e.get("created_at", 0))
                
                # Recursively fetch children of this event
                child_tree = await fetch_all_events_recursive(
                    relay_url,
                    child_event,
                    collected,
                    errors,
                )
                all_events.extend(child_tree)
            else:
                errors.append(f"Child event not found: {a_tag_value}")
        except Exception as e:
            errors.append(f"Error fetching child event {a_tag_value}: {e}")
    
    # Also fetch events referenced by e-tags
    for e_tag_value in e_tags:
        if e_tag_value in collected:
            continue
        
        try:
            child_event = await fetch_event_by_id(relay_url, e_tag_value, pubkey)
            if child_event:
                child_tree = await fetch_all_events_recursive(
                    relay_url,
                    child_event,
                    collected,
                    errors,
                )
                all_events.extend(child_tree)
            else:
                errors.append(f"Event not found by e-tag: {e_tag_value}")
        except Exception as e:
            errors.append(f"Error fetching event by e-tag {e_tag_value}: {e}")
    
    return all_events


async def publish_events_to_relay(
    relay_url: str,
    secret_key_hex: str,
    events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Publish events to a relay."""
    priv_hex = normalize_secret_key_to_hex(secret_key_hex)
    pub_hex = _derive_pubkey(priv_hex)
    
    # Prepare events (update created_at, compute IDs, sign)
    current_time = int(time.time())
    prepared_events = []
    
    for event_json in events:
        # Update created_at to current time
        event_json["created_at"] = current_time
        event_json["pubkey"] = pub_hex
        
        # Compute ID and sign
        event_id = _compute_event_id(event_json)
        event_json["id"] = event_id
        event_json["sig"] = _sign_event(event_json, priv_hex)
        
        prepared_events.append(event_json)
    
    # Publish events
    published_count = 0
    errors = []
    
    try:
        async with websockets.connect(relay_url) as ws:
            print(f"Connected to {relay_url}")
            
            # Publish all events
            for idx, event_json in enumerate(prepared_events):
                try:
                    await ws.send(json.dumps(["EVENT", event_json]))
                    published_count += 1
                    
                    if (idx + 1) % 100 == 0:
                        print(f"Published {idx + 1}/{len(prepared_events)} events...")
                    
                    # Small delay to avoid overwhelming relay
                    if (idx + 1) % 50 == 0:
                        await asyncio.sleep(0.1)
                        
                except Exception as e:
                    errors.append(f"Error publishing event {idx}: {e}")
            
            # Wait a bit for responses
            await asyncio.sleep(2)
            
    except Exception as e:
        errors.append(f"Connection error: {e}")
    
    return {
        "published": published_count,
        "total": len(prepared_events),
        "errors": errors,
    }


async def main():
    parser = argparse.ArgumentParser(
        description="Broadcast an entire publication to a relay",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m uploader.publisher.scripts.broadcast_publication \\
    nevent1qqs... wss://relay.example.com
  
  python -m uploader.publisher.scripts.broadcast_publication \\
    nevent1qqs... ws://localhost:8080 \\
    --key nsec1...
        """
    )
    parser.add_argument("nevent", help="nevent of the top-level 30040 event")
    parser.add_argument("relay_url", help="Relay URL (ws:// or wss://)")
    parser.add_argument(
        "--key",
        default=None,
        help="Secret key (nsec or hex). Defaults to SCRIPTORIUM_KEY env var.",
    )
    
    args = parser.parse_args()
    
    # Get secret key
    secret_key = args.key or os.getenv("SCRIPTORIUM_KEY")
    if not secret_key:
        print("ERROR: Secret key required. Set SCRIPTORIUM_KEY env var or use --key")
        sys.exit(1)
    
    # Decode nevent
    print(f"Decoding nevent: {args.nevent[:20]}...")
    try:
        nevent_data = decode_nevent(args.nevent)
        event_id = nevent_data["event_id"]
        relay_hint = nevent_data.get("relay_hint")
        author_hint = nevent_data.get("author_hint")
    except Exception as e:
        print(f"ERROR: Failed to decode nevent: {e}")
        sys.exit(1)
    
    print(f"Event ID: {event_id}")
    if relay_hint:
        print(f"Relay hint: {relay_hint}")
    if author_hint:
        print(f"Author hint: {author_hint[:16]}...")
    
    # Use relay hint if available, otherwise use provided relay
    query_relay = relay_hint or args.relay_url
    
    # Fetch root event
    print(f"\nFetching root event from {query_relay}...")
    root_event = await fetch_event_by_id(query_relay, event_id, author_hint)
    
    if not root_event:
        print(f"ERROR: Root event not found on relay {query_relay}")
        sys.exit(1)
    
    print(f"✓ Found root event: kind={root_event.get('kind')}, d={root_event.get('tags', [])}")
    
    # Recursively fetch all events
    print(f"\nFetching all child events recursively...")
    collected = set()
    errors = []
    all_events = await fetch_all_events_recursive(
        query_relay,
        root_event,
        collected,
        errors,
    )
    
    print(f"✓ Collected {len(all_events)} events")
    if errors:
        print(f"⚠ {len(errors)} errors occurred while fetching:")
        for err in errors[:10]:
            print(f"  - {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
    
    # Publish all events to target relay
    print(f"\nPublishing {len(all_events)} events to {args.relay_url}...")
    result = await publish_events_to_relay(
        args.relay_url,
        secret_key,
        all_events,
    )
    
    print(f"\n✓ Published {result['published']}/{result['total']} events")
    if result['errors']:
        print(f"⚠ {len(result['errors'])} errors occurred:")
        for err in result['errors'][:10]:
            print(f"  - {err}")
        if len(result['errors']) > 10:
            print(f"  ... and {len(result['errors']) - 10} more")


if __name__ == "__main__":
    asyncio.run(main())

