from __future__ import annotations
import asyncio
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
) -> None:
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
    
    # Run entire publish operation synchronously in a thread
    # This avoids async event loop conflicts with monstr Client
    def _sync_publish_all():
        client = Client(relay_url)
        published = 0
        with tqdm(total=total, desc="Publishing", unit="ev") as pbar:
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
                    )
                    ev.sign(priv_hex)
                    client.publish(ev)
                    published += 1
                    pbar.update(1)
        return published
    
    # Run in thread pool to avoid blocking main event loop
    published_count = await asyncio.to_thread(_sync_publish_all)


