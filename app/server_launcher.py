from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from fastapi import HTTPException

from app.paths import HUB_ROOT, PRE_MATCH_STANDALONE_DIR


@dataclass(frozen=True)
class ServerSpec:
    id: str
    label: str
    port: int
    health_path: str
    cwd: Path
    uvicorn_module: str = "app.main:app"


SERVERS: dict[str, ServerSpec] = {
    "hub": ServerSpec(
        id="hub",
        label="Analysis hub",
        port=8000,
        health_path="/health",
        cwd=HUB_ROOT,
    ),
    "pre-match-standalone": ServerSpec(
        id="pre-match-standalone",
        label="Pre-match report (standalone)",
        port=8002,
        health_path="/api/health",
        cwd=PRE_MATCH_STANDALONE_DIR,
    ),
}

PORT_TO_SERVER: dict[int, str] = {spec.port: spec.id for spec in SERVERS.values()}


def _health_url(spec: ServerSpec) -> str:
    return f"http://127.0.0.1:{spec.port}{spec.health_path}"


def _log_path(spec: ServerSpec) -> Path:
    tmp = Path(os.environ.get("TMPDIR", "/tmp"))
    return tmp / f"pv-analysis-{spec.id}.log"


def _pid_path(spec: ServerSpec) -> Path:
    tmp = Path(os.environ.get("TMPDIR", "/tmp"))
    return tmp / f"pv-analysis-{spec.id}.pid"


def _uvicorn_path(spec: ServerSpec) -> Path:
    venv_uvicorn = spec.cwd / ".venv" / "bin" / "uvicorn"
    if venv_uvicorn.is_file():
        return venv_uvicorn
    return Path(os.environ.get("UVICORN_BIN", "uvicorn"))


def server_is_healthy(spec: ServerSpec) -> bool:
    try:
        response = requests.get(_health_url(spec), timeout=2)
        return response.ok
    except requests.RequestException:
        return False


def _resolve_spec(*, server_id: str | None, port: int | None) -> ServerSpec:
    if server_id:
        spec = SERVERS.get(server_id)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"Unknown server: {server_id}")
        return spec
    if port is not None:
        resolved_id = PORT_TO_SERVER.get(port)
        if resolved_id is None:
            raise HTTPException(status_code=404, detail=f"No registered server on port {port}")
        return SERVERS[resolved_id]
    raise HTTPException(status_code=400, detail="Provide server id or port")


def list_servers() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in SERVERS.values():
        rows.append(
            {
                "id": spec.id,
                "label": spec.label,
                "port": spec.port,
                "healthy": server_is_healthy(spec),
                "installed": spec.cwd.is_dir() and (
                    _uvicorn_path(spec).is_file() or spec.id == "hub"
                ),
                "log_path": str(_log_path(spec)),
            }
        )
    return rows


def _clean_proxy_env(env: dict[str, str]) -> dict[str, str]:
    cleaned = dict(env)
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "GIT_HTTP_PROXY",
        "GIT_HTTPS_PROXY",
        "SOCKS_PROXY",
        "SOCKS5_PROXY",
        "socks_proxy",
        "socks5_proxy",
    ):
        cleaned.pop(key, None)
    return cleaned


def _start_server(spec: ServerSpec) -> None:
    if spec.id == "hub":
        script = spec.cwd / "restart.sh"
        if not script.is_file():
            raise HTTPException(status_code=503, detail="Hub restart script not found.")
        subprocess.Popen(
            ["/bin/bash", str(script)],
            cwd=str(spec.cwd),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return

    uvicorn = _uvicorn_path(spec)
    if not spec.cwd.is_dir():
        raise HTTPException(
            status_code=503,
            detail=f"{spec.label} is not installed at {spec.cwd}",
        )

    log_path = _log_path(spec)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")

    log_handle = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [
            str(uvicorn),
            spec.uvicorn_module,
            "--host",
            "127.0.0.1",
            "--port",
            str(spec.port),
        ],
        cwd=str(spec.cwd),
        start_new_session=True,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=_clean_proxy_env(os.environ),
    )
    _pid_path(spec).write_text(str(process.pid), encoding="utf-8")


def _port_is_open(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        try:
            return sock.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


def ensure_server(*, server_id: str | None = None, port: int | None = None) -> dict[str, Any]:
    spec = _resolve_spec(server_id=server_id, port=port)
    if server_is_healthy(spec):
        return {
            "status": "running",
            "server": spec.id,
            "port": spec.port,
            "started": False,
        }

    already_bound = _port_is_open(spec.port)
    if not already_bound:
        try:
            _start_server(spec)
        except HTTPException:
            raise
        except Exception as exc:
            if not _port_is_open(spec.port):
                raise HTTPException(
                    status_code=503,
                    detail=f"Failed to start {spec.label}: {exc}",
                ) from exc

    deadline = time.time() + (60 if already_bound else 45)
    while time.time() < deadline:
        if server_is_healthy(spec):
            return {
                "status": "running",
                "server": spec.id,
                "port": spec.port,
                "started": not already_bound,
            }
        time.sleep(0.25)

    log_hint = f" Check the log at {_log_path(spec)}"
    if already_bound:
        detail = (
            f"{spec.label} is listening on port {spec.port} but health check "
            f"{spec.health_path} did not pass.{log_hint}"
        )
    else:
        detail = f"{spec.label} did not start within 45 seconds.{log_hint}"
    raise HTTPException(status_code=504, detail=detail)
