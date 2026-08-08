"""SQLAlchemy models: User (with display_name), linked OAuth accounts, the
per-user settings document, and the hidden Synapse Matrix account mapping.

The OAuthAccount table exists from day one so Google sign-in works now and
Facebook/GitHub/Instagram only need a new httpx-oauth client — no migration.
"""

from datetime import datetime

from fastapi_users.db import SQLAlchemyBaseOAuthAccountTableUUID, SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    # Pilot display name / callsign; will feed the Matrix display name later.
    display_name: Mapped[str | None] = mapped_column(String(length=100), nullable=True)
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship("OAuthAccount", lazy="joined")


class UserSettings(Base):
    """One settings document per user (option A: single-row JSONB).

    Mirrors oauth_account's relationship pattern — separate table, FK to
    user.id, ON DELETE CASCADE — so fastapi-users' own tables stay pristine
    and deleting a user wipes their preferences. JSONB on PostgreSQL, plain
    JSON under local SQLite dev; user_id uses fastapi-users' cross-dialect
    GUID so the FK type always matches user.id.
    """

    __tablename__ = "user_settings"

    user_id: Mapped[GUID] = mapped_column(
        GUID,
        ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    settings: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"),
        nullable=False,
        default=dict,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MatrixAccount(Base):
    """Maps a fastapi-users User to their hidden Synapse account.

    The Matrix account is provisioned automatically (register hook / lazy
    ensure on token brokering) and is invisible to the user — one website
    account, chat included. Same relationship pattern as oauth_account /
    user_settings: separate table, FK to user.id, ON DELETE CASCADE.
    """

    __tablename__ = "matrix_account"

    user_id: Mapped[GUID] = mapped_column(
        GUID,
        ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mxid: Mapped[str] = mapped_column(String(length=255), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
