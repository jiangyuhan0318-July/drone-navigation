"""Hidden Synapse account provisioning and token brokering (Admin API).

Identity stays with fastapi-users; every website user silently gets a shadow
Synapse account ``@u_<uuid-hex-12>:<server_name>`` with a random password
nobody ever uses. The SPA receives client credentials brokered through the
admin puppet-token flow (POST /_synapse/admin/v1/users/<mxid>/login), so the
user never sees a Matrix password.

All admin calls use the token in server/config.json -> "synapse" block.
Synapse outages must NEVER break core auth: every helper degrades to None.
"""

import logging
import secrets

import aiohttp
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import CONFIG
from .models import MatrixAccount, User

log = logging.getLogger(__name__)

_cfg = CONFIG.get("synapse", {})
BASE_URL = _cfg.get("base_url", "http://127.0.0.1:8008").rstrip("/")
SERVER_NAME = _cfg.get("server_name", "localhost")
ADMIN_TOKEN = _cfg.get("admin_access_token", "")

_HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def localpart_for(user: User) -> str:
    """Stable, PII-free localpart derived from the user's UUID."""
    return f"u_{user.id.hex[:12]}"


def mxid_for(user: User) -> str:
    return f"@{localpart_for(user)}:{SERVER_NAME}"


async def ensure_user(user: User, session: AsyncSession) -> MatrixAccount | None:
    """Idempotently create the hidden Synapse user + DB mapping.

    Returns the mapping row, or None when Synapse is unreachable/rejects the
    call (chat degraded; website account unaffected).
    """
    stmt = select(MatrixAccount).where(MatrixAccount.user_id == user.id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is not None:
        return row

    mxid = mxid_for(user)
    body: dict = {"password": secrets.token_urlsafe(24)}
    if user.display_name:
        body["displayname"] = user.display_name
    try:
        async with aiohttp.ClientSession() as http:
            async with http.put(f"{BASE_URL}/_synapse/admin/v2/users/{mxid}", json=body, headers=_HEADERS) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    log.error("synapse ensure_user %s -> HTTP %s: %s", mxid, resp.status, text[:200])
                    return None
    except Exception as exc:
        log.error("synapse ensure_user %s failed: %s", mxid, exc)
        return None

    row = MatrixAccount(user_id=user.id, mxid=mxid)
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        # Concurrent ensure for the same user lost the race — reuse the winner.
        await session.rollback()
        row = (await session.execute(stmt)).scalar_one()
    log.info("synapse user provisioned: %s", mxid)
    return row


async def broker_token(user: User, session: AsyncSession) -> dict | None:
    """Broker Matrix client credentials for the user's hidden account.

    Admin puppet-token flow: POST /_synapse/admin/v1/users/<mxid>/login mints
    an access token owned by the admin but acting AS the user (Synapse >=
    1.49; replaces the removed login_token + m.login.token exchange, which
    returns M_UNRECOGNIZED on 1.157). Puppet tokens carry no device_id.
    Returns {access_token, user_id, device_id}, or None when unavailable.
    """
    row = await ensure_user(user, session)
    if row is None:
        return None
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(f"{BASE_URL}/_synapse/admin/v1/users/{row.mxid}/login",
                                 headers=_HEADERS, json={}) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    log.error("synapse admin-login %s -> HTTP %s: %s", row.mxid, resp.status, text[:200])
                    return None
                data = await resp.json()
                return {
                    "access_token": data["access_token"],
                    "user_id": row.mxid,
                    "device_id": None,
                }
    except Exception as exc:
        log.error("synapse broker_token %s failed: %s", row.mxid, exc)
        return None
