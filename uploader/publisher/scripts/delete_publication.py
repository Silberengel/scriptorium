#!/usr/bin/env python3
"""
Delete an entire publication from a relay.

Usage:
    python -m uploader.publisher.scripts.delete_publication <event_ref> <relay_url> [--key SCRIPTORIUM_KEY]

    event_ref can be:
    - nevent (bech32 encoded event reference)
    - naddr (bech32 encoded address: kind:pubkey:d-tag)
    - hex event ID (64 hex characters)

The script will:
1. Resolve the event reference to get the top-level 30040 event
2. Recursively fetch all child events via a-tags
3. Create deletion events (kind 5) for all events
4. Publish deletion events to the specified relay
"""

import asyncio
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Set, Any, Optional, Callable
import websockets

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

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


def decode_naddr(naddr: str) -> Dict[str, Any]:
    """
    Decode an naddr (bech32 encoded address: kind:pubkey:d-tag).
    Returns dict with: kind, pubkey, d_tag, relay_hint
    """
    if not naddr.startswith("naddr1"):
        raise ValueError(f"Invalid naddr format: {naddr}")
    
    # Decode bech32
    hrp, data = bech32_decode(naddr)
    if hrp != "naddr":
        raise ValueError(f"Invalid naddr HRP: {hrp}")
    
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
        
        if t == 0:  # kind (varint, but we'll read as bytes and convert)
            # Kind is stored as a varint, but for simplicity, read as little-endian uint32
            kind_bytes = bytes(v)
            if len(kind_bytes) <= 4:
                kind = int.from_bytes(kind_bytes, byteorder='little')
                result["kind"] = kind
        elif t == 1:  # pubkey (32 bytes)
            result["pubkey"] = bytes(v).hex()
        elif t == 2:  # d-tag (string)
            result["d_tag"] = bytes(v).decode('utf-8')
        elif t == 3:  # relay hint (string)
            result["relay_hint"] = bytes(v).decode('utf-8')
        
        i += 2 + l
    
    if "kind" not in result or "pubkey" not in result or "d_tag" not in result:
        raise ValueError("naddr missing required fields (kind, pubkey, d_tag)")
    
    return result


def parse_event_reference(ref: str) -> Dict[str, Any]:
    """
    Parse an event reference in any format: nevent, naddr, or hex event ID.
    Returns dict with: event_id, relay_hint, author_hint (for nevent/hex)
                      or kind, pubkey, d_tag, relay_hint (for naddr)
    """
    ref = ref.strip()
    
    # Check if it's a hex event ID (64 hex characters)
    if len(ref) == 64 and all(c in '0123456789abcdefABCDEF' for c in ref):
        return {
            "event_id": ref.lower(),
            "relay_hint": None,
            "author_hint": None,
        }
    
    # Check if it's a nevent
    if ref.startswith("nevent1"):
        return decode_nevent(ref)
    
    # Check if it's an naddr
    if ref.startswith("naddr1"):
        return decode_naddr(ref)
    
    raise ValueError(f"Invalid event reference format. Expected nevent, naddr, or 64-char hex ID, got: {ref[:20]}...")


