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


async def fetch_all_events_breadth_first(
    relay_url: str,
    root_event: Dict[str, Any],
    collected: Set[str],
    errors: List[str],
    progress_callback: Optional[Callable[[int], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch all events in a publication tree using breadth-first batching.
    
    This is much faster than recursive depth-first because it batches queries:
    1. Start with root event
    2. Collect all a-tags from current level
    3. Batch query all those events at once
    4. Repeat for next level
    
    Args:
        relay_url: Relay URL to query
        root_event: The root event to start from
        collected: Set of event IDs already collected (to avoid duplicates)
        errors: List to append errors to
        progress_callback: Optional callback with current count (int)
    
    Returns:
        List of all events in the publication tree
    """
    all_events = []
    
    # Start with root event
    event_id = root_event.get("id")
    if event_id not in collected:
        collected.add(event_id)
        all_events.append(root_event)
        if progress_callback:
            progress_callback(len(collected))
    
    # Current level of events to process
    current_level = [root_event]
    
    # Process level by level (breadth-first)
    while current_level:
        # Collect all a-tags and e-tags from current level
        a_tags_to_fetch = {}  # Map a-tag value -> (kind, pubkey, d_tag)
        e_tags_to_fetch = set()  # Set of event IDs
        
        for event in current_level:
            pubkey = event.get("pubkey")
            
            # Extract a-tags
            for tag in event.get("tags", []):
                if tag and len(tag) > 0 and tag[0] == "a":
                    a_value = tag[1] if len(tag) > 1 else ""
                    if a_value and a_value not in a_tags_to_fetch:
                        try:
                            parsed = parse_a_tag(a_value)
                            a_tags_to_fetch[a_value] = (
                                parsed["kind"],
                                parsed["pubkey"],
                                parsed["d_tag"],
                            )
                        except Exception as e:
                            errors.append(f"Error parsing a-tag {a_value}: {e}")
            
            # Extract e-tags
            for tag in event.get("tags", []):
                if tag and len(tag) > 0 and tag[0] == "e":
                    e_value = tag[1] if len(tag) > 1 else ""
                    if e_value and e_value not in collected:
                        e_tags_to_fetch.add(e_value)
        
        # Batch fetch events by a-tags (group by pubkey and kind for efficient queries)
        a_tag_groups = {}  # (pubkey, kind) -> list of d_tags
        for a_value, (kind, pubkey, d_tag) in a_tags_to_fetch.items():
            key = (pubkey, kind)
            if key not in a_tag_groups:
                a_tag_groups[key] = []
            a_tag_groups[key].append((d_tag, a_value))
        
        # Fetch all a-tag events in batches
        next_level = []
        for (pubkey, kind), d_tag_list in a_tag_groups.items():
            # Create filter for all d-tags of this kind/pubkey
            d_tags = [d_tag for d_tag, _ in d_tag_list]
            filters = [{
                "authors": [pubkey],
                "kinds": [kind],
                "#d": d_tags,
            }]
            
            try:
                fetched_events = await query_events_from_relay(relay_url, pubkey, filters, timeout=60.0)
                
                # Map d-tags to events (take latest for each d-tag)
                d_tag_to_event = {}
                for event in fetched_events:
                    # Find d-tag in event
                    event_d_tag = None
                    for tag in event.get("tags", []):
                        if tag and len(tag) > 0 and tag[0] == "d":
                            event_d_tag = tag[1] if len(tag) > 1 else ""
                            break
                    
                    if event_d_tag and event_d_tag in d_tags:
                        # Keep the latest event for this d-tag
                        if event_d_tag not in d_tag_to_event:
                            d_tag_to_event[event_d_tag] = event
                        else:
                            existing = d_tag_to_event[event_d_tag]
                            if event.get("created_at", 0) > existing.get("created_at", 0):
                                d_tag_to_event[event_d_tag] = event
                
                # Add fetched events to next level
                for d_tag, a_value in d_tag_list:
                    if d_tag in d_tag_to_event:
                        event = d_tag_to_event[d_tag]
                        event_id = event.get("id")
                        if event_id not in collected:
                            collected.add(event_id)
                            all_events.append(event)
                            next_level.append(event)
                            if progress_callback:
                                progress_callback(len(collected))
                    else:
                        errors.append(f"Child event not found: {a_value}")
            except Exception as e:
                errors.append(f"Error batch fetching events for {pubkey}/{kind}: {e}")
        
        # Fetch events by e-tags (batch by IDs)
        if e_tags_to_fetch:
            # Batch fetch by event IDs
            event_ids = list(e_tags_to_fetch)
            # Split into chunks to avoid too large queries
            chunk_size = 100
            for i in range(0, len(event_ids), chunk_size):
                chunk = event_ids[i:i + chunk_size]
                filters = [{"ids": chunk}]
                
                try:
                    fetched_events = await query_events_from_relay(relay_url, root_event.get("pubkey", ""), filters, timeout=60.0)
                    
                    for event in fetched_events:
                        event_id = event.get("id")
                        if event_id not in collected:
                            collected.add(event_id)
                            all_events.append(event)
                            next_level.append(event)
                            if progress_callback:
                                progress_callback(len(collected))
                except Exception as e:
                    errors.append(f"Error batch fetching events by IDs: {e}")
        
        # Move to next level
        current_level = next_level
    
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
    if HAS_TQDM and sys.stdout.isatty():
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
        
        if pbar is not None:
            pbar.update(1)
        elif (idx + 1) % 100 == 0:
            print(f"Created {idx + 1}/{len(events_to_delete)} deletion events...")
    
    if pbar is not None:
        pbar.close()
    
    # Publish deletion events
    published_count = 0
    errors = []
    
    try:
        async with websockets.connect(relay_url) as ws:
            print(f"Connected to {relay_url}")
            print(f"Publishing {len(deletion_events)} deletion events...")
            
            # Create progress bar if tqdm is available and we're in a TTY
            if HAS_TQDM and sys.stdout.isatty():
                pbar = tqdm(total=len(deletion_events), desc="Publishing deletions", unit="events")
            else:
                pbar = None
            
            # Publish events in batches for better performance
            # Send multiple events quickly, then pause briefly
            batch_size = 100
            for batch_start in range(0, len(deletion_events), batch_size):
                batch_end = min(batch_start + batch_size, len(deletion_events))
                batch = deletion_events[batch_start:batch_end]
                
                # Send all events in this batch without waiting
                for idx, deletion_event in enumerate(batch):
                    try:
                        await ws.send(json.dumps(["EVENT", deletion_event]))
                        published_count += 1
                        
                        if pbar is not None:
                            pbar.update(1)
                    except Exception as e:
                        errors.append(f"Error publishing deletion event {batch_start + idx}: {e}")
                        if pbar is not None:
                            pbar.set_postfix_str(f"Errors: {len(errors)}")
                
                # Progress update for non-tqdm mode
                if pbar is None and batch_end % 500 == 0:
                    print(f"Published {batch_end}/{len(deletion_events)} deletion events...")
                
                # Small delay between batches to avoid overwhelming relay
                if batch_end < len(deletion_events):
                    await asyncio.sleep(0.1)
            
            if pbar is not None:
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
    parser.add_argument(
        "relay_url",
        nargs="?",
        default=None,
        help="Relay URL (ws:// or wss://). Defaults to wss://thecitadel.nostr1.com if not provided.",
    )
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
    
    # Determine publish relay (for deletions) - prioritize user-provided, then default to thecitadel
    publish_relay = args.relay_url or "wss://thecitadel.nostr1.com"
    
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
        
        # Priority: 1) user-provided relay, 2) relay hint, 3) default (thecitadel)
        if args.relay_url:
            query_relay = args.relay_url
        elif relay_hint:
            query_relay = relay_hint
        else:
            query_relay = "wss://thecitadel.nostr1.com"
        
        # Fetch root event by naddr
        print(f"\nFetching root event from {query_relay}...")
        root_event = await fetch_event_by_naddr(query_relay, kind, pubkey, d_tag)
        
        # If not found, try fallback relays
        if not root_event:
            fallback_relays = []
            if args.relay_url and relay_hint and args.relay_url != relay_hint:
                fallback_relays.append(relay_hint)
            if "wss://thecitadel.nostr1.com" not in [query_relay] + fallback_relays:
                fallback_relays.append("wss://thecitadel.nostr1.com")
            
            for fallback in fallback_relays:
                print(f"Event not found on {query_relay}, trying fallback relay {fallback}...")
                root_event = await fetch_event_by_naddr(fallback, kind, pubkey, d_tag)
                if root_event:
                    query_relay = fallback
                    break
        
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
        
        # Priority: 1) user-provided relay, 2) relay hint, 3) default (thecitadel)
        if args.relay_url:
            query_relay = args.relay_url
        elif relay_hint:
            query_relay = relay_hint
        else:
            query_relay = "wss://thecitadel.nostr1.com"
        
        # Fetch root event by ID
        print(f"\nFetching root event from {query_relay}...")
        root_event = await fetch_event_by_id(query_relay, event_id, author_hint)
        
        # If not found, try fallback relays
        if not root_event:
            fallback_relays = []
            if args.relay_url and relay_hint and args.relay_url != relay_hint:
                fallback_relays.append(relay_hint)
            if "wss://thecitadel.nostr1.com" not in [query_relay] + fallback_relays:
                fallback_relays.append("wss://thecitadel.nostr1.com")
            
            for fallback in fallback_relays:
                print(f"Event not found on {query_relay}, trying fallback relay {fallback}...")
                root_event = await fetch_event_by_id(fallback, event_id, author_hint)
                if root_event:
                    query_relay = fallback
                    break
    
    if not root_event:
        print(f"ERROR: Root event not found on any relay")
        sys.exit(1)
    
    print(f"✓ Found root event: kind={root_event.get('kind')}, d={root_event.get('tags', [])}")
    
    # Recursively fetch all events
    print(f"\nFetching all child events recursively...")
    print("This may take a while for large publications...")
    collected = set()
    errors = []
    
    # Progress tracking
    last_progress_print = 0
    
    # Progress callback for fetching
    if HAS_TQDM and sys.stdout.isatty():
        pbar = tqdm(desc="Fetching events", unit="events", dynamic_ncols=True, total=None)
        
        def progress_callback(count: int):
            if pbar is not None:
                pbar.update(1)
                pbar.set_postfix_str(f"Total: {count}")
    else:
        pbar = None
        
        def progress_callback(count: int):
            nonlocal last_progress_print
            # Print every 100 events or every 5 seconds
            current_time = time.time()
            if count % 100 == 0 or (current_time - last_progress_print) >= 5.0:
                print(f"  Fetched {count} events...", end='\r')
                last_progress_print = current_time
    
    try:
        all_events = await fetch_all_events_breadth_first(
            query_relay,
            root_event,
            collected,
            errors,
            progress_callback,
        )
    finally:
        if pbar is not None:
            pbar.close()
        if pbar is None:
            print()  # New line after progress updates
    
    print(f"✓ Collected {len(all_events)} events to delete")
    if errors:
        print(f"⚠ {len(errors)} errors occurred while fetching:")
        for err in errors[:10]:
            print(f"  - {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
    
    # Confirm deletion
    print(f"\n⚠ WARNING: About to delete {len(all_events)} events from {publish_relay}")
    response = input("Type 'DELETE' to confirm: ")
    if response != "DELETE":
        print("Cancelled.")
        sys.exit(0)
    
    # Create and publish deletion events
    print(f"\nCreating deletion events for {len(all_events)} events...")
    result = await create_and_publish_deletions(
        publish_relay,
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

