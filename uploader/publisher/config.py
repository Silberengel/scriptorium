import os
from dataclasses import dataclass
from typing import Optional

from .util import normalize_secret_key_to_hex


DEFAULT_RELAY = "wss://thecitadel.nostr1.com"


@dataclass
class Config:
    relay_url: str
    secret_key_hex: str
    source_type: str
    out_dir: str
    max_batch: int
    rate_per_sec: float
    resume: bool


def load_config(
    *,
    relay_url: Optional[str] = None,
    source_type: Optional[str] = None,
    out_dir: Optional[str] = None,
    max_batch: Optional[int] = None,
    rate_per_sec: Optional[float] = None,
    resume: Optional[bool] = None,
) -> Config:
    """
    Load configuration from env and function arguments.
    Precedence: function args > env > defaults.
    Requires SCRIPTORIUM_KEY (bech32 nsec... or hex) in env.
    """
    env_key = os.getenv("SCRIPTORIUM_KEY", "").strip()
    if not env_key:
        raise RuntimeError("Missing SCRIPTORIUM_KEY in environment")
    secret_key_hex = normalize_secret_key_to_hex(env_key)

    relay = relay_url or os.getenv("SCRIPTORIUM_RELAY", DEFAULT_RELAY)
    src_type = (source_type or os.getenv("SCRIPTORIUM_SOURCE", "HTML")).upper()
    out = out_dir or os.getenv("SCRIPTORIUM_OUT", "uploader/publisher/out")
    mb = int(max_batch or int(os.getenv("SCRIPTORIUM_MAX_BATCH", "500")))
    rps = float(rate_per_sec or float(os.getenv("SCRIPTORIUM_RATE", "50")))
    do_resume = bool(resume if resume is not None else os.getenv("SCRIPTORIUM_RESUME", "1") not in ("0", "false", "False"))

    return Config(
        relay_url=relay,
        secret_key_hex=secret_key_hex,
        source_type=src_type,
        out_dir=out,
        max_batch=mb,
        rate_per_sec=rps,
        resume=do_resume,
    )


