"""Community-chat endpoints: Matrix credential brokering + user directory.

GET /api/matrix/token      -> brokered client credentials for the caller's
                              hidden Synapse account (same-origin homeserver).
GET /api/directory/users   -> chat-addressable users (display_name + opaque
                              mxid; emails are never exposed).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_async_session
from .matrix_admin import broker_token
from .models import MatrixAccount, User
from .users import current_active_user

router = APIRouter(tags=["matrix"])


@router.get("/matrix/token")
async def matrix_token(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    creds = await broker_token(user, session)
    if creds is None:
        raise HTTPException(status_code=503, detail="Chat service unavailable")
    # Empty homeserver_url = same-origin: the SPA reaches Synapse through our
    # own domain (Vite proxy in dev, Caddy in prod) — Matrix endpoints are
    # never exposed anywhere else.
    return {"homeserver_url": "", **creds}


@router.get("/directory/users")
async def directory_users(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[dict]:
    stmt = (
        select(User.display_name, MatrixAccount.mxid)
        .join(MatrixAccount, MatrixAccount.user_id == User.id)
        .where(User.id != user.id, User.is_active.is_(True))
        .order_by(User.display_name)
    )
    rows = (await session.execute(stmt)).all()
    return [{"display_name": name or "Pilot", "mxid": mxid} for name, mxid in rows]