async def fetch_event_by_id(relay_url: str, event_id: str, author_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch an event by its ID from a relay."""
    filters = [{"ids": [event_id]}]
    if author_hint:
        filters[0]["authors"] = [author_hint]
    
    events = await query_events_from_relay(relay_url, author_hint or "", filters, timeout=30.0)
    if events:
        return events[0]
    return None


async def fetch_event_by_naddr(relay_url: str, kind: int, pubkey: str, d_tag: str) -> Optional[Dict[str, Any]]:
    """Fetch an event by naddr (kind:pubkey:d-tag) from a relay."""
    filters = [{
        "kinds": [kind],
        "authors": [pubkey],
        "#d": [d_tag],
    }]
    
    events = await query_events_from_relay(relay_url, pubkey, filters, timeout=30.0)
    if events:
        # Return the latest event (highest created_at)
        return max(events, key=lambda e: e.get("created_at", 0))
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
    progress_callback: Optional[Callable[[str], None]] = None,
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
    
    if progress_callback:
        progress_callback(f"Fetched event {len(collected)}: {event_id[:16]}...")
    
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
                    progress_callback,
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
                    progress_callback,
                )
                all_events.extend(child_tree)
            else:
                errors.append(f"Event not found by e-tag: {e_tag_value}")
        except Exception as e:
            errors.append(f"Error fetching event by e-tag {e_tag_value}: {e}")
    
    return all_events


async def create_and_publish_deletions(
    relay_url: str,
    secret_key_hex: str,
    events_to_delete: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Create deletion events (kind 5) and publish them to a relay."""
    priv_hex = normalize_secret_key_to_hex(secret_key_hex)
    pub_hex = _derive_pubkey(priv_hex)
    
    # Create deletion events (kind 5)
    # Format: ["e", "<event_id_to_delete>"]
    current_time = int(time.time())
    deletion_events = []
    
    print(f"Creating {len(events_to_delete)} deletion events...")
    if HAS_TQDM:
        pbar = tqdm(total=len(events_to_delete), desc="Creating deletions", unit="events")
    else:
        pbar = None
    
    for idx, event_to_delete in enumerate(events_to_delete):
        event_id_to_delete = event_to_delete.get("id")
        if not event_id_to_delete:
            continue
        
        # Create deletion event
        deletion_event = {
            "pubkey": pub_hex,
            "created_at": current_time,
            "kind": 5,  # Deletion event
            "tags": [["e", event_id_to_delete]],
            "content": "",
        }
        
        # Compute ID and sign
        event_id = _compute_event_id(deletion_event)
        deletion_event["id"] = event_id
        deletion_event["sig"] = _sign_event(deletion_event, priv_hex)
        
        deletion_events.append(deletion_event)
        
        if pbar:
            pbar.update(1)
        elif (idx + 1) % 100 == 0:
            print(f"Created {idx + 1}/{len(events_to_delete)} deletion events...")
    
    if pbar:
        pbar.close()
    
    # Publish deletion events
    published_count = 0
    errors = []
    
    try:
        async with websockets.connect(relay_url) as ws:
            print(f"Connected to {relay_url}")
            print(f"Publishing {len(deletion_events)} deletion events...")
            
            # Create progress bar if tqdm is available
            if HAS_TQDM:
                pbar = tqdm(total=len(deletion_events), desc="Publishing deletions", unit="events")
            else:
                pbar = None
            
            # Publish all deletion events
            for idx, deletion_event in enumerate(deletion_events):
                try:
                    await ws.send(json.dumps(["EVENT", deletion_event]))
                    published_count += 1
                    
                    if pbar:
                        pbar.update(1)
                    elif (idx + 1) % 100 == 0:
                        print(f"Published {idx + 1}/{len(deletion_events)} deletion events...")
                    
                    # Small delay to avoid overwhelming relay
                    if (idx + 1) % 50 == 0:
                        await asyncio.sleep(0.1)
                        
                except Exception as e:
                    errors.append(f"Error publishing deletion event {idx}: {e}")
                    if pbar:
                        pbar.set_postfix_str(f"Errors: {len(errors)}")
            
            if pbar:
                pbar.close()
            
            # Wait a bit for responses
            await asyncio.sleep(2)
            
    except Exception as e:
        errors.append(f"Connection error: {e}")
    
    return {
        "published": published_count,
        "total": len(deletion_events),
        "errors": errors,
    }


async def main():
    parser = argparse.ArgumentParser(
        description="Delete an entire publication from a relay",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m uploader.publisher.scripts.delete_publication \\
    nevent1qqs... wss://relay.example.com
  
  python -m uploader.publisher.scripts.delete_publication \\
    naddr1qqs... ws://localhost:8080 \\
    --key nsec1...
  
  python -m uploader.publisher.scripts.delete_publication \\
    abc123...def456 wss://relay.example.com \\
    --key nsec1...
        """
    )
    parser.add_argument(
        "event_ref",
        help="Event reference: nevent, naddr, or 64-char hex event ID of the top-level 30040 event",
    )
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
    
    # Parse event reference (nevent, naddr, or hex)
    print(f"Parsing event reference: {args.event_ref[:20]}...")
    try:
        ref_data = parse_event_reference(args.event_ref)
    except Exception as e:
        print(f"ERROR: Failed to parse event reference: {e}")
        sys.exit(1)
    
    # Determine if it's an naddr or event ID
    if "kind" in ref_data and "pubkey" in ref_data and "d_tag" in ref_data:
        # It's an naddr
        kind = ref_data["kind"]
        pubkey = ref_data["pubkey"]
        d_tag = ref_data["d_tag"]
        relay_hint = ref_data.get("relay_hint")
        
        print(f"naddr: kind={kind}, pubkey={pubkey[:16]}..., d={d_tag}")
        if relay_hint:
            print(f"Relay hint: {relay_hint}")
        
        # Use relay hint if available, otherwise try thecitadel first, then provided relay
        if relay_hint:
            query_relay = relay_hint
        else:
            # No relay hint - try thecitadel first
            query_relay = "wss://thecitadel.nostr1.com"
        
        # Fetch root event by naddr
        print(f"\nFetching root event from {query_relay}...")
        root_event = await fetch_event_by_naddr(query_relay, kind, pubkey, d_tag)
        
        # If not found and we haven't tried the fallback relay, try it
        if not root_event:
            if relay_hint:
                # If we had a relay hint, try thecitadel as fallback
                if query_relay != "wss://thecitadel.nostr1.com":
                    print(f"Event not found on {query_relay}, trying fallback relay wss://thecitadel.nostr1.com...")
                    root_event = await fetch_event_by_naddr("wss://thecitadel.nostr1.com", kind, pubkey, d_tag)
                    if root_event:
                        query_relay = "wss://thecitadel.nostr1.com"
            else:
                # If no relay hint, we tried thecitadel first, now try the provided relay
                if args.relay_url != query_relay:
                    print(f"Event not found on {query_relay}, trying {args.relay_url}...")
                    root_event = await fetch_event_by_naddr(args.relay_url, kind, pubkey, d_tag)
                    if root_event:
                        query_relay = args.relay_url
        
        author_hint = pubkey
    else:
        # It's an nevent or hex event ID
        event_id = ref_data["event_id"]
        relay_hint = ref_data.get("relay_hint")
        author_hint = ref_data.get("author_hint")
        
        print(f"Event ID: {event_id}")
        if relay_hint:
            print(f"Relay hint: {relay_hint}")
        if author_hint:
            print(f"Author hint: {author_hint[:16]}...")
        
        # Use relay hint if available, otherwise try thecitadel first, then provided relay
        if relay_hint:
            query_relay = relay_hint
        else:
            # No relay hint - try thecitadel first
            query_relay = "wss://thecitadel.nostr1.com"
        
        # Fetch root event by ID
        print(f"\nFetching root event from {query_relay}...")
        root_event = await fetch_event_by_id(query_relay, event_id, author_hint)
        
        # If not found and we haven't tried the fallback relay, try it
        if not root_event:
            if relay_hint:
                # If we had a relay hint, try thecitadel as fallback
                if query_relay != "wss://thecitadel.nostr1.com":
                    print(f"Event not found on {query_relay}, trying fallback relay wss://thecitadel.nostr1.com...")
                    root_event = await fetch_event_by_id("wss://thecitadel.nostr1.com", event_id, author_hint)
                    if root_event:
                        query_relay = "wss://thecitadel.nostr1.com"
            else:
                # If no relay hint, we tried thecitadel first, now try the provided relay
                if args.relay_url != query_relay:
                    print(f"Event not found on {query_relay}, trying {args.relay_url}...")
                    root_event = await fetch_event_by_id(args.relay_url, event_id, author_hint)
                    if root_event:
                        query_relay = args.relay_url
    
    if not root_event:
        print(f"ERROR: Root event not found on any relay")
        sys.exit(1)
    
    print(f"✓ Found root event: kind={root_event.get('kind')}, d={root_event.get('tags', [])}")
    
    # Recursively fetch all events
    print(f"\nFetching all child events recursively...")
    collected = set()
    errors = []
    
    # Progress callback for fetching
    def progress_callback(msg: str):
        if not HAS_TQDM:
            print(f"  {msg}")
    
    all_events = await fetch_all_events_recursive(
        query_relay,
        root_event,
        collected,
        errors,
        progress_callback,
    )
    
    print(f"✓ Collected {len(all_events)} events to delete")
    if errors:
        print(f"⚠ {len(errors)} errors occurred while fetching:")
        for err in errors[:10]:
            print(f"  - {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
    
    # Confirm deletion
    print(f"\n⚠ WARNING: About to delete {len(all_events)} events from {args.relay_url}")
    response = input("Type 'DELETE' to confirm: ")
    if response != "DELETE":
        print("Cancelled.")
        sys.exit(0)
    
    # Create and publish deletion events
    print(f"\nCreating deletion events for {len(all_events)} events...")
    result = await create_and_publish_deletions(
        args.relay_url,
        secret_key,
        all_events,
    )
    
    print(f"\n✓ Published {result['published']}/{result['total']} deletion events")
    if result['errors']:
        print(f"⚠ {len(result['errors'])} errors occurred:")
        for err in result['errors'][:10]:
            print(f"  - {err}")
        if len(result['errors']) > 10:
            print(f"  ... and {len(result['errors']) - 10} more")


if __name__ == "__main__":
    asyncio.run(main())

