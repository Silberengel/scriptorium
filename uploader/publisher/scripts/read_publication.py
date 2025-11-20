#!/usr/bin/env python3
"""
Read and display a publication from a relay.

Usage:
    python -m uploader.publisher.scripts.read_publication <event_ref> <relay_url>

    event_ref can be:
    - nevent (bech32 encoded event reference)
    - naddr (bech32 encoded address: kind:pubkey:d-tag)
    - hex event ID (64 hex characters)
    - kind:pubkey:d-tag (colon-separated format)

The script will:
1. Resolve the event reference to get the top-level 30040 event
2. Recursively fetch all child events via a-tags
3. Output publication data as JSON for display
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Any, Optional, Callable

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Check for required dependencies before importing
try:
    import orjson
except ImportError:
    print("ERROR: orjson library not found.", file=sys.stderr)
    print("Please install dependencies with:", file=sys.stderr)
    print("  pip install -r uploader/publisher/requirements.txt", file=sys.stderr)
    sys.exit(1)

try:
    from bech32 import bech32_decode, convertbits
except ImportError:
    print("ERROR: bech32 library not found.", file=sys.stderr)
    print("Please install dependencies with:", file=sys.stderr)
    print("  pip install -r uploader/publisher/requirements.txt", file=sys.stderr)
    sys.exit(1)

from uploader.publisher.nostr_client import query_events_from_relay

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


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
        
        if t == 0:  # kind (u16, 2 bytes)
            if len(v) >= 2:
                result["kind"] = int.from_bytes(v[:2], byteorder='big')
        elif t == 1:  # pubkey (32 bytes)
            result["pubkey"] = bytes(v).hex()
        elif t == 2:  # d-tag (string)
            result["d_tag"] = bytes(v).decode('utf-8')
        elif t == 3:  # relay hint (string)
            result["relay_hint"] = bytes(v).decode('utf-8')
        
        i += 2 + l
    
    if "kind" not in result or "pubkey" not in result or "d_tag" not in result:
        raise ValueError("naddr missing required fields")
    
    return result


def parse_event_ref(ref: str) -> Dict[str, Any]:
    """
    Parse an event reference in any format: nevent, naddr, hex event ID, or kind:pubkey:d-tag.
    Returns dict with: event_id, relay_hint, author_hint (for nevent/hex)
                      or kind, pubkey, d_tag, relay_hint (for naddr/kind:pubkey:d-tag)
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
    
    # Check if it's kind:pubkey:d-tag format
    if ":" in ref:
        parts = ref.split(":", 2)
        if len(parts) == 3:
            try:
                kind = int(parts[0])
                pubkey = parts[1]
                d_tag = parts[2]
                # Validate pubkey is hex (64 chars)
                if len(pubkey) == 64 and all(c in '0123456789abcdefABCDEF' for c in pubkey):
                    return {
                        "kind": kind,
                        "pubkey": pubkey.lower(),
                        "d_tag": d_tag,
                        "relay_hint": None,
                    }
            except ValueError:
                pass
    
    raise ValueError(f"Invalid event reference format. Expected nevent, naddr, hex ID, or kind:pubkey:d-tag, got: {ref[:50]}...")


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
    stream_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Recursively fetch all events in a publication tree.
    
    Args:
        relay_url: Relay URL to query
        root_event: The root event to start from
        collected: Set of event IDs already collected (to avoid duplicates)
        errors: List to append errors to
        progress_callback: Optional callback function to report progress
        stream_callback: Optional callback to stream events as they're found
    
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
    
    # Stream event immediately
    if stream_callback:
        stream_callback(root_event)
    
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
                    stream_callback,
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
                    stream_callback,
                )
                all_events.extend(child_tree)
            else:
                errors.append(f"Event not found by e-tag: {e_tag_value}")
        except Exception as e:
            errors.append(f"Error fetching event by e-tag {e_tag_value}: {e}")
    
    return all_events


