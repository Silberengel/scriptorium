from __future__ import annotations
import asyncio
import json
import time
import hashlib
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
    
    # Load all events and prepare them
    events_list = []
    first_event_d_tag = None
    first_event_kind = None
    
    with open(ndjson_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = orjson.loads(line)
            
            # Build event JSON
            event_json = {
                "pubkey": pub_hex,
                "created_at": int(time.time()),
                "kind": data["kind"],
                "tags": data.get("tags", []),
                "content": data.get("content", ""),
            }
            
            # Compute ID and signature
            event_id = _compute_event_id(event_json)
            event_json["id"] = event_id
            event_json["sig"] = _sign_event(event_json, priv_hex)
            
            events_list.append(event_json)
            
            # Capture first event's d-tag for verification
            if first_event_d_tag is None:
                first_event_kind = data["kind"]
                for tag in data.get("tags", []):
                    if tag and len(tag) > 0 and tag[0] == "d":
                        first_event_d_tag = tag[1] if len(tag) > 1 else None
                        break
    
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
