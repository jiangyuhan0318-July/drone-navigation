"""Per-user settings endpoints (option A: single-row JSONB document).

GET /api/users/me/settings  -> the caller's document ({} until first save)
PUT /api/users/me/settings  -> whole-document replace (upsert by user_id)

Both require an active user (Bearer JWT), matching the rest of the auth API.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_async_session
from .models import User, UserSettings
from .schemas import SettingsDocument
from .users import current_active_user

router = APIRouter(tags=["settings"])


async def _get_row(session: AsyncSession, user: User) -> UserSettings | None:
    stmt = select(UserSettings).where(UserSettings.user_id == user.id)
    return (await session.execute(stmt)).scalar_one_or_none()


@router.get("/users/me/settings")
async def read_settings(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    row = await _get_row(session, user)
    return {
        "settings": row.settings if row else {},
        "updated_at": row.updated_at if row else None,
    }


@router.put("/users/me/settings")
async def replace_settings(
    doc: SettingsDocument,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    payload = doc.model_dump()
    row = await _get_row(session, user)
    if row is None:
        row = UserSettings(user_id=user.id, settings=payload)
        session.add(row)
    else:
        # Attribute assignment marks the row dirty, so SQLAlchemy's
        # onupdate=func.now() refreshes updated_at on every save.
        row.settings = payload
    await session.commit()
    await session.refresh(row)
    return {"settings": row.settings, "updated_at": row.updated_at}