def organize_publication(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Organize events into a hierarchical structure for display.
    Returns a dict with metadata and organized content.
    """
    # Find root event (kind 30040)
    root_event = None
    content_events = []
    
    for event in events:
        if event.get("kind") == 30040:
            root_event = event
        elif event.get("kind") == 30041:
            content_events.append(event)
    
    if not root_event:
        # If no 30040, use the first event as root
        root_event = events[0] if events else None
    
    # Extract metadata from root event
    metadata = {}
    for tag in root_event.get("tags", []):
        if tag and len(tag) > 1:
            tag_name = tag[0]
            tag_value = tag[1] if len(tag) > 1 else ""
            
            if tag_name in ["title", "author", "language", "summary", "published_on", "published_by", "version", "source", "image"]:
                metadata[tag_name] = tag_value
            elif tag_name == "d":
                metadata["d_tag"] = tag_value
    
    # Organize content events by d-tag hierarchy
    content_by_dtag = {}
    for event in content_events:
        d_tag = None
        for tag in event.get("tags", []):
            if tag and len(tag) > 1 and tag[0] == "d":
                d_tag = tag[1]
                break
        
        if d_tag:
            if d_tag not in content_by_dtag:
                content_by_dtag[d_tag] = []
            content_by_dtag[d_tag].append(event)
    
    return {
        "metadata": metadata,
        "root_event": root_event,
        "content_events": content_events,
        "content_by_dtag": content_by_dtag,
        "total_events": len(events),
    }


async def main():
    parser = argparse.ArgumentParser(
        description="Read and display a publication from a relay",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Read by nevent
  python -m uploader.publisher.scripts.read_publication nevent1... wss://relay.example.com
  
  # Read by naddr
  python -m uploader.publisher.scripts.read_publication naddr1... wss://relay.example.com
  
  # Read by hex event ID
  python -m uploader.publisher.scripts.read_publication abc123... wss://relay.example.com
  
  # Read by kind:pubkey:d-tag
  python -m uploader.publisher.scripts.read_publication "30040:abc123...:root" wss://relay.example.com
        """
    )
    parser.add_argument("event_ref", help="Event reference: nevent, naddr, hex ID, or kind:pubkey:d-tag")
    parser.add_argument("relay_url", help="Relay URL (ws:// or wss://)")
    parser.add_argument("--fallback-relay", default="wss://thecitadel.nostr1.com", help="Fallback relay if event not found")
    
    args = parser.parse_args()
    
    # Parse event reference
    try:
        ref_data = parse_event_ref(args.event_ref)
    except Exception as e:
        print(f"ERROR: Failed to parse event reference: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Determine initial query relay
    query_relay = args.relay_url
    root_event = None
    author_hint = None
    
    # Try to fetch root event
    if "event_id" in ref_data:
        # Fetch by event ID
        author_hint = ref_data.get("author_hint")
        relay_hint = ref_data.get("relay_hint")
        
        if relay_hint and relay_hint != query_relay:
            # Try relay hint first
            root_event = await fetch_event_by_id(relay_hint, ref_data["event_id"], author_hint)
            if root_event:
                query_relay = relay_hint
        
        if not root_event:
            # Try primary relay
            root_event = await fetch_event_by_id(query_relay, ref_data["event_id"], author_hint)
        
        if not root_event and query_relay != args.fallback_relay:
            # Try fallback relay
            print(f"Event not found on {query_relay}, trying fallback relay {args.fallback_relay}...", file=sys.stderr)
            root_event = await fetch_event_by_id(args.fallback_relay, ref_data["event_id"], author_hint)
            if root_event:
                query_relay = args.fallback_relay
    
    elif "kind" in ref_data:
        # Fetch by kind:pubkey:d-tag
        relay_hint = ref_data.get("relay_hint")
        
        if relay_hint and relay_hint != query_relay:
            # Try relay hint first
            root_event = await fetch_event_by_naddr(relay_hint, ref_data["kind"], ref_data["pubkey"], ref_data["d_tag"])
            if root_event:
                query_relay = relay_hint
        
        if not root_event:
            # Try primary relay
            root_event = await fetch_event_by_naddr(query_relay, ref_data["kind"], ref_data["pubkey"], ref_data["d_tag"])
        
        if not root_event and query_relay != args.fallback_relay:
            # Try fallback relay
            print(f"Event not found on {query_relay}, trying fallback relay {args.fallback_relay}...", file=sys.stderr)
            root_event = await fetch_event_by_naddr(args.fallback_relay, ref_data["kind"], ref_data["pubkey"], ref_data["d_tag"])
            if root_event:
                query_relay = args.fallback_relay
    
    if not root_event:
        print(f"ERROR: Root event not found on any relay.", file=sys.stderr)
        sys.exit(1)
    
    # Recursively fetch all events
    collected = set()
    errors = []
    all_events = []
    
    # Stream callback to output events as they're found
    def stream_event(event: Dict[str, Any]):
        """Output event as JSON line for streaming"""
        print(json.dumps({"type": "event", "event": event}, ensure_ascii=False), flush=True)
    
    # Progress callback
    def progress(msg: str):
        """Output progress updates"""
        print(json.dumps({"type": "progress", "message": msg}, ensure_ascii=False), flush=True, file=sys.stderr)
    
    # Output initial status
    print(json.dumps({"type": "status", "message": f"Fetching publication from {query_relay}..."}, ensure_ascii=False), flush=True, file=sys.stderr)
    
    all_events = await fetch_all_events_recursive(
        query_relay,
        root_event,
        collected,
        errors,
        progress_callback=progress,
        stream_callback=stream_event,
    )
    
    if errors:
        print(json.dumps({"type": "warnings", "count": len(errors), "errors": errors[:10]}, ensure_ascii=False), flush=True, file=sys.stderr)
    
    # Output completion message
    print(json.dumps({"type": "status", "message": f"Fetched {len(all_events)} events"}, ensure_ascii=False), flush=True, file=sys.stderr)
    
    # Organize publication
    publication = organize_publication(all_events)
    
    # Output final publication summary
    print(json.dumps({"type": "publication", "publication": publication}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())

