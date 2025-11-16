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
    """Derive public key from private key using secp256k1."""
    privkey_bytes = bytes.fromhex(privkey_hex)
    privkey = secp256k1.PrivateKey(privkey_bytes, raw=True)
    pubkey = privkey.pubkey.serialize(compressed=False)[1:]  # Skip 0x04 prefix
    return pubkey.hex()


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
    
    # Hash and sign with ECDSA
    message_hash = hashlib.sha256(message.encode('utf-8')).digest()
    privkey_bytes = bytes.fromhex(privkey_hex)
    privkey = secp256k1.PrivateKey(privkey_bytes, raw=True)
    sig = privkey.ecdsa_sign(message_hash, raw=True)
    # Serialize signature as 64-byte (r, s) format
    sig_der = privkey.ecdsa_serialize_compact(sig)
    return sig_der.hex()


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
                
                # Publish all events
                for idx, event_json in enumerate(events_list):
                    try:
                        # Send EVENT message: ["EVENT", event_json]
                        await ws.send(json.dumps(["EVENT", event_json]))
                        
                        # Wait for OK response: ["OK", event_id, accepted, message]
                        try:
                            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                            resp_data = json.loads(response)
                            if resp_data[0] == "OK":
                                event_id, accepted, msg = resp_data[1], resp_data[2], resp_data[3] if len(resp_data) > 3 else ""
                                if not accepted:
                                    errors.append(f"Event {event_id[:8]}... rejected: {msg}")
                            elif resp_data[0] == "EVENT":
                                # Sometimes relay sends back the event, that's fine
                                pass
                        except asyncio.TimeoutError:
                            # No response, but continue (relay might be slow)
                            pass
                        except Exception as e:
                            # Log but continue
                            errors.append(f"Response error for event {idx}: {e}")
                        
                        published_count += 1
                        await progress_queue.put(1)  # Signal one event published
                        
                        # Rate limiting
                        if (idx + 1) % 10 == 0:
                            await asyncio.sleep(0.05)
                        if (idx + 1) % 100 == 0:
                            await asyncio.sleep(0.2)
                            
                    except Exception as e:
                        errors.append(f"Error publishing event {idx}: {e}")
                        # Continue with next event
                
                # Give time for final events to be sent
                await asyncio.sleep(2)
                
        except Exception as e:
            errors.append(f"Connection error: {e}")
    
    # Run with progress bar
    with tqdm(total=total, desc="Publishing", unit="ev") as pbar:
        # Start publishing task
        publish_task = asyncio.create_task(_publish_all())
        
        # Update progress bar as events are published
        connection_established = False
        while not publish_task.done() or not progress_queue.empty():
            try:
                item = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
                if item == "connected":
                    if not connection_established:
                        connection_established = True
                        print(f"\nConnected to relay, starting publish...")
                elif item == 1:
                    pbar.update(1)
            except asyncio.TimeoutError:
                # Check if task is done
                if publish_task.done():
                    break
                continue
        
        # Wait for completion and drain any remaining items
        await publish_task
        while not progress_queue.empty():
            try:
                item = progress_queue.get_nowait()
                if item == 1:
                    pbar.update(1)
            except asyncio.QueueEmpty:
                break
    
    if errors:
        print(f"\nWARNING: {len(errors)} errors occurred. First error: {errors[0]}")
    
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
