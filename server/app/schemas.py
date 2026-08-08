"""Pydantic schemas exposed by the auth/user routers."""

import uuid

from fastapi_users import schemas
from pydantic import BaseModel, ConfigDict, Field


class UserRead(schemas.BaseUser[uuid.UUID]):
    display_name: str | None = None


class UserCreate(schemas.BaseUserCreate):
    display_name: str | None = None


class UserUpdate(schemas.BaseUserUpdate):
    display_name: str | None = None


# ─── Settings document (mirrors client/composables/useAppSettings.js) ────────
# One JSONB envelope per user, grouped like the Settings sidebar sections.
# extra="allow" keeps old/new frontends interoperable as the UI grows.


class FontSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    fontFamily: str = "Calibri"
    fontSize: str = "16px"


class FlightSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Ranges mirror the client-side setters in useAppSettings.js.
    takeoffAltitude: float = Field(100, ge=20, le=10000)
    safetyBuffer: float = Field(8, ge=0, le=100)
    defaultLat: float = Field(37.4286, ge=-90, le=90)
    defaultLon: float = Field(-122.1699, ge=-180, le=180)
    defaultAlt: float = 150
    defaultYaw: float = 180
    defaultPitch: float = Field(0, ge=-90, le=90)
    defaultRoll: float = Field(0, ge=-90, le=90)


class MediaSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    audioVolume: float = Field(0.9, ge=0, le=1)


class NetworkSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    enterpriseProxy: str = ""


class SettingsDocument(BaseModel):
    """Full settings envelope; PUT is a whole-document replace (upsert)."""

    model_config = ConfigDict(extra="allow")

    version: int = 1
    locale: str = "en"
    font: FontSettings = FontSettings()
    media: MediaSettings = MediaSettings()
    network: NetworkSettings = NetworkSettings()
    flight: FlightSettings = FlightSettings()
