from __future__ import annotations

from fastapi import Header, HTTPException

from .settings import settings


def require_api_token(x_api_key: str | None = Header(default=None)) -> None:
    """Optional API-key guard.

    Demo mode leaves APP_API_TOKEN empty, so existing local pages keep working.
    When APP_API_TOKEN is set, mutating endpoints require X-API-Key.
    """

    if not settings.app_api_token:
        return
    if x_api_key != settings.app_api_token:
        raise HTTPException(status_code=401, detail="API token invalid or missing")
