"""Session-based hub login (replaces Caddy basic auth).

Single shared user via TEAM_USERNAME / TEAM_PASSWORD in .env for now.
Multi-user add/remove is planned for a later phase.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

PUBLIC_PATHS = frozenset({"/health", "/login", "/api/auth/login", "/api/auth/logout"})
PUBLIC_PREFIXES = ("/standalone/port-vale-badge",)


def auth_enabled() -> bool:
    return bool(os.getenv("TEAM_PASSWORD", "").strip())


def team_username() -> str:
    return os.getenv("TEAM_USERNAME", "PortVale").strip() or "PortVale"


def session_secret() -> str:
    secret = os.getenv("HUB_AUTH_SECRET", "").strip()
    if secret:
        return secret
    if auth_enabled():
        return "port-vale-hub-dev-secret-change-in-production"
    return secrets.token_hex(32)


def is_authenticated(request: Request) -> bool:
    if not auth_enabled():
        return True
    return request.session.get("authenticated") is True


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class HubAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not auth_enabled() or _is_public_path(request.url.path):
            return await call_next(request)
        if is_authenticated(request):
            return await call_next(request)

        path = request.url.path
        accept = request.headers.get("accept", "")
        if path.startswith("/api/") or "application/json" in accept:
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

        next_path = path
        if request.url.query:
            next_path = f"{path}?{request.url.query}"
        return RedirectResponse(url=f"/login?next={quote(next_path, safe='')}", status_code=302)


def register_auth(app: FastAPI, login_html_path: Path) -> None:
    app.add_middleware(HubAuthMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret(),
        session_cookie="pv_hub_session",
        max_age=60 * 60 * 24 * 14,
        same_site="lax",
        https_only=False,
    )

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        if is_authenticated(request):
            return RedirectResponse(url="/", status_code=302)
        if not login_html_path.exists():
            raise HTTPException(status_code=503, detail="Login page not found")
        return HTMLResponse(
            login_html_path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
        )

    @app.post("/api/auth/login")
    def login(request: Request, body: LoginRequest) -> dict[str, str | bool]:
        if not auth_enabled():
            return {"ok": True, "redirect": "/"}

        username = body.username.strip()
        password = body.password
        expected_user = team_username()
        expected_password = os.getenv("TEAM_PASSWORD", "")

        if username.casefold() != expected_user.casefold() or password != expected_password:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        request.session["authenticated"] = True
        next_url = request.query_params.get("next", "/").strip() or "/"
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/"
        return {"ok": True, "redirect": next_url}

    @app.post("/api/auth/logout")
    def logout(request: Request) -> dict[str, bool]:
        request.session.clear()
        return {"ok": True}
