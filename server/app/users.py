"""fastapi-users wiring: UserManager, Bearer/JWT backend, and OAuth clients.

Auth model:
  - Bearer JWT transport (SPA sends ``Authorization: Bearer <token>``).
  - Email+password registration automatically triggers a verification email.
  - Google OAuth via httpx-oauth; ``associate_by_email`` links a Google login
    to an existing account with the same email. New providers (Facebook,
    GitHub, Instagram, ...) only need another client in ``OAUTH_CLIENTS`` and
    a matching router in main.py.
"""

import logging
import uuid

from fastapi import Depends
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from httpx_oauth.clients.google import GoogleOAuth2
from sqlalchemy.ext.asyncio import AsyncSession

from .config import CONFIG
from .db import async_session_maker, get_async_session
from .email import send_password_reset_email, send_verification_email
from .matrix_admin import ensure_user as ensure_matrix_user
from .models import OAuthAccount, User

log = logging.getLogger(__name__)

SECRET = CONFIG["secret"]


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
):
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def on_after_register(self, user: User, request=None) -> None:
        # Fire the verification email right after sign-up.
        await self.request_verify(user, request)
        # Provision the hidden Synapse chat account. Failure must NEVER block
        # registration — the token endpoint lazily re-ensures on first use.
        try:
            async with async_session_maker() as session:
                await ensure_matrix_user(user, session)
        except Exception:
            log.exception("matrix provisioning failed for user %s", user.id)

    async def on_after_request_verify(self, user: User, token: str, request=None) -> None:
        await send_verification_email(user.email, token)

    async def on_after_forgot_password(self, user: User, token: str, request=None) -> None:
        await send_password_reset_email(user.email, token)


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


bearer_transport = BearerTransport(tokenUrl="/api/auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=SECRET,
        lifetime_seconds=CONFIG.get("jwt_lifetime_seconds", 86400),
    )


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])
current_active_user = fastapi_users.current_user(active=True)

# --- OAuth providers -------------------------------------------------------

_google_cfg = CONFIG.get("oauth", {}).get("google", {})
google_oauth_client = GoogleOAuth2(
    _google_cfg.get("client_id", ""),
    _google_cfg.get("client_secret", ""),
)
