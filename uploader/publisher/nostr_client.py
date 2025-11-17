from __future__ import annotations
import asyncio
import json
import time
import hashlib
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
import orjson
from tqdm import tqdm
import websockets
import secp256k1

from .util import normalize_secret_key_to_hex


def _derive_pubkey(privkey_hex: str) -> str:
    """Derive public key from private key using secp256k1.
    Nostr uses the 32-byte x-coordinate of the public key (64 hex chars).
    """
    privkey_bytes = bytes.fromhex(privkey_hex)
    privkey = secp256k1.PrivateKey(privkey_bytes, raw=True)
    # Get compressed public key (33 bytes: 0x02/0x03 + 32-byte x-coordinate)
    pubkey_compressed = privkey.pubkey.serialize(compressed=True)
    # Extract just the x-coordinate (skip the 0x02/0x03 prefix)
    pubkey_x = pubkey_compressed[1:33]  # 32 bytes
    return pubkey_x.hex()


def _sign_event(event_json: Dict[str, Any], privkey_hex: str) -> str:
    """Sign a Nostr event and return the signature."""
    # Serialize event for signing: [0, pubkey, created_at, kind, tags, content]
    pubkey_hex = _derive_pubkey(privkey_hex)
    message = json.dumps([
        0,
        pubkey_hex,
        event_json["created_at"],
        event_json["kind"],
        event_json["tags"],
        event_json["content"]
    ], separators=(',', ':'), ensure_ascii=False)
    
    # Hash and sign with Schnorr (Nostr uses Schnorr signatures, not ECDSA)
    message_hash = hashlib.sha256(message.encode('utf-8')).digest()
    privkey_bytes = bytes.fromhex(privkey_hex)
    privkey = secp256k1.PrivateKey(privkey_bytes, raw=True)
    # Nostr uses Schnorr signatures (64 bytes = 128 hex chars)
    sig = privkey.schnorr_sign(message_hash, None, raw=True)
    return sig.hex()


