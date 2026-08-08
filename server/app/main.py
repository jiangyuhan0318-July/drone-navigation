"""FastAPI application entry point.

Run locally:
    cd server && uvicorn app.main:app --reload --port 8000

All routers are mounted under ``/api`` so Caddy can proxy ``/api/*`` without
path rewriting, giving identical URLs in dev and production:

    https://drone-navigation.com/api/auth/jwt/login
    http://localhost:8000/api/auth/jwt/login
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CONFIG
from .copilot import router as copilot_router
from .db import Base, engine
from .drone_commands import router as drone_commands_router
from .matrix_auth import router as matrix_router
from .safety import router as safety_router
from .schemas import UserCreate, UserRead, UserUpdate
from .settings import router as settings_router
from .stream import router as stream_router
from .telemetry import router as telemetry_router
from .users import auth_backend, fastapi_users, google_oauth_client

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (fine for v1; Alembic when the schema evolves).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Drone Navigation API", lifespan=lifespan)

# Only needed for local dev (Vite on :5173 -> API on :8000); in production the
# SPA and API are same-origin behind Caddy, so no CORS preflight occurs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CONFIG.get("cors_origins", []),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Auth: email + password (JWT) ------------------------------------------
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/api/auth/jwt",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/api/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/api/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/api/auth",
    tags=["auth"],
)

# --- Auth: Google OAuth -----------------------------------------------------
if google_oauth_client.client_id:
    app.include_router(
        fastapi_users.get_oauth_router(
            google_oauth_client,
            auth_backend,
            CONFIG["secret"],
            associate_by_email=True,
            is_verified_by_default=True,  # Google emails are pre-verified
        ),
        prefix="/api/auth/google",
        tags=["auth"],
    )

# --- Users ------------------------------------------------------------------
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/api/users",
    tags=["users"],
)

# --- Per-user settings document (GET/PUT /api/users/me/settings) ------------
app.include_router(settings_router, prefix="/api")

# --- Community chat: Matrix token brokering + user directory ----------------
app.include_router(matrix_router, prefix="/api")

# --- Livestream: MediaMTX runtime config for the SPA (GET /api/stream/config)
app.include_router(stream_router, prefix="/api")

# --- Real drone: telemetry relay (WS /api/drone/telemetry[/publish]) --------
app.include_router(telemetry_router, prefix="/api")

# --- Real drone: flight commands (WS /api/drone/command[/downlink]) ----------
app.include_router(drone_commands_router, prefix="/api")

# --- AI flight copilot (REST /api/copilot/*) ---------------------------------
app.include_router(copilot_router, prefix="/api")

# --- Safety: fall alerts + fall-response takeoff (REST /api/safety/*) -------
app.include_router(safety_router, prefix="/api")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
