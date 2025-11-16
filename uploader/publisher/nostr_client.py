from __future__ import annotations
import asyncio
import time
from typing import Iterable, List, Dict, Any
import orjson
from tqdm import tqdm

from monstr.client.client import Client
from monstr.event.event import Event
from .util import normalize_secret_key_to_hex

# Use Keys API per monstr README, with compatibility fallbacks
def _import_keys_cls():
    candidates = (
        ("monstr.encrypt", "Keys"),
        ("monstr.keys", "Keys"),
    )
    for mod_name, cls_name in candidates:
        try:
            mod = __import__(mod_name, fromlist=[cls_name])
            if hasattr(mod, cls_name):
                return getattr(mod, cls_name)
        except Exception:
            continue
    tried = ", ".join([f"{m}.{c}" for m, c in candidates])
    raise ImportError("Unable to locate monstr.Keys; tried: " + tried)

Keys = _import_keys_cls()

def _load_keys(secret_key_str: str):
    # Try documented constructor/getter paths
    try:
        if hasattr(Keys, "get_key"):
            return Keys.get_key(secret_key_str)
    except Exception:
        pass
    # Fallback to constructor with priv_k
    try:
        return Keys(priv_k=secret_key_str)
    except Exception as e:
        raise ValueError(f"Failed to load keys from secret: {e}")

def _extract_pub_hex(keys_obj) -> str:
    # Try common accessors
    for attr in ("public_key_hex", "pub_hex", "pub_k"):
        val = getattr(keys_obj, attr, None)
        # Support both attribute and method forms
        if callable(val):
            try:
                val = val()
            except Exception:
                val = None
        if isinstance(val, str) and val:
            return val.lower()
    # Method that returns bytes or object with hex()
    meth = getattr(keys_obj, "public_key", None)
    if callable(meth):
        try:
            v = meth()
            if isinstance(v, (bytes, bytearray)):
                return v.hex()
            if hasattr(v, "hex") and callable(getattr(v, "hex")):
                return v.hex()
            if isinstance(v, str) and all(c in "0123456789abcdefABCDEF" for c in v):
                return v.lower()
        except Exception:
            pass
    raise ValueError("Unable to extract public key hex from Keys")

def _extract_priv_hex(keys_obj) -> str:
    for attr in ("private_key_hex", "priv_hex", "priv_k"):
        val = getattr(keys_obj, attr, None)
        # Support both attribute and method forms
        if callable(val):
            try:
                val = val()
            except Exception:
                val = None
        if isinstance(val, str) and val:
            return val.lower()
    # Some APIs expose .private_key() returning bytes or object
    meth = getattr(keys_obj, "private_key", None)
    if callable(meth):
        try:
            v = meth()
            if isinstance(v, (bytes, bytearray)):
                return v.hex()
            if hasattr(v, "hex") and callable(getattr(v, "hex")):
                return v.hex()
            if isinstance(v, str) and all(c in "0123456789abcdefABCDEF" for c in v):
                return v.lower()
        except Exception:
            pass
    raise ValueError("Unable to extract private key hex from Keys")