def _compute_event_id(event_json: Dict[str, Any]) -> str:
    """Compute event ID from event JSON (without id/sig)."""
    # Serialize: [0, pubkey, created_at, kind, tags, content]
    message = json.dumps([
        0,
        event_json["pubkey"],
        event_json["created_at"],
        event_json["kind"],
        event_json["tags"],
        event_json["content"]
    ], separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(message.encode('utf-8')).hexdigest()


async def publish_events_ndjson(
    relay_url: str,
    secret_key_hex: str,
    ndjson_path: str,
    *,
    max_in_flight: int = 100,
) -> Dict[str, Any]:
    """
    Publish events from NDJSON file directly via WebSocket.
    Each line should be a JSON object with: { "kind": int, "tags": [...], "content": "..." }
    """
    # Normalize secret key (supports nsec bech32 or hex)
    priv_hex = normalize_secret_key_to_hex(secret_key_hex)
    pub_hex = _derive_pubkey(priv_hex)
    
    # Pre-count total events for progress bar
    total = 0
    with open(ndjson_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                total += 1
    
    # Load all events and build hierarchy for a-tags
    events_data = []  # Store raw event data
    parent_d_to_children = {}  # parent d-tag -> list of (child_kind, child_d_tag)
    
    with open(ndjson_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = orjson.loads(line)
            events_data.append(data)
            
            # Extract d-tag and parent d-tag (from _parent_d temporary tag)
            d_tag = None
            parent_d = None
            for tag in data.get("tags", []):
                if tag and len(tag) > 0:
                    if tag[0] == "d":
                        d_tag = tag[1] if len(tag) > 1 else None
                    elif tag[0] == "_parent_d":
                        parent_d = tag[1] if len(tag) > 1 else None
            
            if d_tag and parent_d:
                # Build parent -> children mapping
                if parent_d not in parent_d_to_children:
                    parent_d_to_children[parent_d] = []
                parent_d_to_children[parent_d].append((data["kind"], d_tag))
    
    # Add a-tags to kind 30040 events (index events)
    # Format: ["a", "<kind>:<pubkey>:<d-tag>"]
    # Also remove temporary "_parent_d" tags
    for data in events_data:
        d_tag = None
        tags = data.get("tags", [])
        new_tags = []
        has_parent_d = False
        
        for tag in tags:
            if tag and len(tag) > 0:
                if tag[0] == "d":
                    d_tag = tag[1] if len(tag) > 1 else None
                    new_tags.append(tag)
                elif tag[0] == "_parent_d":
                    # Skip temporary parent_d tag
                    has_parent_d = True
                elif tag[0] == "a":
                    # Replace placeholder pubkey in a-tags with actual pubkey
                    # Format: ["a", "<kind>:<pubkey>:<d-tag>"]
                    a_value = tag[1] if len(tag) > 1 else ""
                    if ":" in a_value:
                        parts = a_value.split(":", 2)
                        if len(parts) == 3:
                            child_kind, old_pubkey, child_d = parts
                            # Replace placeholder or update with actual pubkey
                            a_tag = ["a", f"{child_kind}:{pub_hex}:{child_d}"]
                            new_tags.append(a_tag)
                        else:
                            new_tags.append(tag)
                    else:
                        new_tags.append(tag)
                else:
                    new_tags.append(tag)
        
        # If this is a kind 30040 event and has children, add a-tags (if not already present)
        # Check if a-tags already exist (from generation)
        has_a_tags = any(t[0] == "a" for t in new_tags)
        if data["kind"] == 30040 and d_tag and d_tag in parent_d_to_children and not has_a_tags:
            for child_kind, child_d in parent_d_to_children[d_tag]:
                # Format: ["a", "<kind>:<pubkey>:<d-tag>"]
                a_tag = ["a", f"{child_kind}:{pub_hex}:{child_d}"]
                new_tags.append(a_tag)
        
        data["tags"] = new_tags
    
    # Phase 1: Prepare all events (build event JSONs without IDs/signatures)
    # Use current time for created_at - same timestamp for all events
    current_time = int(time.time())
    prepared_events = []
    first_event_d_tag = None
    first_event_kind = None
    
    for idx, data in enumerate(events_data):
        # Build event JSON (without id and sig - will be computed next)
        event_json = {
            "pubkey": pub_hex,
            "created_at": current_time,  # Use same timestamp for all - relay will accept if newer than existing
            "kind": data["kind"],
            "tags": data.get("tags", []),
            "content": data.get("content", ""),
        }
        prepared_events.append(event_json)
        
        # Capture first event's d-tag for verification
        if first_event_d_tag is None:
            first_event_kind = data["kind"]
            for tag in data.get("tags", []):
                if tag and len(tag) > 0 and tag[0] == "d":
                    first_event_d_tag = tag[1] if len(tag) > 1 else None
                    break
    
    # Phase 2: Compute IDs and sign all events at once
    print(f"Computing IDs and signing {len(prepared_events)} events...")
    events_list = []
    with tqdm(total=len(prepared_events), desc="Signing events", unit="event") as pbar:
        for event_json in prepared_events:
            # Compute ID and signature
            event_id = _compute_event_id(event_json)
            event_json["id"] = event_id
            event_json["sig"] = _sign_event(event_json, priv_hex)
            events_list.append(event_json)
            pbar.update(1)
    
    # Write complete events (with IDs and signatures) back to the file
    # This ensures we have valid Nostr events for republishing
    # Create backup of original file
    ndjson_path_obj = Path(ndjson_path)
    backup_path = ndjson_path_obj.with_suffix('.ndjson.backup')
    if ndjson_path_obj.exists():
        shutil.copy2(ndjson_path_obj, backup_path)
    
    # Write complete events back to the file
    with open(ndjson_path, "w", encoding="utf-8") as f:
        for event_json in events_list:
            f.write(orjson.dumps(event_json).decode("utf-8"))
            f.write("\n")
    
    # Publish events via WebSocket with progress tracking
    published_count = 0
    errors = []
    progress_queue = asyncio.Queue()
    
    async def _publish_all():
        nonlocal published_count, errors
        try:
            async with websockets.connect(relay_url) as ws:
                await progress_queue.put("connected")
                
                # Start a task to handle incoming messages (OK responses)
                pending_oks = {}  # event_id -> asyncio.Event
                
                async def message_handler():
                    """Handle incoming messages from relay."""
                    try:
                        async for message in ws:
                            try:
                                resp_data = json.loads(message)
                                msg_type = resp_data[0]
                                
                                if msg_type == "OK":
                                    event_id = resp_data[1]
                                    accepted = resp_data[2]
                                    msg = resp_data[3] if len(resp_data) > 3 else ""
                                    
                                    if event_id in pending_oks:
                                        pending_oks[event_id].set_result((accepted, msg))
                                    elif not accepted:
                                        errors.append(f"Event {event_id[:8]}... rejected: {msg}")
                                        
                                elif msg_type == "NOTICE":
                                    notice_msg = resp_data[1] if len(resp_data) > 1 else ""
                                    if "rate limit" in notice_msg.lower() or "error" in notice_msg.lower():
                                        errors.append(f"Relay notice: {notice_msg}")
                            except json.JSONDecodeError:
                                pass
                            except Exception as e:
                                errors.append(f"Error parsing message: {e}")
                    except (websockets.exceptions.ConnectionClosed, websockets.exceptions.WebSocketException):
                        # Connection closed or error - this is expected when publishing many events
                        # Don't treat as fatal error
                        pass
                    except Exception as e:
                        # Log but don't break - continue publishing
                        errors.append(f"Message handler error: {e}")
                
                # Start message handler
                handler_task = asyncio.create_task(message_handler())
                
                # Publish all events without waiting for OK responses
                # Send events as fast as possible, handle OKs asynchronously
                for idx, event_json in enumerate(events_list):
                    try:
                        event_id = event_json["id"]
                        pending_oks[event_id] = asyncio.Future()
                        
                        # Send EVENT message: ["EVENT", event_json]
                        await ws.send(json.dumps(["EVENT", event_json]))
                        
                        published_count += 1
                        await progress_queue.put(1)  # Signal one event published
                        
                        # Rate limiting - small delays to avoid overwhelming relay
                        if (idx + 1) % 50 == 0:
                            await asyncio.sleep(0.1)
                        if (idx + 1) % 500 == 0:
                            await asyncio.sleep(0.5)
                            
                    except (websockets.exceptions.ConnectionClosed, websockets.exceptions.WebSocketException) as e:
                        # Connection lost - this can happen with many events
                        errors.append(f"Connection lost at event {idx}/{len(events_list)}: {e}")
                        # Break the loop - can't send more events
                        break
                    except Exception as e:
                        errors.append(f"Error sending event {idx}: {e}")
                        # Continue with next event (might be transient error)
                        continue
                
                # Give time for all events to be sent and OK responses to arrive
                # Many relays are slow to respond, especially with large batches
                await progress_queue.put("waiting")
                
                # Wait longer for OK responses - relays can be slow with large batches
                # Check periodically if we're still getting responses
                wait_time = 0
                max_wait = 30  # Wait up to 30 seconds for responses
                last_response_count = 0
                while wait_time < max_wait:
                    await asyncio.sleep(2)
                    wait_time += 2
                    # Check if we got new responses
                    current_responses = sum(1 for f in pending_oks.values() if f.done())
                    if current_responses > last_response_count:
                        last_response_count = current_responses
                        # Still getting responses, wait more
                    elif wait_time >= 10 and current_responses == last_response_count:
                        # No new responses for a while, probably done
                        break
                
                # Check for rejected events (those that got OK with accepted=False)
                # We don't wait for all OKs, but check what we got
                rejected_count = 0
                accepted_count = 0
                for event_id, future in list(pending_oks.items()):
                    if future.done():
                        try:
                            accepted, msg = future.result()
                            if not accepted:
                                rejected_count += 1
                                if rejected_count <= 10:  # Only log first 10 rejections
                                    errors.append(f"Event {event_id[:8]}... rejected: {msg}")
                            else:
                                accepted_count += 1
                        except Exception:
                            pass
                    else:
                        # Cancel futures that didn't get responses
                        future.cancel()
                
                # Log summary (only once)
                if rejected_count > 0 or accepted_count > 0:
                    if accepted_count > 0:
                        print(f"  {accepted_count} events accepted by relay")
                    if rejected_count > 0:
                        print(f"  {rejected_count} events were rejected by relay")
                    if len(pending_oks) > accepted_count + rejected_count:
                        no_response = len(pending_oks) - accepted_count - rejected_count
                        print(f"  {no_response} events sent (no OK response - this is normal)")
                
                # Cancel message handler
                handler_task.cancel()
                try:
                    await handler_task
                except asyncio.CancelledError:
                    pass
                
        except Exception as e:
            errors.append(f"Connection error: {e}")
            import traceback
            errors.append(f"Traceback: {traceback.format_exc()}")
    
    # Run with progress bar
    with tqdm(total=total, desc="Publishing", unit="ev") as pbar:
        # Start publishing task
        publish_task = asyncio.create_task(_publish_all())
        
        # Update progress bar as events are published
        connection_established = False
        waiting_shown = False
        while not publish_task.done() or not progress_queue.empty():
            try:
                item = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
                if item == "connected":
                    if not connection_established:
                        connection_established = True
                        print(f"\nConnected to relay, starting publish...")
                elif item == "waiting":
                    if not waiting_shown:
                        waiting_shown = True
                        print(f"\nWaiting for relay responses...")
                elif item == 1:
                    pbar.update(1)
            except asyncio.TimeoutError:
                # Check if task is done
                if publish_task.done():
                    break
                continue
        
        # Wait for completion
        await publish_task
        
        # Drain any remaining progress items (but don't update bar multiple times)
        remaining = 0
        while not progress_queue.empty():
            try:
                item = progress_queue.get_nowait()
                if item == 1:
                    remaining += 1
            except asyncio.QueueEmpty:
                break
        if remaining > 0:
            pbar.update(remaining)
    
    if errors:
        print(f"\nWARNING: {len(errors)} errors occurred during publishing.")
        if len(errors) <= 10:
            for err in errors:
                print(f"  - {err}")
        else:
            print(f"  First 5 errors:")
            for err in errors[:5]:
                print(f"  - {err}")
            print(f"  ... and {len(errors) - 5} more")
    
    if published_count == 0:
        print(f"\nERROR: No events were published! Check connection and relay URL.")
        if errors:
            print(f"Errors: {errors[0] if errors else 'Unknown'}")
    
    # Verify first event was actually published
    verification_result = {"verified": False, "error": None}
    if first_event_d_tag and first_event_kind and published_count > 0:
        print(f"\nVerifying publication by querying relay for first event...")
        print(f"  Looking for: kind={first_event_kind}, d={first_event_d_tag}, author={pub_hex[:16]}...")
        # Wait a bit for events to propagate on the relay
        await asyncio.sleep(2)
        
        try:
            async with websockets.connect(relay_url) as ws:
                # Send REQ message: ["REQ", subscription_id, filters]
                subscription_id = "verify"
                filters = {
                    "authors": [pub_hex],
                    "kinds": [first_event_kind],
                    "#d": [first_event_d_tag]
                }
                await ws.send(json.dumps(["REQ", subscription_id, filters]))
                
                # Wait for events or EOSE
                events_found = []
                timeout = 10.0
                start_time = time.time()
                
                while time.time() - start_time < timeout:
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        resp_data = json.loads(response)
                        
                        if resp_data[0] == "EVENT" and resp_data[1] == subscription_id:
                            # Got an event
                            events_found.append(resp_data[2])
                        elif resp_data[0] == "EOSE" and resp_data[1] == subscription_id:
                            # End of stored events
                            break
                        elif resp_data[0] == "NOTICE":
                            # Relay notice, ignore
                            continue
                    except asyncio.TimeoutError:
                        # No more responses
                        break
                
                # Close subscription
                await ws.send(json.dumps(["CLOSE", subscription_id]))
                
                verification_result["verified"] = len(events_found) > 0
                if not verification_result["verified"]:
                    verification_result["error"] = f"First event (d={first_event_d_tag}) not found on relay"
                else:
                    print(f"  ✓ Found event on relay")
                    
        except Exception as e:
            verification_result["error"] = f"Verification error: {e}"
            import traceback
            print(f"  Verification exception: {traceback.format_exc()}")
    
    return verification_result


async def query_events_from_relay(
    relay_url: str,
    pubkey_hex: str,
    filters: List[Dict[str, Any]],
    *,
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Query relay for events matching the given filters.
    
    Args:
        relay_url: WebSocket URL of the relay
        pubkey_hex: Public key hex (64 chars)
        filters: List of filter dictionaries (Nostr filter format)
        timeout: Maximum time to wait for responses
    
    Returns:
        List of event dictionaries found on the relay
    """
    events_found = []
    
    try:
        async with websockets.connect(relay_url) as ws:
            # Send REQ message: ["REQ", subscription_id, filters...]
            subscription_id = f"qc_{int(time.time())}"
            req_message = ["REQ", subscription_id] + filters
            await ws.send(json.dumps(req_message))
            
            # Wait for events or EOSE
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    resp_data = json.loads(response)
                    
                    if resp_data[0] == "EVENT" and resp_data[1] == subscription_id:
                        # Got an event
                        event = resp_data[2]
                        events_found.append(event)
                    elif resp_data[0] == "EOSE" and resp_data[1] == subscription_id:
                        # End of stored events
                        break
                    elif resp_data[0] == "NOTICE":
                        # Relay notice, ignore
                        continue
                except asyncio.TimeoutError:
                    # No more responses, assume EOSE
                    break
            
            # Close subscription
            await ws.send(json.dumps(["CLOSE", subscription_id]))
            
    except Exception as e:
        # Return what we found so far, even if there was an error
        pass
    
    return events_found


async def qc_check_events(
    relay_url: str,
    secret_key_hex: str,
    ndjson_path: str,
    *,
    republish_missing: bool = False,
) -> Dict[str, Any]:
    """
    Quality control: check which events from events.ndjson are present on the relay.
    
    Args:
        relay_url: WebSocket URL of the relay
        secret_key_hex: Secret key (nsec or hex)
        ndjson_path: Path to events.ndjson file
        republish_missing: If True, republish missing events
    
    Returns:
        Dictionary with QC results: {
            "total": int,
            "found": int,
            "missing": int,
            "missing_events": List[Dict],
            "errors": List[str]
        }
    """
    # Normalize secret key
    priv_hex = normalize_secret_key_to_hex(secret_key_hex)
    pub_hex = _derive_pubkey(priv_hex)
    
    # Load all events from NDJSON
    events_to_check = []
    with open(ndjson_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = orjson.loads(line)
            events_to_check.append(data)
    
    print(f"QC: Checking {len(events_to_check)} events on relay {relay_url}...")
    
    # Extract event IDs and d-tags from events
    event_ids = []  # List of event IDs to query
    event_id_to_data = {}  # event_id -> event_data
    d_tags_by_kind: Dict[int, List[str]] = {}  # kind -> list of d-tags
    
    for event_data in events_to_check:
        event_id = event_data.get("id")
        if event_id:
            event_ids.append(event_id)
            event_id_to_data[event_id] = event_data
        
        # Also collect d-tags for fallback query
        kind = event_data.get("kind")
        if kind:
            d_tag = None
            for tag in event_data.get("tags", []):
                if tag and len(tag) > 0 and tag[0] == "d":
                    d_tag = tag[1] if len(tag) > 1 else None
                    break
            if d_tag:
                if kind not in d_tags_by_kind:
                    d_tags_by_kind[kind] = []
                if d_tag not in d_tags_by_kind[kind]:
                    d_tags_by_kind[kind].append(d_tag)
    
    # Query by event ID first (to check if latest version is on relay)
    found_by_id = set()  # Set of event IDs found on relay
    found_by_d_tag = set()  # Set of d-tags that have any version on relay
    errors = []
    
    # Query by event IDs (chunked)
    if event_ids:
        chunk_size = 100
        total_id_chunks = (len(event_ids) + chunk_size - 1) // chunk_size
        
        with tqdm(total=total_id_chunks, desc="QC: Querying by event ID", unit="chunk") as pbar:
            for i in range(0, len(event_ids), chunk_size):
                chunk_ids = event_ids[i:i + chunk_size]
                filter_dict = {
                    "authors": [pub_hex],
                    "ids": chunk_ids
                }
                
                try:
                    found = await query_events_from_relay(relay_url, pub_hex, [filter_dict], timeout=30.0)
                    for event in found:
                        event_id = event.get("id")
                        if event_id:
                            found_by_id.add(event_id)
                except Exception as e:
                    errors.append(f"Error querying event IDs (chunk {i//chunk_size + 1}): {e}")
                
                pbar.update(1)
    
    # Query by d-tags (to check if any version exists)
    # This is a fallback - if we find any version with the same d-tag, that's enough
    total_d_tag_chunks = 0
    for kind, d_tags in d_tags_by_kind.items():
        chunk_size = 100
        total_d_tag_chunks += (len(d_tags) + chunk_size - 1) // chunk_size
    
    if total_d_tag_chunks > 0:
        with tqdm(total=total_d_tag_chunks, desc="QC: Querying by d-tag", unit="chunk") as pbar:
            for kind, d_tags in d_tags_by_kind.items():
                chunk_size = 100
                for i in range(0, len(d_tags), chunk_size):
                    chunk_d_tags = d_tags[i:i + chunk_size]
                    filter_dict = {
                        "authors": [pub_hex],
                        "kinds": [kind],
                        "#d": chunk_d_tags
                    }
                    
                    try:
                        found = await query_events_from_relay(relay_url, pub_hex, [filter_dict], timeout=30.0)
                        for event in found:
                            # Extract d-tag from event
                            for tag in event.get("tags", []):
                                if tag and len(tag) > 0 and tag[0] == "d":
                                    d_tag = tag[1] if len(tag) > 1 else None
                                    if d_tag:
                                        found_by_d_tag.add(d_tag)
                                    break
                    except Exception as e:
                        errors.append(f"Error querying kind {kind} by d-tag (chunk {i//chunk_size + 1}): {e}")
                    
                    pbar.update(1)
    
    # Compare found vs expected
    # An event is considered "found" if:
    # 1. Its exact event ID is found (latest version), OR
    # 2. Any version with the same d-tag is found (any version is enough)
    missing_events = []
    found_count = 0
    
    for event_data in events_to_check:
        event_id = event_data.get("id")
        d_tag = None
        for tag in event_data.get("tags", []):
            if tag and len(tag) > 0 and tag[0] == "d":
                d_tag = tag[1] if len(tag) > 1 else None
                break
        
        # Check if found by ID (latest version) or by d-tag (any version)
        is_found = False
        if event_id and event_id in found_by_id:
            is_found = True
            found_count += 1
        elif d_tag and d_tag in found_by_d_tag:
            is_found = True
            found_count += 1
        
        # Only mark as missing if exact ID is not found
        # (We'll republish to ensure latest version is on relay)
        if event_id and event_id not in found_by_id:
            missing_events.append(event_data)
    
    result = {
        "total": len(events_to_check),
        "found": found_count,
        "found_by_id": len(found_by_id),
        "found_by_d_tag": len(found_by_d_tag),
        "missing": len(missing_events),
        "missing_events": missing_events,
        "errors": errors,
    }
    
    # Republish missing events if requested
    if republish_missing and missing_events:
        print(f"\nRepublishing {len(missing_events)} missing events...")
        # Write missing events to temporary file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ndjson', delete=False, encoding='utf-8') as f:
            for event_data in missing_events:
                f.write(orjson.dumps(event_data).decode('utf-8'))
                f.write('\n')
            temp_path = f.name
        
        try:
            # Publish missing events
            verification = await publish_events_ndjson(
                relay_url,
                secret_key_hex,
                temp_path,
                max_in_flight=100,
            )
            if verification and verification.get("verified"):
                print(f"✓ Republished {len(missing_events)} missing events")
            else:
                errors.append(f"Failed to republish missing events: {verification.get('error', 'Unknown error') if verification else 'No verification'}")
        finally:
            import os
            try:
                os.unlink(temp_path)
            except Exception:
                pass  # Ignore errors when cleaning up temp file
    
    return result
