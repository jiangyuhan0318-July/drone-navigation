"""Livestream runtime configuration for the SPA.

The playable stream catalog lives in ``server/config.json`` (``mediamtx``
section) so the SAME frontend build plays the desktop MediaMTX in local
dev and the ECS MediaMTX in production — only the deployed config differs:

    local:       "streams": [ { ..., "whep_url": "http://127.0.0.1:8889/<id>/whep" }, ... ]
    production:  "streams": [ { ..., "whep_url": "https://drone-navigation.com/live/<id>/whep" }, ... ]

Each ``streams`` entry: ``{id, hostname, description, whep_url}`` — the
first entry is the PRIMARY stream (the one the Livestream Host subpage
monitors; default: ``crazyflie-drone``, the real drone's broadcast
published by ``extension/crazyflie_bridge/crazyflie_mediamtx.py``).
``whep_url`` (singular) is the legacy single-stream form — still returned
for backward compatibility.

The endpoint is public: the URLs are not secrets (they are reachable from
the browser anyway) and the Livestream page must work for logged-out
visitors.
"""

from fastapi import APIRouter

from .config import CONFIG

router = APIRouter(tags=["stream"])


@router.get("/stream/config")
async def stream_config() -> dict:
    mt = CONFIG.get("mediamtx", {})
    # Empty values when unconfigured — the SPA then keeps its built-in
    # environment fallback (local in dev, /live via Caddy in production).
    return {
        "whep_url": mt.get("whep_url", ""),
        "streams": mt.get("streams", []),
    }