async def publish_events_ndjson(
    relay_url: str,
    secret_key_hex: str,
    ndjson_path: str,
    *,
    max_in_flight: int = 100,
) -> Dict[str, Any]:
    """
    Publish events from NDJSON file. Each line should be a JSON object with:
      { "kind": int, "tags": [...], "content": "..." }
    IDs and signatures are computed on the fly.
    """
    # Normalize secret (supports nsec bech32 or hex)
    priv_hex = normalize_secret_key_to_hex(secret_key_hex)
    # Derive public key using Keys helper if available
    pub_hex = None
    try:
        keys = _load_keys(priv_hex)
        pub_hex = _extract_pub_hex(keys)
    except Exception:
        # Try with original (bech32) string in case library prefers it
        try:
            keys = _load_keys(secret_key_hex)
            pub_hex = _extract_pub_hex(keys)
        except Exception:
            pass
    if not pub_hex:
        raise ValueError("Unable to derive public key from the supplied secret key")
    
    # Pre-count total events for progress bar
    total = 0
    with open(ndjson_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                total += 1
    
    # Run publish operation in a thread with its own event loop
    # Client needs to run its event loop to actually send queued events
    def _sync_publish_all():
        import threading
        import queue
        
        # Queue for progress updates
        progress_queue = queue.Queue()
        done_event = threading.Event()
        
        # Load all events first and capture first event's d-tag for verification
        events_list = []
        first_event_d_tag = None
        first_event_kind = None
        with open(ndjson_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = orjson.loads(line)
                ev = Event(
                    kind=data["kind"],
                    content=data.get("content", ""),
                    pub_key=pub_hex,
                    tags=data.get("tags", []),
                    created_at=int(time.time()),  # Set timestamp explicitly
                )
                ev.sign(priv_hex)
                events_list.append(ev)
                # Capture first event's d-tag for verification
                if first_event_d_tag is None:
                    first_event_kind = data["kind"]
                    for tag in data.get("tags", []):
                        if tag and len(tag) > 0 and tag[0] == "d":
                            first_event_d_tag = tag[1] if len(tag) > 1 else None
                            break
        
        # Worker thread that runs the client
        def _client_worker():
            import asyncio as worker_asyncio
            client = Client(relay_url)
            published = [0]  # Use list to allow modification in nested function
            
            # Use client as async context manager - this starts the connection
            async def _run_client():
                try:
                    async with client:
                        # Wait for connection to be established
                        try:
                            if hasattr(client, "wait_connect") and callable(client.wait_connect):
                                await client.wait_connect(timeout=10)
                            else:
                                # Fallback: poll for connection
                                max_wait = 10
                                waited = 0
                                while not client.connected and waited < max_wait:
                                    await worker_asyncio.sleep(0.5)
                                    waited += 0.5
                            
                            if not client.connected:
                                progress_queue.put(("error", "Failed to connect to relay"))
                                return
                        except Exception as e:
                            progress_queue.put(("error", f"Connection error: {e}"))
                            return
                        
                        # Publish all events with rate limiting
                        for idx, ev in enumerate(events_list):
                            try:
                                client.publish(ev)
                                published[0] += 1
                                progress_queue.put(1)
                                # Rate limiting: small delay every 10 events, longer every 100
                                if (idx + 1) % 10 == 0:
                                    await worker_asyncio.sleep(0.05)
                                if (idx + 1) % 100 == 0:
                                    await worker_asyncio.sleep(0.2)
                            except Exception as e:
                                # Log but continue on individual event errors
                                progress_queue.put(("error", str(e)))
                        # Give time for final events to be sent
                        await worker_asyncio.sleep(3)
                except Exception as e:
                    # Connection errors are expected if relay disconnects
                    # but we've already published most events
                    progress_queue.put(("connection_error", str(e)))
            
            # Run in new event loop
            loop = worker_asyncio.new_event_loop()
            worker_asyncio.set_event_loop(loop)
            
            # Suppress asyncio error logging for connection errors
            def exception_handler(loop, context):
                # Ignore connection errors - they're expected when publishing many events
                exc = context.get("exception") or context.get("message", "")
                if "Connection" in str(exc) or "disconnected" in str(exc).lower():
                    return
                # Log other exceptions
                if hasattr(loop, "default_exception_handler"):
                    loop.default_exception_handler(context)
            
            loop.set_exception_handler(exception_handler)
            
            try:
                loop.run_until_complete(_run_client())
                # Give a moment for any final sends to complete
                loop.run_until_complete(worker_asyncio.sleep(1))
            finally:
                # Cancel all remaining tasks before closing
                try:
                    pending = [t for t in worker_asyncio.all_tasks(loop) if not t.done()]
                    for task in pending:
                        task.cancel()
                    # Wait briefly for cancellations (with timeout)
                    if pending:
                        try:
                            loop.run_until_complete(worker_asyncio.wait_for(
                                worker_asyncio.gather(*pending, return_exceptions=True), timeout=2.0
                            ))
                        except worker_asyncio.TimeoutError:
                            pass  # Force close if tasks don't cancel quickly
                except Exception:
                    pass  # Ignore errors during cleanup
                finally:
                    loop.close()
            
            done_event.set()
            return published[0]
        
        # Start worker
        worker = threading.Thread(target=_client_worker, daemon=True)
        worker.start()
        
        # Monitor progress
        published = 0
        errors = []
        connection_established = False
        with tqdm(total=total, desc="Publishing", unit="ev") as pbar:
            while not done_event.is_set() or not progress_queue.empty():
                try:
                    item = progress_queue.get(timeout=0.1)
                    if isinstance(item, tuple):
                        # Error message
                        error_type, error_msg = item
                        if error_type == "connection_error":
                            # Connection lost is expected after many events
                            if published > 0:
                                print(f"\nConnection lost after publishing {published} events (this is normal)")
                        elif "Failed to connect" in error_msg or "Connection error" in error_msg:
                            errors.append(error_msg)
                            print(f"\nERROR: {error_msg}")
                        else:
                            errors.append(error_msg)
                    elif item:
                        if not connection_established:
                            connection_established = True
                            print(f"\nConnected to relay, starting publish...")
                        published += item
                        pbar.update(1)
                except queue.Empty:
                    if done_event.is_set():
                        break
                    continue
        
        if errors and not connection_established:
            print(f"\nWARNING: {len(errors)} errors occurred. First error: {errors[0]}")
        
        worker.join(timeout=5.0)
        
        return published, first_event_d_tag, first_event_kind
    
    # Run in thread pool to avoid blocking main event loop
    published_count, first_event_d_tag, first_event_kind = await asyncio.to_thread(_sync_publish_all)
    
    # Verify first event was actually published
    verification_result = {"verified": False, "error": None}
    if first_event_d_tag and first_event_kind and published_count > 0:
        print(f"\nVerifying publication by querying relay for first event...")
        client = Client(relay_url)
        
        async def _verify():
            nonlocal verification_result
            try:
                async with client:
                    # Wait for connection
                    if hasattr(client, "wait_connect"):
                        await client.wait_connect(timeout=5)
                    else:
                        max_wait = 5
                        waited = 0
                        while not client.connected and waited < max_wait:
                            await asyncio.sleep(0.5)
                            waited += 0.5
                    
                    if not client.connected:
                        verification_result["error"] = "Could not connect to relay for verification"
                        return
                    
                    # Query for the first event by author and d-tag
                    filters = [{
                        "authors": [pub_hex],
                        "kinds": [first_event_kind],
                        "#d": [first_event_d_tag]
                    }]
                    
                    events_found = []
                    async for ev in client.query(filters):
                        events_found.append(ev)
                        break  # Only need to find one
                    
                    verification_result["verified"] = len(events_found) > 0
                    if not verification_result["verified"]:
                        verification_result["error"] = f"First event (d={first_event_d_tag}) not found on relay"
            except Exception as e:
                verification_result["error"] = f"Verification error: {e}"
        
        await _verify()
    
    # Return verification result for caller to check
    return verification_result


