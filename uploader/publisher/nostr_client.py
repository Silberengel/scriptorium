from __future__ import annotations
import asyncio
from typing import Iterable, List, Dict, Any
import orjson

from monstr.client.client import Client
from monstr.event.event import Event
from monstr.identity import PrivateKey


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
    priv = PrivateKey(secret_key_hex)
    client = Client(relay_url)
    await client.connect()
    sem = asyncio.Semaphore(max_in_flight)

    async def _send(one: Dict[str, Any]):
        async with sem:
            ev = Event(
                kind=one["kind"],
                content=one.get("content", ""),
                pub_key=priv.public_key().hex(),
                tags=one.get("tags", []),
            )
            ev.sign(priv.private_key.hex())
            await client.publish(ev)

    tasks: List[asyncio.Task] = []
    with open(ndjson_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = orjson.loads(line)
            tasks.append(asyncio.create_task(_send(data)))
    if tasks:
        await asyncio.gather(*tasks)
    await client.close()


