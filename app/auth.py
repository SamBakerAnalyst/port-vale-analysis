"""Session-based hub login with role-locked apps.

Admin (TEAM_USERNAME / TEAM_PASSWORD) keeps full access.
Analysis accounts (ANALYSIS_USERNAME / ANALYSIS_PASSWORD, or HUB_USERS JSON)
can only open Analysis tools + the hub home ribbon for those apps.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/login",
        "/api/auth/login",
        "/api/auth/logout",
        "/fixture-planner/reject-assignment",
        # Assets for the tokenised coach scoring page, which has no login to
        # fetch them with. Listed file by file rather than opening /static.
        "/static/goal-involvement.css",
        "/static/goal-involvement-link.css",
        "/static/goal-involvement-link.js",
    }
)
PUBLIC_PREFIXES = (
    "/standalone/port-vale-badge",
    "/standalone/stadiums.json",
    "/static/stadiums.json",
    "/api/player-photo",
    "/api/availability/photo",
    # Signed per-coach Goal Involvement scoring links. The token itself carries
    # the identity and is scoped to one coach + one match — it grants nothing else.
    "/gi/",
    "/api/gi/",
)

# Paths an analysis-only account may hit (prefix match, except "/" which is exact).
ANALYSIS_ALLOWED_EXACT = frozenset(
    {"/", "/hub", "/api/auth/me", "/api/auth/logout", "/api/apps"}
)


def _analysis_allowed_prefixes() -> tuple[str, ...]:
    """Derived from apps_manifest — do not hand-edit a parallel list."""
    try:
        from app.apps_manifest import analysis_path_prefixes

        return analysis_path_prefixes()
    except Exception:
        # Boot-safe fallback if manifest import fails during early load.
        return (
            "/pre-match",
            "/set-piece-pre-match",
            "/player-cards",
            "/xg-chance-analysis",
            "/post-match",
            "/blocks-analysis",
            "/schedule",
            "/api/pre-match",
            "/api/team-badge",
            "/api/set-piece-pre-match",
            "/api/player-cards",
            "/api/xg-chance-analysis",
            "/api/post-match",
            "/api/blocks-analysis",
            "/api/schedule",
            "/api/feedback",
            "/api/apps",
            "/api/wysiwyg-export-pdf",
            "/api/wysiwyg-export-png-zip",
            "/static/",
            "/standalone/",
        )


ROLE_GROUPS = {
    "admin": ("analysis", "recruitment", "scouts", "strategy", "presentations"),
    "analysis": ("analysis",),
}


def auth_enabled() -> bool:
    return bool(os.getenv("TEAM_PASSWORD", "").strip()) or bool(_hub_users())


def team_username() -> str:
    return os.getenv("TEAM_USERNAME", "PortVale").strip() or "PortVale"


def session_secret() -> str:
    secret = os.getenv("HUB_AUTH_SECRET", "").strip()
    if secret:
        return secret
    if auth_enabled():
        return "port-vale-hub-dev-secret-change-in-production"
    return secrets.token_hex(32)


def _hub_users() -> list[dict[str, str]]:
    """Built-in admin + optional analysis account + optional HUB_USERS JSON."""
    users: list[dict[str, str]] = []
    admin_user = team_username()
    admin_pass = os.getenv("TEAM_PASSWORD", "").strip()
    if admin_pass:
        users.append(
            {
                "username": admin_user,
                "password": admin_pass,
                "role": "admin",
                "display_name": admin_user,
            }
        )

    analysis_user = os.getenv("ANALYSIS_USERNAME", "").strip()
    analysis_pass = os.getenv("ANALYSIS_PASSWORD", "").strip()
    if analysis_user and analysis_pass:
        users.append(
            {
                "username": analysis_user,
                "password": analysis_pass,
                "role": "analysis",
                "display_name": analysis_user,
            }
        )

    raw = os.getenv("HUB_USERS", "").strip()
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = []
        if isinstance(payload, list):
            for row in payload:
                if not isinstance(row, dict):
                    continue
                username = str(row.get("username") or "").strip()
                password = str(row.get("password") or "")
                role = str(row.get("role") or "analysis").strip().lower() or "analysis"
                if not username or not password:
                    continue
                if role not in ROLE_GROUPS:
                    role = "analysis"
                users.append(
                    {
                        "username": username,
                        "password": password,
                        "role": role,
                        "display_name": str(row.get("display_name") or username).strip()
                        or username,
                    }
                )
    return users


def _find_user(username: str, password: str) -> dict[str, str] | None:
    needle = username.strip().casefold()
    for user in _hub_users():
        if user["username"].casefold() == needle and user["password"] == password:
            return user
    return None


def is_authenticated(request: Request) -> bool:
    if not auth_enabled():
        return True
    return request.session.get("authenticated") is True


def current_role(request: Request) -> str:
    if not auth_enabled():
        return "admin"
    role = str(request.session.get("role") or "admin").strip().lower()
    return role if role in ROLE_GROUPS else "admin"


def current_user_payload(request: Request) -> dict[str, Any]:
    role = current_role(request)
    return {
        "authenticated": is_authenticated(request) if auth_enabled() else True,
        "username": str(request.session.get("username") or team_username()),
        "display_name": str(request.session.get("display_name") or request.session.get("username") or team_username()),
        "role": role,
        "groups": list(ROLE_GROUPS.get(role, ROLE_GROUPS["analysis"])),
        "allow_all": role == "admin",
    }


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def _path_allowed_for_role(path: str, role: str) -> bool:
    if role == "admin" or not auth_enabled():
        return True
    if path in ANALYSIS_ALLOWED_EXACT:
        return True
    # Allow asset files under standalone; block other app HTML if ever served raw.
    if path.startswith("/standalone/"):
        lower = path.lower()
        if lower.endswith((".js", ".css", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".json", ".woff", ".woff2", ".map")):
            return True
        # Analysis pages are routed via FastAPI paths, not raw HTML.
        return False
    return any(
        path == prefix.rstrip("/") or path.startswith(prefix)
        for prefix in _analysis_allowed_prefixes()
    )


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class HubAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not auth_enabled() or _is_public_path(path):
            return await call_next(request)
        if not is_authenticated(request):
            accept = request.headers.get("accept", "")
            if path.startswith("/api/") or "application/json" in accept:
                return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
            next_path = path
            if request.url.query:
                next_path = f"{path}?{request.url.query}"
            return RedirectResponse(url=f"/login?next={quote(next_path, safe='')}", status_code=302)

        role = current_role(request)
        if not _path_allowed_for_role(path, role):
            accept = request.headers.get("accept", "")
            if path.startswith("/api/") or "application/json" in accept:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Your account cannot access this tool."},
                )
            return RedirectResponse(url="/?locked=1", status_code=302)

        return await call_next(request)


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

    @app.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        if auth_enabled() and not is_authenticated(request):
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current_user_payload(request)

    @app.post("/api/auth/login")
    def login(request: Request, body: LoginRequest) -> dict[str, str | bool]:
        if not auth_enabled():
            return {"ok": True, "redirect": "/"}

        user = _find_user(body.username, body.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        request.session["authenticated"] = True
        request.session["username"] = user["username"]
        request.session["display_name"] = user.get("display_name") or user["username"]
        request.session["role"] = user["role"]

        next_url = request.query_params.get("next", "/").strip() or "/"
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/"
        if not _path_allowed_for_role(next_url.split("?", 1)[0], user["role"]):
            next_url = "/"
        return {"ok": True, "redirect": next_url, "role": user["role"]}

    @app.post("/api/auth/logout")
    def logout(request: Request) -> dict[str, bool]:
        request.session.clear()
        return {"ok": True}
