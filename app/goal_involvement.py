"""Goal Involvement — 10-point coach scoring for Vale goals for and against."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import statistics
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth import _hub_users as hub_users
from app.auth import current_user_payload as current_user
from app.fixture_assignment_email import COACHING_EMAILS as COACH_EMAILS
from app.match_player_utils import _position_abbr as position_abbr
from app.paths import DATA_ROOT as DATA_ROOT
from app.paths import STANDALONE_DIR as STANDALONE_DIR
from app.paths import ensure_data_dirs as ensure_dirs
from app.pre_match import _completed_opponent_fixtures as completed_fixtures
from app.pre_match import _fetch_match_detail as fetch_match_detail
from app.pre_match import _impect as impect_mod
from app.pre_match import _match_is_complete as match_complete
from app.pre_match import _match_squad_block as match_squad
from app.pre_match import _player_surname as surname
from app.pre_match import _resolve_port_vale_squad_id as vale_squad_id
from app.pre_match import _squads_map as squads_map
from app.pre_match import _unwrap_items as unwrap
from app.squad_review import _default_port_vale_season as default_season
from app.squad_review import _resolve_port_vale_iteration as resolve_iteration
from app.xg_chance_analysis import RED_CARD_ACTIONS as RED_CARDS
from app.xg_chance_analysis import _fetch_match_events as fetch_events
from app.xg_chance_analysis import _parse_impect_minute as parse_minute
from app.xg_chance_analysis import _player_directory as player_names
from app.xg_chance_analysis import _player_name as event_player_name
from app.xg_chance_analysis import _shot_outcome as shot_outcome

POINTS = 10
CURRENT_SEASON = "26/27"
# match_id 0 on a link means "everything this coach still owes", worked out when
# they open it, rather than one fixed game.
ALL_OUTSTANDING = 0
# The standing link is how a coach catches up after missing games, so it has to
# outlive a busy spell. A one-off match link can go stale sooner.
STANDING_LINK_DAYS = 240
MATCH_LINK_DAYS = 21
DB_PATH = DATA_ROOT / "goal-involvement.sqlite"
_lock = threading.Lock()
_ready = False

# Coaches share the one hub login, so scoring identity comes from a picker.
DEFAULT_COACHES: tuple[tuple[str, str], ...] = (
    ("JB", "Jon Brady"),
    ("GM", "Gary Mills"),
    ("ROD", "Richard O'Donnell"),
    ("JS", "Jamie Smith"),
    ("DW", "Dan Watson"),
)


class Allocation(BaseModel):
    player_id: int
    points: int = Field(ge=0, le=POINTS)


class ScoreBody(BaseModel):
    allocations: list[Allocation] = Field(min_length=1)
    coach_id: str | None = None


class CloseBody(BaseModel):
    note: str = ""


class CoachItem(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    active: bool = True
    sort_order: int = 0
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=120)


class CoachesBody(BaseModel):
    coaches: list[CoachItem]
    expected_coach_count: int = Field(default=6, ge=1, le=20)
    quorum: int = Field(default=5, ge=1, le=20)
    disagreement_threshold: float = Field(default=1.5, ge=0, le=10)


class ManualGoalBody(BaseModel):
    match_id: int
    minute: int = Field(ge=0, le=130)
    team_for_or_against: str
    scorer_name: str = ""
    player_ids: list[int] = Field(default_factory=list)


class PlayersBody(BaseModel):
    player_ids: list[int] = Field(min_length=1)


class AddPlayerBody(BaseModel):
    player_id: int


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scoring_links (
            code TEXT PRIMARY KEY,
            coach_id TEXT NOT NULL,
            match_id INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS coaches (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY,
            match_id INTEGER NOT NULL,
            event_id INTEGER,
            date TEXT NOT NULL,
            season TEXT,
            competition TEXT,
            opponent TEXT,
            is_home INTEGER NOT NULL DEFAULT 1,
            scoreline TEXT,
            scoreline_before TEXT,
            team_for_or_against TEXT NOT NULL,
            minute REAL NOT NULL,
            minute_label TEXT,
            scorer_id INTEGER,
            scorer_name TEXT,
            players_on_pitch TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'open',
            closed_at TEXT,
            closed_by TEXT,
            close_note TEXT,
            created_at TEXT NOT NULL,
            clip_file TEXT NOT NULL DEFAULT '',
            clip_url TEXT NOT NULL DEFAULT '',
            clip_added_at TEXT,
            clip_added_by TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_goals_event
            ON goals(match_id, event_id) WHERE event_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_goals_match ON goals(match_id);
        CREATE INDEX IF NOT EXISTS idx_goals_date ON goals(date);
        CREATE TABLE IF NOT EXISTS goal_scores (
            goal_id TEXT NOT NULL,
            coach_id TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            points INTEGER NOT NULL,
            submitted_at TEXT NOT NULL,
            PRIMARY KEY (goal_id, coach_id, player_id),
            FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_scores_coach ON goal_scores(coach_id);
        """
    )
    # Contact columns arrived after the first deploy — add them to live DBs.
    have = {str(row["name"]) for row in conn.execute("PRAGMA table_info(coaches)").fetchall()}
    for column in ("phone", "email"):
        if column not in have:
            conn.execute(f"ALTER TABLE coaches ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    # Clips arrived later too, so widen goals tables that predate them.
    goal_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(goals)").fetchall()}
    for column, ddl in (
            ("clip_file", "TEXT NOT NULL DEFAULT ''"),
            ("clip_url", "TEXT NOT NULL DEFAULT ''"),
            ("clip_added_at", "TEXT"),
            ("clip_added_by", "TEXT"),
            ("play_type", "TEXT NOT NULL DEFAULT ''"),
    ):
        if column not in goal_columns:
            conn.execute(f"ALTER TABLE goals ADD COLUMN {column} {ddl}")
    # Coaches seeded before those columns existed still have no email, and
    # seed_coaches will not revisit them, so fill the known ones in here.
    for display_name, email in COACH_EMAILS.items():
        conn.execute(
            "UPDATE coaches SET email = ? WHERE display_name = ? AND email = ''",
            (email, display_name),
        )
    for key, value in {
        "expected_coach_count": "6",
        "quorum": "5",
        "disagreement_threshold": "1.5",
    }.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
    seed_coaches(conn)


def seed_coaches(conn: sqlite3.Connection) -> None:
    """Put the real coaching staff in on first boot so nobody has to type them."""
    if setting(conn, "coaches_seeded", "") == "1":
        return
    when = now()
    for index, (coach_id, display_name) in enumerate(DEFAULT_COACHES):
        conn.execute(
            """
            INSERT OR IGNORE INTO coaches (id, display_name, active, sort_order, created_at, phone, email)
            VALUES (?, ?, 1, ?, ?, '', ?)
            """,
            (coach_id, display_name, index, when, COACH_EMAILS.get(display_name, "")),
        )
    for key, value in {
        "coaches_seeded": "1",
        "expected_coach_count": str(len(DEFAULT_COACHES)),
        "quorum": str(max(1, len(DEFAULT_COACHES) - 1)),
    }.items():
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, value))


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    global _ready
    with _lock:
        conn = connect()
        try:
            if not _ready:
                init_schema(conn)
                conn.commit()
                _ready = True
            yield conn
            conn.commit()
        finally:
            conn.close()


def as_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def setting(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def settings(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "expected_coach_count": int(setting(conn, "expected_coach_count", "6")),
        "quorum": int(setting(conn, "quorum", "5")),
        "disagreement_threshold": float(setting(conn, "disagreement_threshold", "1.5")),
        "points_pool": POINTS,
        "last_sync_at": setting(conn, "last_sync_at", ""),
        "last_sync_season": setting(conn, "last_sync_season", ""),
    }


def actor(request: Request) -> dict[str, Any]:
    payload = current_user(request)
    username = str(payload.get("username") or "staff").strip() or "staff"
    role = str(payload.get("role") or "analysis")
    return {
        "id": username,
        "display_name": str(payload.get("display_name") or username),
        "role": role,
        "is_admin": bool(payload.get("allow_all") or role == "admin"),
    }


def coaches(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, display_name, active, sort_order, phone, email
        FROM coaches ORDER BY sort_order, display_name
        """
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "display_name": str(row["display_name"]),
            "active": bool(row["active"]),
            "sort_order": int(row["sort_order"] or 0),
            "phone": str(row["phone"] or ""),
            "email": str(row["email"] or ""),
        }
        for row in rows
    ]


def link_secret() -> bytes:
    raw = (
        os.getenv("GI_LINK_SECRET", "").strip()
        or os.getenv("HUB_AUTH_SECRET", "").strip()
        or "goal-involvement-dev-secret"
    )
    return raw.encode("utf-8")


def make_scoring_token(*, coach_id: str, match_id: int, ttl_days: int = 21) -> str:
    """Signed 'you are this coach, for this match' link — no hub login needed."""
    exp = int(time.time()) + max(1, int(ttl_days)) * 86400
    payload = f"{coach_id}\n{int(match_id)}\n{exp}"
    sig = hmac.new(link_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}\n{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_scoring_token(token: str) -> dict[str, Any] | None:
    raw = str(token or "").strip()
    if not raw:
        return None
    pad = "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw + pad).decode("utf-8")
    except Exception:
        return None
    parts = decoded.split("\n")
    if len(parts) != 4:
        return None
    coach_id, match_raw, exp_raw, sig = parts
    try:
        match_id = int(match_raw)
        exp = int(exp_raw)
    except ValueError:
        return None
    payload = f"{coach_id}\n{match_id}\n{exp}"
    expected = hmac.new(link_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    if exp < int(time.time()):
        return None
    return {"coach_id": coach_id, "match_id": match_id, "exp": exp}


# No 0/O/1/I/L — coaches occasionally read these out or type them by hand.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def link_code(conn: sqlite3.Connection, *, coach_id: str, match_id: int, ttl_days: int | None = None) -> str:
    """Short code for a coach, so the URL we send stays human-sized.

    A standing "everything you owe" link is the catch-up route, so it gets a
    season-long life and the same code every time. Re-sending also pushes the
    expiry out, meaning whichever message a coach scrolls back to still works.
    """
    if ttl_days is None:
        ttl_days = STANDING_LINK_DAYS if int(match_id) == ALL_OUTSTANDING else MATCH_LINK_DAYS
    now_ts = int(time.time())
    fresh = now_ts + max(1, int(ttl_days)) * 86400
    existing = conn.execute(
        """
        SELECT code, expires_at FROM scoring_links
        WHERE coach_id = ? AND match_id = ?
        ORDER BY expires_at DESC LIMIT 1
        """,
        (coach_id, int(match_id)),
    ).fetchone()
    if existing:
        code = str(existing["code"])
        if int(existing["expires_at"]) < fresh:
            conn.execute("UPDATE scoring_links SET expires_at = ? WHERE code = ?", (fresh, code))
        return code

    expires = fresh
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        try:
            conn.execute(
                """
                INSERT INTO scoring_links (code, coach_id, match_id, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (code, coach_id, int(match_id), expires, now()),
            )
        except sqlite3.IntegrityError:
            continue
        return code
    raise HTTPException(status_code=500, detail="Could not mint a scoring link.")


def resolve_link(conn: sqlite3.Connection, code: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT coach_id, match_id, expires_at FROM scoring_links WHERE code = ?",
        (str(code or "").strip().upper(),),
    ).fetchone()
    if not row:
        return None
    if int(row["expires_at"]) < int(time.time()):
        return None
    return {
        "coach_id": str(row["coach_id"]),
        "match_id": int(row["match_id"]),
        "exp": int(row["expires_at"]),
    }


def link_base_url(request: Request) -> str:
    override = os.getenv("GI_LINK_BASE_URL", "").strip()
    if override:
        return override.rstrip("/")
    # Behind Caddy the app sees http/internal host, so trust the proxy headers.
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "http").split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    if not host:
        return str(request.base_url).rstrip("/")
    return f"{proto}://{host}"


CLIPS_DIR = DATA_ROOT / "goal-involvement" / "clips"
# Generous for a goal clip (a 30s 1080p cut is nearer 20MB) but small enough
# that a mis-picked full-match file is refused rather than filling the disk.
MAX_CLIP_BYTES = 150 * 1024 * 1024
CLIP_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}
# Providers that allow embedding. Anything else becomes a "watch" button rather
# than an iframe that silently renders a refused-to-connect box.
EMBEDDABLE = re.compile(r"(youtube\.com|youtu\.be|vimeo\.com|player\.vimeo\.com)", re.I)


def clip_dir() -> Any:
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    return CLIPS_DIR


def clip_filename(goal_id: str, suffix: str) -> str:
    """Goal ids are ours, but never trust one straight into a filesystem path."""
    stem = re.sub(r"[^A-Za-z0-9_-]", "", str(goal_id))[:80]
    if not stem:
        stem = hashlib.sha256(str(goal_id).encode()).hexdigest()[:16]
    return f"{stem}{suffix}"


def clip_file_path(goal: dict[str, Any]) -> Any:
    name = str(goal.get("clip_file") or "").strip()
    if not name:
        return None
    # Re-derive rather than trusting the stored string as a path.
    candidate = CLIPS_DIR / os.path.basename(name)
    return candidate if candidate.is_file() else None


def embed_url(raw: str) -> str:
    """Turn a normal YouTube/Vimeo link into one that works inside an iframe."""
    url = str(raw or "").strip()
    youtube = re.search(r"(?:youtu\.be/|v=)([A-Za-z0-9_-]{6,})", url)
    if youtube and "youtube.com/embed/" not in url:
        return f"https://www.youtube.com/embed/{youtube.group(1)}"
    vimeo = re.search(r"vimeo\.com/(?:video/)?(\d+)", url)
    if vimeo and "player.vimeo.com" not in url:
        return f"https://player.vimeo.com/video/{vimeo.group(1)}"
    return url


def clip_info(goal: dict[str, Any]) -> dict[str, Any]:
    """Describe a goal's clip without leaking where it sits on disk.

    The caller builds the stream URL, because the same file is reached through
    the hub when an analyst is logged in and through the token when a coach is
    not, and only the caller knows which of those it is.
    """
    link = str(goal.get("clip_url") or "").strip()
    if clip_file_path(goal) is not None:
        kind = "file"
    elif link:
        kind = "embed" if EMBEDDABLE.search(link) else "link"
    else:
        kind = ""
    return {
        "kind": kind,
        "has_clip": bool(kind),
        "url": embed_url(link) if kind == "embed" else link,
        "added_at": goal.get("clip_added_at"),
        "added_by": goal.get("clip_added_by"),
    }


def store_clip(goal_id: str, *, filename: str, blob: bytes) -> str:
    suffix = os.path.splitext(str(filename or ""))[1].lower()
    if suffix not in CLIP_TYPES:
        allowed = ", ".join(sorted(CLIP_TYPES))
        raise HTTPException(status_code=400, detail=f"Clips must be one of: {allowed}.")
    if not blob:
        raise HTTPException(status_code=400, detail="That file was empty.")
    if len(blob) > MAX_CLIP_BYTES:
        cap = MAX_CLIP_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Clip is too big — keep it under {cap}MB.")
    name = clip_filename(goal_id, suffix)
    target = clip_dir() / name
    # Same goal re-uploaded as a different format would otherwise leave the old
    # file orphaned on disk.
    for stale in CLIPS_DIR.glob(f"{os.path.splitext(name)[0]}.*"):
        if stale.name != name:
            stale.unlink(missing_ok=True)
    target.write_bytes(blob)
    return name


def drop_clip(goal: dict[str, Any]) -> None:
    existing = clip_file_path(goal)
    if existing is not None:
        existing.unlink(missing_ok=True)


def clip_response(goal: dict[str, Any]) -> FileResponse:
    path = clip_file_path(goal)
    if path is None:
        raise HTTPException(status_code=404, detail="No clip attached to that goal.")
    media = CLIP_TYPES.get(path.suffix.lower(), "video/mp4")
    # FileResponse answers Range requests, which Safari requires before it will
    # play a video at all, and which lets everyone scrub.
    return FileResponse(path, media_type=media)


def first_name(display_name: str) -> str:
    return str(display_name or "").strip().split(" ")[0] or "Hi"


def friendly_date(raw: Any) -> str:
    """'2026-08-22' -> ' on Sat 22 Aug'. Blank if we cannot read it."""
    try:
        parsed = datetime.strptime(str(raw or "")[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return f" on {parsed.strftime('%a %-d %b')}"


def wa_number(phone: str) -> str:
    """wa.me wants digits only, country code included, no + or spaces."""
    digits = re.sub(r"\D", "", str(phone or ""))
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "44" + digits[1:]
    return digits


def acting(conn: sqlite3.Connection, person: dict[str, Any], coach_id: str | None) -> dict[str, Any]:
    """Resolve which coach the points belong to — the staff share one hub login."""
    active = [row for row in coaches(conn) if row["active"]]
    wanted = str(coach_id or "").strip().casefold()
    chosen: dict[str, Any] | None = None
    if wanted:
        chosen = next((row for row in active if row["id"].casefold() == wanted), None)
    if chosen is None:
        chosen = next((row for row in active if row["id"].casefold() == person["id"].casefold()), None)
    if chosen is None and not active:
        chosen = {"id": person["id"], "display_name": person["display_name"]}
    return {
        **person,
        "coach_id": str(chosen["id"]) if chosen else "",
        "coach_name": str(chosen["display_name"]) if chosen else "",
        "is_listed_coach": bool(chosen and active),
    }


def can_score(conn: sqlite3.Connection, person: dict[str, Any]) -> bool:
    if not person.get("coach_id"):
        return False
    active = [row for row in coaches(conn) if row["active"]]
    if not active:
        return True
    return str(person["coach_id"]).casefold() in {row["id"].casefold() for row in active}


def coach_progress(conn: sqlite3.Connection, season: str | None) -> dict[str, int]:
    sql = """
        SELECT s.coach_id AS coach_id, COUNT(DISTINCT s.goal_id) AS scored
        FROM goal_scores s
        JOIN goals g ON g.id = s.goal_id
    """
    params: list[Any] = []
    if season:
        sql += " WHERE g.season = ?"
        params.append(season)
    sql += " GROUP BY s.coach_id"
    return {str(row["coach_id"]): int(row["scored"]) for row in conn.execute(sql, params).fetchall()}


def season_squad(conn: sqlite3.Connection, season: str | None) -> list[dict[str, Any]]:
    """Everyone we have seen on the pitch — the pool for 'add a player'."""
    sql = "SELECT players_on_pitch FROM goals"
    params: list[Any] = []
    if season:
        sql += " WHERE season = ?"
        params.append(season)
    seen: dict[int, dict[str, Any]] = {}
    for row in conn.execute(sql, params).fetchall():
        for player in parse_players(row["players_on_pitch"]):
            player_id = int(player.get("id") or 0)
            if not player_id or player_id in seen:
                continue
            seen[player_id] = {
                "id": player_id,
                "name": player.get("name") or f"Player {player_id}",
                "short_name": player.get("short_name") or surname(str(player.get("name") or "")),
                "position": player.get("position") or "",
                "shirt": player.get("shirt"),
                "photo_url": player.get("photo_url") or f"/api/player-photo?name={player.get('name') or ''}",
            }
    return sorted(seen.values(), key=lambda row: str(row["name"]))


def require_admin(person: dict[str, Any]) -> None:
    if not person["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin only.")


def allocation_total(rows: list[Allocation]) -> int:
    return sum(int(row.points) for row in rows)


def pstdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return round(float(statistics.pstdev(values)), 3)


def average_player_scores(
    *,
    player_ids: list[int],
    coach_ids: list[str],
    scores: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not coach_ids:
        return []
    pairs = {(str(row["coach_id"]), int(row["player_id"])): int(row["points"]) for row in scores}
    out: list[dict[str, Any]] = []
    for player_id in player_ids:
        per = [float(pairs.get((coach_id, player_id), 0)) for coach_id in coach_ids]
        mean = round(sum(per) / len(per), 3) if per else 0.0
        out.append(
            {
                "player_id": player_id,
                "mean": mean,
                "stdev": pstdev(per),
                "min": min(per) if per else 0.0,
                "max": max(per) if per else 0.0,
                "by_coach": {coach_id: per[i] for i, coach_id in enumerate(coach_ids)},
            }
        )
    out.sort(key=lambda row: (-row["mean"], row["player_id"]))
    return out


MATRIX_SPREAD = 3.0
MATRIX_CELL_DELTA = 2.0


def disagreement_summary(player_rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    involved = [row for row in player_rows if row["mean"] > 0 or row["stdev"] > 0]
    stdevs = [float(row["stdev"]) for row in involved] or [0.0]
    average = round(sum(stdevs) / len(stdevs), 3)
    peak = round(max(stdevs), 3)
    flagged = average >= threshold or peak >= max(threshold, 2.0)
    if peak < 0.75 and average < 0.75:
        label = "High agreement"
    elif flagged:
        label = "Low agreement"
    else:
        label = "Mixed"
    return {
        "average_stdev": average,
        "max_stdev": peak,
        "threshold": threshold,
        "flagged": flagged,
        "label": label,
    }


def parse_players(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        payload = raw
    else:
        try:
            payload = json.loads(raw or "[]")
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def clock_seconds(raw: Any) -> float:
    if isinstance(raw, dict):
        return float(parse_minute(raw)) * 60.0
    if isinstance(raw, (int, float)):
        return float(raw)
    return 0.0


def minute_label(minute: float) -> str:
    if minute >= 90:
        extra = int(round(minute - 90))
        return f"90+{extra}'" if extra else "90'"
    return f"{int(minute)}'"


def shirts(squad: dict[str, Any]) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for row in squad.get("players") or []:
        if not isinstance(row, dict):
            continue
        player_id = int(row.get("id") or 0)
        shirt = row.get("shirtNumber") or row.get("shirt_number")
        if not player_id or shirt is None:
            continue
        try:
            mapping[player_id] = int(shirt)
        except (TypeError, ValueError):
            continue
    return mapping


def player_card(
    player_id: int,
    names: dict[int, str],
    *,
    position: str = "",
    shirt: int | None = None,
    started: bool = False,
) -> dict[str, Any]:
    name = names.get(player_id) or f"Player {player_id}"
    return {
        "id": player_id,
        "name": name,
        "short_name": surname(name),
        "position": position_abbr(position) if position else "",
        "position_raw": position,
        "shirt": shirt,
        "started": started,
        "photo_url": f"/api/player-photo?name={name}",
    }


def on_pitch(
    match_id: int,
    squad_id: int,
    goal_seconds: float,
    names: dict[int, str],
) -> list[dict[str, Any]]:
    detail = fetch_match_detail(match_id)
    squad = match_squad(detail, squad_id)
    if not squad:
        return []
    numbers = shirts(squad)
    pitch: dict[int, dict[str, Any]] = {}
    for row in squad.get("startingPositions") or []:
        if not isinstance(row, dict):
            continue
        player_id = int(row.get("playerId") or 0)
        if not player_id:
            continue
        pitch[player_id] = player_card(
            player_id,
            names,
            position=str(row.get("position") or ""),
            shirt=numbers.get(player_id),
            started=True,
        )
    events: list[dict[str, Any]] = []
    for row in squad.get("substitutions") or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("substitutionType") or "").upper()
        if kind not in {"SUB_ON", "RED_CARD"}:
            continue
        events.append(
            {
                "type": kind,
                "seconds": clock_seconds(row.get("gameTime")),
                "player_id": int(row.get("playerId") or 0),
                "off_id": int(row.get("exchangedPlayerId") or 0),
                "position": str(row.get("toPosition") or row.get("position") or ""),
            }
        )
    try:
        match_events = fetch_events(match_id)
    except Exception:
        match_events = []
    for event in match_events:
        action = str(event.get("action") or event.get("actionType") or "").upper()
        if action not in RED_CARDS:
            continue
        if int(event.get("squadId") or 0) != int(squad_id):
            continue
        player = event.get("player") or {}
        game_time = event.get("gameTime") or {}
        events.append(
            {
                "type": "RED_CARD",
                "seconds": clock_seconds(game_time) if isinstance(game_time, dict) else 0.0,
                "player_id": int(player.get("id") or 0),
                "off_id": 0,
                "position": "",
            }
        )
    events.sort(key=lambda item: (float(item["seconds"]), item["type"] != "SUB_ON"))
    for event in events:
        if float(event["seconds"]) >= goal_seconds:
            continue
        player_id = int(event["player_id"] or 0)
        if event["type"] == "SUB_ON":
            off_id = int(event.get("off_id") or 0)
            if off_id:
                pitch.pop(off_id, None)
            if player_id:
                pitch[player_id] = player_card(
                    player_id,
                    names,
                    position=str(event.get("position") or ""),
                    shirt=numbers.get(player_id),
                    started=False,
                )
        elif event["type"] == "RED_CARD" and player_id:
            pitch.pop(player_id, None)
    players = list(pitch.values())
    players.sort(key=lambda row: (not row.get("started"), str(row.get("shirt") or 99), str(row.get("name") or "")))
    return players


def iso_date(raw: Any) -> str:
    text = str(raw or "")
    return text[:10] if len(text) >= 10 else text


SET_PLAY_ACTIONS = {"PENALTY_KICK", "DIRECT_FREE_KICK"}


def classify_play_type(event: dict[str, Any]) -> str:
    """Set play vs open play. Open play is possession + transition."""
    action = str(event.get("action") or event.get("actionType") or "").upper()
    phase = str(event.get("phase") or "").upper()
    if action in SET_PLAY_ACTIONS:
        return "set_play"
    if event.get("inferredSetPiece") or event.get("setPiece"):
        return "set_play"
    if phase == "SET_PIECE":
        return "set_play"
    return "open_play"


def play_type_label(play_type: str) -> str:
    if play_type == "set_play":
        return "Set play"
    if play_type == "open_play":
        return "Open play"
    return ""


def extract_goals(
    *,
    match: dict[str, Any],
    vale_id: int,
    names: dict[int, str],
    season: str,
    competition: str,
    opponent: str,
    is_home: bool,
) -> list[dict[str, Any]]:
    match_id = int(match["id"])
    home_id = int(match.get("homeSquadId") or -1)
    away_id = int(match.get("awaySquadId") or -1)
    home_goals = 0
    away_goals = 0
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for event in fetch_events(match_id):
        action = str(event.get("action") or event.get("actionType") or "").upper()
        squad_id = int(event.get("squadId") or 0)
        game_time = event.get("gameTime") or {}
        minute = parse_minute(game_time) if isinstance(game_time, dict) else 0.0
        goal_seconds = clock_seconds(game_time) if isinstance(game_time, dict) else 0.0
        is_shot = str(event.get("actionType") or "").upper() == "SHOT"
        success_goal = str(event.get("result") or "").upper() == "SUCCESS" and action in {
            "GOAL",
            "SHOT",
            "OWN_GOAL",
        }
        if not ((is_shot and shot_outcome(event) == "goal") or ((not is_shot) and success_goal)):
            continue
        if "OWN_GOAL" in action:
            side = "conceded" if squad_id == vale_id else "scored"
        else:
            side = "scored" if squad_id == vale_id else "conceded"
        player = event.get("player") or {}
        scorer_id = int(player.get("id") or 0) or None
        # Impect logs a SHOT that went in and a GOAL event for the same finish.
        # Counting both doubled the cards and split clips across two ids.
        fingerprint = goal_fingerprint(
            match_id=match_id,
            side=side,
            minute=minute,
            scorer_id=scorer_id,
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        vale_before, opp_before = (home_goals, away_goals) if vale_id == home_id else (away_goals, home_goals)
        if squad_id == home_id:
            home_goals += 1
        elif squad_id == away_id:
            away_goals += 1
        vale_after, opp_after = (home_goals, away_goals) if vale_id == home_id else (away_goals, home_goals)
        scorer_name = event_player_name(event, names) if scorer_id else ""
        pitch = on_pitch(match_id, vale_id, goal_seconds, names)
        if scorer_id and side == "scored" and scorer_id not in {int(row["id"]) for row in pitch}:
            pitch.append(player_card(scorer_id, names))
        event_id = int(event.get("id") or event.get("eventId") or 0) or None
        out.append(
            {
                "id": f"g_{match_id}_{event_id or uuid.uuid4().hex[:8]}",
                "match_id": match_id,
                "event_id": event_id,
                "date": iso_date(match.get("scheduledDate")),
                "season": season,
                "competition": competition,
                "opponent": opponent,
                "is_home": int(bool(is_home)),
                "scoreline": f"{vale_after}-{opp_after}",
                "scoreline_before": f"{vale_before}-{opp_before}",
                "team_for_or_against": side,
                "minute": round(minute, 2),
                "minute_label": minute_label(minute),
                "scorer_id": scorer_id,
                "scorer_name": scorer_name,
                "players_on_pitch": json.dumps(pitch),
                "play_type": classify_play_type(event),
                "created_at": now(),
            }
        )
    return out


def goal_fingerprint(
    *,
    match_id: int,
    side: str,
    minute: float,
    scorer_id: int | None,
) -> tuple[Any, ...]:
    """Same finish in Impect, whether it arrived as a shot or a goal event."""
    return (int(match_id), str(side), round(float(minute or 0)), int(scorer_id or 0))


def row_fingerprint(goal: dict[str, Any]) -> tuple[Any, ...]:
    return goal_fingerprint(
        match_id=int(goal.get("match_id") or 0),
        side=str(goal.get("team_for_or_against") or ""),
        minute=float(goal.get("minute") or 0),
        scorer_id=int(goal.get("scorer_id") or 0) or None,
    )


def find_existing_goal(conn: sqlite3.Connection, goal: dict[str, Any]) -> dict[str, Any] | None:
    if goal.get("event_id"):
        row = conn.execute(
            "SELECT * FROM goals WHERE match_id = ? AND event_id = ?",
            (goal["match_id"], goal["event_id"]),
        ).fetchone()
        if row:
            return as_dict(row)
    row = conn.execute(
        """
        SELECT * FROM goals
        WHERE match_id = ?
          AND team_for_or_against = ?
          AND IFNULL(scorer_id, 0) = IFNULL(?, 0)
          AND abs(minute - ?) < 0.8
        ORDER BY created_at ASC
        """,
        (
            goal["match_id"],
            goal["team_for_or_against"],
            goal.get("scorer_id"),
            float(goal.get("minute") or 0),
        ),
    ).fetchone()
    return as_dict(row) if row else None


def merge_duplicate_goals(conn: sqlite3.Connection) -> int:
    """Fold shot+goal twins (and re-synced copies) into one row so clips stick."""
    rows = [as_dict(row) for row in conn.execute("SELECT * FROM goals").fetchall()]
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row_fingerprint(row), []).append(row)
    removed = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        def rank(row: dict[str, Any]) -> tuple[int, int, str]:
            clip = 1 if (row.get("clip_file") or row.get("clip_url")) else 0
            scores = conn.execute(
                "SELECT COUNT(*) AS n FROM goal_scores WHERE goal_id = ?",
                (row["id"],),
            ).fetchone()
            return (clip, int(scores["n"] if scores else 0), str(row.get("created_at") or ""))
        members.sort(key=rank, reverse=True)
        keeper = members[0]
        for loser in members[1:]:
            if not (keeper.get("clip_file") or keeper.get("clip_url")) and (
                loser.get("clip_file") or loser.get("clip_url")
            ):
                conn.execute(
                    """
                    UPDATE goals SET clip_file=?, clip_url=?, clip_added_at=?, clip_added_by=?
                    WHERE id=?
                    """,
                    (
                        loser.get("clip_file") or "",
                        loser.get("clip_url") or "",
                        loser.get("clip_added_at"),
                        loser.get("clip_added_by"),
                        keeper["id"],
                    ),
                )
            for score in conn.execute(
                "SELECT coach_id, player_id, points, submitted_at FROM goal_scores WHERE goal_id = ?",
                (loser["id"],),
            ).fetchall():
                already = conn.execute(
                    """
                    SELECT 1 FROM goal_scores
                    WHERE goal_id = ? AND coach_id = ? AND player_id = ?
                    """,
                    (keeper["id"], score["coach_id"], score["player_id"]),
                ).fetchone()
                if already:
                    continue
                conn.execute(
                    """
                    INSERT INTO goal_scores (goal_id, coach_id, player_id, points, submitted_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        keeper["id"],
                        score["coach_id"],
                        score["player_id"],
                        score["points"],
                        score["submitted_at"],
                    ),
                )
            conn.execute("DELETE FROM goal_scores WHERE goal_id = ?", (loser["id"],))
            conn.execute("DELETE FROM goals WHERE id = ?", (loser["id"],))
            removed += 1
    return removed


def upsert_goal(conn: sqlite3.Connection, goal: dict[str, Any]) -> str:
    existing = find_existing_goal(conn, goal)
    play_type = str(goal.get("play_type") or "")
    if existing:
        scored = conn.execute(
            "SELECT 1 FROM goal_scores WHERE goal_id = ? LIMIT 1", (existing["id"],)
        ).fetchone()
        if play_type:
            conn.execute("UPDATE goals SET play_type=? WHERE id=?", (play_type, existing["id"]))
        if not scored:
            conn.execute(
                """
                UPDATE goals SET date=?, season=?, competition=?, opponent=?, is_home=?,
                    scoreline=?, scoreline_before=?, team_for_or_against=?, minute=?,
                    minute_label=?, scorer_id=?, scorer_name=?, players_on_pitch=?,
                    event_id=COALESCE(event_id, ?)
                WHERE id=?
                """,
                (
                    goal["date"], goal["season"], goal["competition"], goal["opponent"],
                    goal["is_home"], goal["scoreline"], goal["scoreline_before"],
                    goal["team_for_or_against"], goal["minute"], goal["minute_label"],
                    goal["scorer_id"], goal["scorer_name"], goal["players_on_pitch"],
                    goal.get("event_id"),
                    existing["id"],
                ),
            )
        return str(existing["id"])
    conn.execute(
        """
        INSERT INTO goals (
            id, match_id, event_id, date, season, competition, opponent, is_home,
            scoreline, scoreline_before, team_for_or_against, minute, minute_label,
            scorer_id, scorer_name, players_on_pitch, status, created_at, play_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
        """,
        (
            goal["id"], goal["match_id"], goal["event_id"], goal["date"], goal["season"],
            goal["competition"], goal["opponent"], goal["is_home"], goal["scoreline"],
            goal["scoreline_before"], goal["team_for_or_against"], goal["minute"],
            goal["minute_label"], goal["scorer_id"], goal["scorer_name"],
            goal["players_on_pitch"], goal["created_at"], play_type,
        ),
    )
    return str(goal["id"])


def backfill_play_types(conn: sqlite3.Connection, *, season: str | None = None) -> int:
    """Fill set/open play on goals synced before we stored it."""
    sql = "SELECT id, match_id, event_id, minute, scorer_id FROM goals WHERE IFNULL(play_type, '') = ''"
    params: list[Any] = []
    if season:
        sql += " AND season = ?"
        params.append(season)
    rows = [as_dict(row) for row in conn.execute(sql, params).fetchall()]
    if not rows:
        return 0
    by_match: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_match.setdefault(int(row["match_id"]), []).append(row)
    updated = 0
    for match_id, goals in by_match.items():
        try:
            events = fetch_events(match_id)
        except Exception:
            continue
        by_id: dict[int, dict[str, Any]] = {}
        for event in events:
            eid = int(event.get("id") or event.get("eventId") or 0)
            if eid:
                by_id[eid] = event
        for goal in goals:
            event = by_id.get(int(goal["event_id"] or 0))
            if event is None:
                wanted = round(float(goal.get("minute") or 0))
                scorer = int(goal.get("scorer_id") or 0)
                for candidate in events:
                    player = candidate.get("player") or {}
                    cid = int(player.get("id") or 0)
                    game_time = candidate.get("gameTime") or {}
                    minute = parse_minute(game_time) if isinstance(game_time, dict) else 0.0
                    if scorer and cid == scorer and abs(float(minute) - wanted) < 0.8:
                        event = candidate
                        break
            if event is None:
                continue
            conn.execute(
                "UPDATE goals SET play_type=? WHERE id=?",
                (classify_play_type(event), goal["id"]),
            )
            updated += 1
    return updated


def iterations_for_season(season: str) -> list[tuple[int, str, str]]:
    """League only — coaches score league goals, cup ties are not compared."""
    iteration = resolve_iteration(season)
    return [
        (
            int(iteration["id"]),
            str(iteration.get("competition_name") or iteration.get("competition") or "League"),
            str(iteration.get("season") or season),
        )
    ]


def sync_season(season: str) -> dict[str, Any]:
    created = 0
    updated = 0
    matches_seen = 0
    errors: list[str] = []
    with db() as conn:
        merge_duplicate_goals(conn)
        for iteration_id, competition, season_label in iterations_for_season(season):
            try:
                vale_id = vale_squad_id(iteration_id)
                if not vale_id:
                    continue
                api = impect_mod()
                matches = unwrap(
                    api._impect_get(f"/v5/{api._api_prefix()}/iterations/{iteration_id}/matches")["data"]
                )
                squads = squads_map(iteration_id)
                fixtures = completed_fixtures(iteration_id, vale_id, squads, matches)
                by_id = {int(m["id"]): m for m in matches if m.get("id") is not None}
                names = player_names(iteration_id)
                for fixture in fixtures:
                    match_id = int(fixture.get("match_id") or fixture.get("matchId") or 0)
                    match = by_id.get(match_id)
                    if not match or not match_complete(match):
                        continue
                    matches_seen += 1
                    opponent = str((fixture.get("opponent") or {}).get("name") or "Opponent")
                    is_home = bool(fixture.get("is_home") if "is_home" in fixture else fixture.get("isHome"))
                    for goal in extract_goals(
                        match=match,
                        vale_id=vale_id,
                        names=names,
                        season=season_label,
                        competition=competition,
                        opponent=opponent,
                        is_home=is_home,
                    ):
                        before = conn.execute(
                            "SELECT id FROM goals WHERE match_id = ? AND event_id = ?",
                            (goal["match_id"], goal["event_id"]),
                        ).fetchone()
                        upsert_goal(conn, goal)
                        if before:
                            updated += 1
                        else:
                            created += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{competition}: {exc}")
        try:
            backfill_play_types(conn, season=season)
        except Exception:
            pass
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            ("last_sync_at", now()),
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            ("last_sync_season", season),
        )
    return {
        "ok": True,
        "skipped": False,
        "season": season,
        "matches": matches_seen,
        "goals_created": created,
        "goals_updated": updated,
        "errors": errors,
        "last_sync_at": now(),
    }


AUTO_SYNC_SECONDS = 8 * 60


def maybe_sync_season(season: str, *, force: bool = False) -> dict[str, Any]:
    """Skip Impect if we pulled this season a few minutes ago.

    Opening the app after a Vale match should just work; hammering the API
    every time someone switches tabs should not.
    """
    if not force:
        with db() as conn:
            last_at = setting(conn, "last_sync_at", "")
            last_season = setting(conn, "last_sync_season", "")
        if last_at and last_season == season:
            try:
                then = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
                age = (datetime.now(UTC) - then).total_seconds()
                if age < AUTO_SYNC_SECONDS:
                    return {
                        "ok": True,
                        "skipped": True,
                        "season": season,
                        "matches": 0,
                        "goals_created": 0,
                        "goals_updated": 0,
                        "errors": [],
                        "last_sync_at": last_at,
                    }
            except ValueError:
                pass
    return sync_season(season)


def submitted_ids(conn: sqlite3.Connection, goal_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT coach_id FROM goal_scores WHERE goal_id = ? ORDER BY coach_id",
        (goal_id,),
    ).fetchall()
    return [str(row["coach_id"]) for row in rows]


def score_rows(conn: sqlite3.Connection, goal_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT goal_id, coach_id, player_id, points, submitted_at FROM goal_scores WHERE goal_id = ?",
        (goal_id,),
    ).fetchall()
    return [as_dict(row) for row in rows]


def reveal_state(status: str, submitted: list[str], expected: int) -> dict[str, Any]:
    count = len(submitted)
    complete = status == "closed" or count >= expected
    return {
        "complete": complete,
        "revealed": complete,
        "submitted_count": count,
        "expected": expected,
        "remaining": max(0, expected - count),
    }


def public_goal(
    conn: sqlite3.Connection,
    goal: dict[str, Any],
    person: dict[str, Any],
    *,
    detail: bool = False,
) -> dict[str, Any]:
    cfg = settings(conn)
    expected = int(cfg["expected_coach_count"])
    threshold = float(cfg["disagreement_threshold"])
    players = parse_players(goal.get("players_on_pitch"))
    submitted = submitted_ids(conn, str(goal["id"]))
    reveal = reveal_state(str(goal.get("status") or "open"), submitted, expected)
    acting_id = str(person.get("coach_id") or "").casefold()
    mine = [
        row for row in score_rows(conn, str(goal["id"]))
        if acting_id and str(row["coach_id"]).casefold() == acting_id
    ]
    payload: dict[str, Any] = {
        "id": goal["id"],
        "match_id": goal["match_id"],
        "event_id": goal.get("event_id"),
        "date": goal.get("date"),
        "season": goal.get("season"),
        "competition": goal.get("competition"),
        "opponent": goal.get("opponent"),
        "is_home": bool(goal.get("is_home")),
        "venue": "Home" if goal.get("is_home") else "Away",
        "scoreline": goal.get("scoreline"),
        "scoreline_before": goal.get("scoreline_before"),
        "team_for_or_against": goal.get("team_for_or_against"),
        "side_label": "Scored" if goal.get("team_for_or_against") == "scored" else "Conceded",
        "points_label": "involvement" if goal.get("team_for_or_against") == "scored" else "responsibility",
        "minute": goal.get("minute"),
        "minute_label": goal.get("minute_label") or minute_label(float(goal.get("minute") or 0)),
        "scorer_id": goal.get("scorer_id"),
        "scorer_name": goal.get("scorer_name"),
        "players_on_pitch": players,
        "status": goal.get("status"),
        "closed_at": goal.get("closed_at"),
        "closed_by": goal.get("closed_by"),
        "close_note": goal.get("close_note"),
        "submitted_count": reveal["submitted_count"],
        "expected": expected,
        "remaining": reveal["remaining"],
        "complete": reveal["complete"],
        "revealed": reveal["revealed"],
        "i_have_scored": bool(mine),
        "scored_by": person.get("coach_id") or "",
        "quorum": int(cfg["quorum"]),
        # Who has filed is fair game; what they said is not.
        "submitted_coaches": submitted,
        "clip": clip_info(goal),
        "play_type": str(goal.get("play_type") or ""),
        "play_label": play_type_label(str(goal.get("play_type") or "")),
    }

    def attach_averages(*, include_spread: bool) -> None:
        scores = score_rows(conn, str(goal["id"]))
        coach_ids = submitted or [str(row["coach_id"]) for row in scores]
        ids = [int(row["id"]) for row in players]
        for row in scores:
            pid = int(row["player_id"])
            if pid not in ids:
                ids.append(pid)
        averages = average_player_scores(player_ids=ids, coach_ids=coach_ids, scores=scores)
        by_id = {int(row["id"]): row for row in players}
        for row in averages:
            info = by_id.get(int(row["player_id"])) or {}
            row["name"] = info.get("name") or f"Player {row['player_id']}"
            row["short_name"] = info.get("short_name") or surname(str(row["name"]))
            row["shirt"] = info.get("shirt")
            row["position"] = info.get("position")
            row["photo_url"] = info.get("photo_url") or f"/api/player-photo?name={row['name']}"
        payload["averages"] = averages
        payload["agreement"] = disagreement_summary(averages, threshold)
        if include_spread:
            payload["coach_scores"] = scores
            payload["coach_names"] = {row["id"]: row["display_name"] for row in coaches(conn)}

    if not detail:
        if reveal["revealed"]:
            attach_averages(include_spread=False)
            for row in payload.get("averages") or []:
                row.pop("by_coach", None)
        return payload
    payload["my_allocations"] = [
        {"player_id": int(row["player_id"]), "points": int(row["points"])} for row in mine
    ]
    # No admin bypass: the staff share one hub login, so an override would leak
    # every coach's numbers to every coach. Closing the goal is the way in.
    if reveal["revealed"]:
        attach_averages(include_spread=True)
    else:
        payload["averages"] = []
        payload["agreement"] = None
        payload["coach_scores"] = []
        payload["waiting_label"] = (
            f"Hidden until {expected} coaches submit ({reveal['submitted_count']}/{expected} in)."
        )
    return payload


def score_matrix(conn: sqlite3.Connection, *, season: str | None) -> dict[str, Any]:
    """Player × coach points for every goal — review board, not the scoring sheet."""
    cfg = settings(conn)
    expected = int(cfg["expected_coach_count"])
    threshold = float(cfg["disagreement_threshold"])
    staff = [row for row in coaches(conn) if row["active"]]
    coach_ids = [row["id"] for row in staff]
    goals_out: list[dict[str, Any]] = []
    for goal in list_goals(conn, season=season):
        players = parse_players(goal.get("players_on_pitch"))
        scores = score_rows(conn, str(goal["id"]))
        submitted = submitted_ids(conn, str(goal["id"]))
        reveal = reveal_state(str(goal.get("status") or "open"), submitted, expected)
        ids = [int(row["id"]) for row in players]
        for row in scores:
            pid = int(row["player_id"])
            if pid not in ids:
                ids.append(pid)
        averages = (
            average_player_scores(player_ids=ids, coach_ids=submitted, scores=scores)
            if submitted
            else [
                {
                    "player_id": pid,
                    "mean": 0.0,
                    "stdev": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "by_coach": {},
                }
                for pid in ids
            ]
        )
        by_id = {int(row["id"]): row for row in players}
        player_rows: list[dict[str, Any]] = []
        for row in averages:
            spread = round(float(row["max"]) - float(row["min"]), 3)
            flagged = len(submitted) >= 2 and (row["stdev"] >= threshold or spread >= MATRIX_SPREAD)
            by_coach: dict[str, float | None] = {}
            outliers: dict[str, bool] = {}
            for coach_id in coach_ids:
                if coach_id not in submitted:
                    by_coach[coach_id] = None
                    continue
                value = float(row["by_coach"].get(coach_id, 0))
                by_coach[coach_id] = value
                if len(submitted) >= 2 and abs(value - float(row["mean"])) >= MATRIX_CELL_DELTA:
                    outliers[coach_id] = True
            info = by_id.get(int(row["player_id"])) or {}
            name = str(info.get("name") or f"Player {row['player_id']}")
            player_rows.append(
                {
                    "player_id": row["player_id"],
                    "name": name,
                    "short_name": info.get("short_name") or surname(name),
                    "photo_url": info.get("photo_url") or f"/api/player-photo?name={name}",
                    "mean": row["mean"],
                    "stdev": row["stdev"],
                    "spread": spread,
                    "flagged": flagged,
                    "by_coach": by_coach,
                    "outliers": outliers,
                }
            )
        agreement = disagreement_summary(averages, threshold) if averages else None
        goals_out.append(
            {
                "id": goal["id"],
                "date": goal.get("date"),
                "opponent": goal.get("opponent"),
                "venue": "Home" if goal.get("is_home") else "Away",
                "scoreline": goal.get("scoreline"),
                "team_for_or_against": goal.get("team_for_or_against"),
                "side_label": "Scored" if goal.get("team_for_or_against") == "scored" else "Conceded",
                "minute_label": goal.get("minute_label") or minute_label(float(goal.get("minute") or 0)),
                "scorer_name": goal.get("scorer_name"),
                "status": goal.get("status"),
                "revealed": reveal["revealed"],
                "submitted": submitted,
                "submitted_count": reveal["submitted_count"],
                "expected": expected,
                "agreement": agreement,
                "players": player_rows,
                "play_type": str(goal.get("play_type") or ""),
                "play_label": play_type_label(str(goal.get("play_type") or "")),
            }
        )
    return {
        "season": season or "",
        "coaches": [{"id": row["id"], "display_name": row["display_name"]} for row in staff],
        "threshold": threshold,
        "cell_delta": MATRIX_CELL_DELTA,
        "goals": goals_out,
        "anomaly_count": len(
            [
                goal
                for goal in goals_out
                if (goal.get("agreement") or {}).get("flagged")
                or any(row.get("flagged") for row in goal.get("players") or [])
            ]
        ),
    }


def get_goal(conn: sqlite3.Connection, goal_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found.")
    return as_dict(row)


def list_goals(
    conn: sqlite3.Connection,
    *,
    season: str | None = None,
    side: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM goals WHERE 1=1"
    params: list[Any] = []
    if season:
        sql += " AND season = ?"
        params.append(season)
    if side in {"scored", "conceded"}:
        sql += " AND team_for_or_against = ?"
        params.append(side)
    if status in {"open", "closed"}:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY date DESC, minute DESC, id DESC"
    return [as_dict(row) for row in conn.execute(sql, params).fetchall()]


def player_dashboard(
    conn: sqlite3.Connection,
    *,
    season: str | None,
    date_from: str | None,
    date_to: str | None,
    competition: str | None,
    player_id: int | None = None,
    include_incomplete: bool = False,
    play_type: str | None = None,
) -> dict[str, Any]:
    cfg = settings(conn)
    expected = int(cfg["expected_coach_count"])
    threshold = float(cfg["disagreement_threshold"])
    sql = "SELECT * FROM goals WHERE 1=1"
    params: list[Any] = []
    if season:
        sql += " AND season = ?"
        params.append(season)
    if date_from:
        sql += " AND date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date <= ?"
        params.append(date_to)
    if competition:
        sql += " AND competition = ?"
        params.append(competition)
    if play_type in {"open_play", "set_play"}:
        sql += " AND play_type = ?"
        params.append(play_type)
    sql += " ORDER BY date ASC, minute ASC"
    people: dict[int, dict[str, Any]] = {}
    comps: set[str] = set()
    goals_counted = 0
    provisional_goals = 0
    for goal in [as_dict(row) for row in conn.execute(sql, params).fetchall()]:
        comps.add(str(goal.get("competition") or ""))
        submitted = submitted_ids(conn, str(goal["id"]))
        reveal = reveal_state(str(goal.get("status") or "open"), submitted, expected)
        if not reveal["revealed"] and not include_incomplete:
            continue
        if include_incomplete and not submitted:
            continue
        goals_counted += 1
        if not reveal["revealed"]:
            provisional_goals += 1
        scores = score_rows(conn, str(goal["id"]))
        pitch = parse_players(goal.get("players_on_pitch"))
        ids = [int(row["id"]) for row in pitch]
        for row in scores:
            if int(row["player_id"]) not in ids:
                ids.append(int(row["player_id"]))
        averages = average_player_scores(player_ids=ids, coach_ids=submitted, scores=scores)
        names = {int(row["id"]): row for row in pitch}
        agreement = disagreement_summary(averages, threshold)
        side = str(goal.get("team_for_or_against") or "scored")
        for row in averages:
            pid = int(row["player_id"])
            if player_id is not None and pid != player_id:
                continue
            info = names.get(pid) or {}
            name = str(info.get("name") or f"Player {pid}")
            bucket = people.setdefault(
                pid,
                {
                    "player_id": pid,
                    "name": name,
                    "short_name": info.get("short_name") or surname(name),
                    "photo_url": info.get("photo_url") or f"/api/player-photo?name={name}",
                    "scored_points": 0.0,
                    "conceded_points": 0.0,
                    "scored_goals": 0,
                    "conceded_goals": 0,
                    "timeline": [],
                },
            )
            pts_key = "scored_points" if side == "scored" else "conceded_points"
            n_key = "scored_goals" if side == "scored" else "conceded_goals"
            bucket[pts_key] = round(float(bucket[pts_key]) + float(row["mean"]), 3)
            if row["mean"] > 0:
                bucket[n_key] += 1
            bucket["timeline"].append(
                {
                    "goal_id": goal["id"],
                    "date": goal.get("date"),
                    "opponent": goal.get("opponent"),
                    "minute_label": goal.get("minute_label"),
                    "side": side,
                    "points": row["mean"],
                    "stdev": row["stdev"],
                    "flagged": agreement["flagged"],
                    "scoreline": goal.get("scoreline"),
                    "competition": goal.get("competition"),
                    "provisional": not reveal["revealed"],
                    "coaches_in": len(submitted),
                    "expected": expected,
                }
            )
    rows = []
    for row in people.values():
        row["total_points"] = round(float(row["scored_points"]) + float(row["conceded_points"]), 3)
        row["net_points"] = round(float(row["scored_points"]) - float(row["conceded_points"]), 3)
        # Nobody gave them a point all season — keeps the board about players who featured.
        if row["total_points"] <= 0:
            continue
        row["timeline"] = [item for item in row["timeline"] if float(item["points"]) > 0]
        rows.append(row)
        rows.sort(
            key=lambda item: (
                -float(item["net_points"]),
                -float(item["scored_points"]),
                str(item["name"]),
            )
        )
    return {
        "players": rows,
        "competitions": sorted(name for name in comps if name),
        "settings": cfg,
        "goals_counted": goals_counted,
        "provisional_goals": provisional_goals,
        "provisional": provisional_goals > 0,
    }


def overview(
    conn: sqlite3.Connection,
    goals: list[dict[str, Any]],
    coach_rows: list[dict[str, Any]],
    season: str | None,
    *,
    play_type: str | None = None,
) -> dict[str, Any]:
    active = [row for row in coach_rows if row["active"]]
    progress = coach_progress(conn, season)
    total = len(goals)
    revealed = [goal for goal in goals if goal["revealed"]]
    dashboard = player_dashboard(
        conn, season=season, date_from=None, date_to=None, competition=None, play_type=play_type
    )
    table = player_dashboard(
        conn,
        season=season,
        date_from=None,
        date_to=None,
        competition=None,
        include_incomplete=True,
        play_type=play_type,
    )
    players = dashboard.get("players") or []
    return {
        "total_goals": total,
        "scored_goals": len([goal for goal in goals if goal["team_for_or_against"] == "scored"]),
        "conceded_goals": len([goal for goal in goals if goal["team_for_or_against"] == "conceded"]),
        "to_score": len([goal for goal in goals if goal["status"] == "open" and not goal["i_have_scored"]]),
        "in_review": len(
            [goal for goal in goals if goal["status"] == "open" and goal["i_have_scored"] and not goal["revealed"]]
        ),
        "revealed": len(revealed),
        "flagged": len([goal for goal in revealed if (goal.get("agreement") or {}).get("flagged")]),
        "coach_progress": [
            {
                "id": row["id"],
                "display_name": row["display_name"],
                "scored": int(progress.get(row["id"], 0)),
                "total": total,
            }
            for row in active
        ],
        "table": table,
        "top_involvement": sorted(
            [row for row in players if float(row["scored_points"]) > 0],
            key=lambda row: -float(row["scored_points"]),
        )[:5],
        "top_responsibility": sorted(
            [row for row in players if float(row["conceded_points"]) > 0],
            key=lambda row: -float(row["conceded_points"]),
        )[:5],
    }


def bootstrap(
    conn: sqlite3.Connection,
    person: dict[str, Any],
    season: str | None,
    *,
    play_type: str | None = None,
) -> dict[str, Any]:
    seasons = [
        {"value": CURRENT_SEASON, "label": CURRENT_SEASON},
        {"value": "25/26", "label": "25/26"},
    ]
    chosen = season or CURRENT_SEASON
    merge_duplicate_goals(conn)
    try:
        backfill_play_types(conn, season=chosen)
    except Exception:
        pass
    coach_rows = coaches(conn)
    goals = [public_goal(conn, goal, person) for goal in list_goals(conn, season=chosen)]
    pending = [goal for goal in goals if not goal["i_have_scored"] and goal["status"] == "open"]
    users = [
        {
            "id": str(user.get("username") or ""),
            "display_name": str(user.get("display_name") or user.get("username") or ""),
            "role": str(user.get("role") or "analysis"),
        }
        for user in hub_users()
    ]
    wanted = play_type if play_type in {"open_play", "set_play"} else None
    return {
        "me": {
            **person,
            "can_score": can_score(conn, person),
        },
        "seasons": seasons,
        "season": chosen,
        "play_type": wanted or "all",
        "settings": settings(conn),
        "coaches": coach_rows,
        "hub_users": users if person["is_admin"] else [],
        "goals": goals,
        "squad": season_squad(conn, chosen),
        "overview": overview(conn, goals, coach_rows, chosen, play_type=wanted),
        "pending_count": len(pending),
        "points_pool": POINTS,
    }


def match_goals(conn: sqlite3.Connection, match_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM goals WHERE match_id = ? ORDER BY minute ASC, id ASC", (int(match_id),)
    ).fetchall()
    return [as_dict(row) for row in rows]


def unranked_goals(
    conn: sqlite3.Connection, coach_id: str, season: str | None = None
) -> list[dict[str, Any]]:
    """Open goals this coach has not scored yet, oldest game first.

    Scoped to one season deliberately — without it a coach who joins midway
    gets handed every unscored goal we have ever logged.
    """
    rows = conn.execute(
        """
        SELECT g.* FROM goals g
        WHERE g.status = 'open'
          AND g.season = ?
          AND NOT EXISTS (
            SELECT 1 FROM goal_scores s WHERE s.goal_id = g.id AND s.coach_id = ?
          )
        ORDER BY g.date ASC, g.minute ASC, g.id ASC
        """,
        (season or CURRENT_SEASON, coach_id),
    ).fetchall()
    return [as_dict(row) for row in rows]


def matches_for_links(conn: sqlite3.Connection, season: str | None) -> list[dict[str, Any]]:
    """One row per match, newest first, with how much scoring is outstanding."""
    out: dict[int, dict[str, Any]] = {}
    for goal in list_goals(conn, season=season):
        match_id = int(goal["match_id"])
        bucket = out.setdefault(
            match_id,
            {
                "match_id": match_id,
                "date": goal.get("date"),
                "opponent": goal.get("opponent"),
                "venue": "Home" if goal.get("is_home") else "Away",
                "competition": goal.get("competition"),
                "season": goal.get("season"),
                "goals": 0,
                "open_goals": 0,
            },
        )
        bucket["goals"] += 1
        if str(goal.get("status") or "open") == "open":
            bucket["open_goals"] += 1
    rows = list(out.values())
    rows.sort(key=lambda row: (str(row["date"] or ""), row["match_id"]), reverse=True)
    return rows


def scoring_link_rows(
    conn: sqlite3.Connection, *, match_id: int, base_url: str
) -> list[dict[str, Any]]:
    goals = match_goals(conn, match_id)
    total = len(goals)
    rows = []
    for coach in coaches(conn):
        if not coach["active"]:
            continue
        done = 0
        for goal in goals:
            if coach["id"] in submitted_ids(conn, str(goal["id"])):
                done += 1
        code = link_code(conn, coach_id=coach["id"], match_id=match_id)
        url = f"{base_url}/gi/{code}"
        first = goals[0] if goals else {}
        opponent = str(first.get("opponent") or "the game")
        outstanding_count = max(0, total - done)
        message = (
            f"{first_name(coach['display_name'])}, "
            f"{outstanding_count or total} goal{'s' if (outstanding_count or total) != 1 else ''} "
            f"to score from {opponent}{friendly_date(first.get('date'))}. "
            f"Tap the link and give out 10 points"
            f"{' on each' if (outstanding_count or total) != 1 else ''} — takes a minute:\n{url}"
        )
        number = wa_number(coach["phone"])
        rows.append(
            {
                **coach,
                "url": url,
                "message": message,
                "whatsapp_url": (
                    f"https://wa.me/{number}?text={quote(message)}" if number else ""
                ),
                "whatsapp_ready": bool(number),
                "done": done,
                "total": total,
                "outstanding": max(0, total - done),
            }
        )
    return rows


def send_out(conn: sqlite3.Connection, *, base_url: str, season: str | None = None) -> dict[str, Any]:
    """One tap on a Sunday: who still owes scores, and the message to send them."""
    use_season = season or CURRENT_SEASON
    rows: list[dict[str, Any]] = []
    fixtures: dict[int, dict[str, Any]] = {}
    for coach in coaches(conn):
        if not coach["active"]:
            continue
        owed = unranked_goals(conn, coach["id"], use_season)
        if not owed:
            rows.append({**coach, "outstanding": 0, "url": "", "message": "", "whatsapp_url": "", "whatsapp_ready": False, "games": []})
            continue

        games: list[str] = []
        for goal in owed:
            match_id = int(goal["match_id"])
            fixtures.setdefault(
                match_id,
                {
                    "match_id": match_id,
                    "date": goal.get("date"),
                    "opponent": goal.get("opponent"),
                    "venue": "Home" if goal.get("is_home") else "Away",
                },
            )
            label = str(goal.get("opponent") or "")
            if label not in games:
                games.append(label)

        code = link_code(conn, coach_id=coach["id"], match_id=ALL_OUTSTANDING)
        url = f"{base_url}/gi/{code}"
        count = len(owed)
        plural = "s" if count != 1 else ""
        if len(games) == 1:
            where = f"from {games[0]}{friendly_date(owed[0].get('date'))}"
        else:
            where = "from " + " and ".join(games)
        message = (
            f"{first_name(coach['display_name'])}, {count} goal{plural} to score {where}. "
            f"Tap the link and give out 10 points{' on each' if count != 1 else ''} "
            f"— takes a minute:\n{url}"
        )
        number = wa_number(coach["phone"])
        rows.append(
            {
                **coach,
                "outstanding": count,
                "games": games,
                "url": url,
                "message": message,
                "whatsapp_url": f"https://wa.me/{number}?text={quote(message)}" if number else "",
                "whatsapp_ready": bool(number),
            }
        )

    waiting = [row for row in rows if row["outstanding"]]
    fixture_rows = sorted(fixtures.values(), key=lambda row: str(row["date"] or ""), reverse=True)
    older = conn.execute(
        "SELECT COUNT(*) n FROM goals WHERE status = 'open' AND season <> ?", (use_season,)
    ).fetchone()["n"]
    return {
        "season": use_season,
        "coaches": rows,
        "waiting": waiting,
        "nothing_to_send": not waiting,
        "fixtures": fixture_rows,
        "goals_outstanding": max((row["outstanding"] for row in rows), default=0),
        "older_unranked": int(older or 0),
        "base_url": base_url,
        "secure": base_url.startswith("https://"),
    }


def token_payload(conn: sqlite3.Connection, claim: dict[str, Any]) -> dict[str, Any]:
    """Everything the phone-only scoring page needs, scoped to one coach + match."""
    coach = next(
        (row for row in coaches(conn) if row["id"] == claim["coach_id"] and row["active"]),
        None,
    )
    if not coach:
        raise HTTPException(status_code=403, detail="That scoring link is no longer active.")
    person = {
        "id": coach["id"],
        "display_name": coach["display_name"],
        "role": "coach",
        "is_admin": False,
        "coach_id": coach["id"],
        "coach_name": coach["display_name"],
        "is_listed_coach": True,
    }
    match_id = int(claim["match_id"])
    source = (
        unranked_goals(conn, coach["id"])
        if match_id == ALL_OUTSTANDING
        else match_goals(conn, match_id)
    )
    goals = [public_goal(conn, goal, person, detail=True) for goal in source]
    for goal in goals:
        # A coach on a link never sees anyone else's numbers, revealed or not.
        goal.pop("averages", None)
        goal.pop("agreement", None)
        goal.pop("coach_scores", None)
        goal.pop("coach_names", None)
        goal.pop("submitted_coaches", None)
    first = goals[0] if goals else {}
    fixtures = {int(goal["match_id"]) for goal in goals}
    return {
        "coach": {"id": coach["id"], "display_name": coach["display_name"]},
        "match": {
            "match_id": match_id,
            "date": first.get("date"),
            "opponent": first.get("opponent"),
            "venue": first.get("venue"),
            "competition": first.get("competition"),
        },
        # More than one fixture on a link means the header cannot name the game,
        # so the page labels each goal instead.
        "multi_match": len(fixtures) > 1,
        "goals": goals,
        "squad": season_squad(conn, str(first.get("season") or "") or None),
        "points_pool": POINTS,
        "expires_at": claim["exp"],
    }


def claim_or_403(conn: sqlite3.Connection, token: str) -> dict[str, Any]:
    # Short codes are what we send now; the long signed tokens stay valid so
    # links already sitting in someone's WhatsApp keep working.
    claim = resolve_link(conn, token) or parse_scoring_token(token)
    if not claim:
        raise HTTPException(status_code=403, detail="That scoring link is invalid or has expired.")
    return claim


def register_goal_involvement_routes(app: FastAPI) -> None:
    @app.get("/goal-involvement")
    def page() -> FileResponse:
        return FileResponse(STANDALONE_DIR / "goal-involvement.html")

    # ---- Tokenised coach links (no hub login; see PUBLIC_PREFIXES in app/auth.py) ----

    @app.get("/gi/{token}")
    def link_page(token: str) -> FileResponse:
        with db() as conn:
            claim_or_403(conn, token)
        return FileResponse(STANDALONE_DIR / "goal-involvement-link.html")

    @app.get("/api/gi/{token}")
    def link_data(token: str) -> dict[str, Any]:
        with db() as conn:
            return token_payload(conn, claim_or_403(conn, token))

    @app.put("/api/gi/{token}/goals/{goal_id}/score")
    def link_score(token: str, goal_id: str, body: ScoreBody) -> dict[str, Any]:
        total = allocation_total(body.allocations)
        if total != POINTS:
            raise HTTPException(status_code=400, detail=f"Points must add up to {POINTS} (you have {total}).")
        with db() as conn:
            claim = claim_or_403(conn, token)
            goal = get_goal(conn, goal_id)
            if int(claim["match_id"]) not in (ALL_OUTSTANDING, int(goal["match_id"])):
                raise HTTPException(status_code=403, detail="That goal is not on this link.")
            if str(goal.get("status") or "open") == "closed":
                raise HTTPException(status_code=409, detail="This goal is closed for scoring.")
            allowed = {int(row["id"]) for row in parse_players(goal.get("players_on_pitch"))}
            cleaned: dict[int, int] = {}
            for row in body.allocations:
                if row.player_id not in allowed:
                    raise HTTPException(status_code=400, detail="That player was not on the pitch for this goal.")
                if row.points:
                    cleaned[int(row.player_id)] = cleaned.get(int(row.player_id), 0) + int(row.points)
            if sum(cleaned.values()) != POINTS:
                raise HTTPException(status_code=400, detail=f"Points must add up to {POINTS}.")
            coach = str(claim["coach_id"])
            conn.execute("DELETE FROM goal_scores WHERE goal_id = ? AND coach_id = ?", (goal_id, coach))
            when = now()
            for player_id, points in cleaned.items():
                conn.execute(
                    """
                    INSERT INTO goal_scores (goal_id, coach_id, player_id, points, submitted_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (goal_id, coach, player_id, points, when),
                )
            return token_payload(conn, claim)

    @app.get("/api/gi/{token}/goals/{goal_id}/clip")
    def link_clip(token: str, goal_id: str) -> FileResponse:
        with db() as conn:
            claim = claim_or_403(conn, token)
            goal = get_goal(conn, goal_id)
            # A link reaches its own goals' clips and nothing else.
            if int(claim["match_id"]) not in (ALL_OUTSTANDING, int(goal["match_id"])):
                raise HTTPException(status_code=403, detail="That goal is not on this link.")
            if int(claim["match_id"]) == ALL_OUTSTANDING:
                owed = {row["id"] for row in unranked_goals(conn, str(claim["coach_id"]))}
                if goal_id not in owed:
                    raise HTTPException(status_code=403, detail="That goal is not on this link.")
            return clip_response(goal)

    @app.post("/api/gi/{token}/goals/{goal_id}/players")
    def link_add_player(token: str, goal_id: str, body: AddPlayerBody) -> dict[str, Any]:
        with db() as conn:
            claim = claim_or_403(conn, token)
            goal = get_goal(conn, goal_id)
            if int(claim["match_id"]) not in (ALL_OUTSTANDING, int(goal["match_id"])):
                raise HTTPException(status_code=403, detail="That goal is not on this link.")
            pitch = parse_players(goal.get("players_on_pitch"))
            if int(body.player_id) not in {int(row["id"]) for row in pitch}:
                squad = {
                    int(row["id"]): row
                    for row in season_squad(conn, str(goal.get("season") or "") or None)
                }
                player = squad.get(int(body.player_id))
                if not player:
                    raise HTTPException(status_code=404, detail="That player is not in the squad list.")
                pitch.append({**player, "started": False, "added_by": claim["coach_id"]})
                conn.execute(
                    "UPDATE goals SET players_on_pitch=? WHERE id=?", (json.dumps(pitch), goal_id)
                )
            return token_payload(conn, claim)

    @app.get("/api/goal-involvement/bootstrap")
    def bootstrap_route(
        request: Request,
        season: str | None = Query(None),
        coach_id: str | None = Query(None),
        play_type: str | None = Query(None),
    ) -> dict[str, Any]:
        with db() as conn:
            person = acting(conn, actor(request), coach_id)
            return bootstrap(conn, person, season, play_type=play_type)

    @app.get("/api/goal-involvement/goals")
    def list_route(
        request: Request,
        season: str | None = Query(None),
        side: str | None = Query(None),
        status: str | None = Query(None),
        coach_id: str | None = Query(None),
    ) -> dict[str, Any]:
        with db() as conn:
            person = acting(conn, actor(request), coach_id)
            return {
                "goals": [
                    public_goal(conn, goal, person)
                    for goal in list_goals(conn, season=season, side=side, status=status)
                ]
            }

    @app.get("/api/goal-involvement/goals/{goal_id}")
    def detail_route(
        request: Request, goal_id: str, coach_id: str | None = Query(None)
    ) -> dict[str, Any]:
        with db() as conn:
            person = acting(conn, actor(request), coach_id)
            return public_goal(conn, get_goal(conn, goal_id), person, detail=True)

    @app.post("/api/goal-involvement/goals/{goal_id}/players")
    def add_player_route(
        request: Request,
        goal_id: str,
        body: AddPlayerBody,
        coach_id: str | None = Query(None),
    ) -> dict[str, Any]:
        with db() as conn:
            person = acting(conn, actor(request), coach_id)
            if not can_score(conn, person):
                raise HTTPException(status_code=403, detail="Pick which coach you are first.")
            goal = get_goal(conn, goal_id)
            pitch = parse_players(goal.get("players_on_pitch"))
            if int(body.player_id) in {int(row["id"]) for row in pitch}:
                return public_goal(conn, goal, person, detail=True)
            squad = {int(row["id"]): row for row in season_squad(conn, str(goal.get("season") or "") or None)}
            player = squad.get(int(body.player_id))
            if not player:
                raise HTTPException(status_code=404, detail="That player is not in the squad list.")
            pitch.append({**player, "started": False, "added_by": person["coach_id"]})
            conn.execute("UPDATE goals SET players_on_pitch=? WHERE id=?", (json.dumps(pitch), goal_id))
            return public_goal(conn, get_goal(conn, goal_id), person, detail=True)

    @app.put("/api/goal-involvement/goals/{goal_id}/score")
    def score_route(request: Request, goal_id: str, body: ScoreBody) -> dict[str, Any]:
        total = allocation_total(body.allocations)
        if total != POINTS:
            raise HTTPException(status_code=400, detail=f"Points must add up to {POINTS} (you have {total}).")
        with db() as conn:
            person = acting(conn, actor(request), body.coach_id)
            if not can_score(conn, person):
                raise HTTPException(status_code=403, detail="Pick which coach you are before submitting.")
            goal = get_goal(conn, goal_id)
            if str(goal.get("status") or "open") == "closed" and not person.get("is_admin"):
                raise HTTPException(status_code=409, detail="This goal is closed for scoring.")
            allowed = {int(row["id"]) for row in parse_players(goal.get("players_on_pitch"))}
            if not allowed:
                raise HTTPException(status_code=409, detail="No on-pitch list for this goal yet.")
            cleaned: dict[int, int] = {}
            for row in body.allocations:
                if row.player_id not in allowed:
                    raise HTTPException(status_code=400, detail="That player was not on the pitch for this goal.")
                if row.points:
                    cleaned[int(row.player_id)] = cleaned.get(int(row.player_id), 0) + int(row.points)
            if sum(cleaned.values()) != POINTS:
                raise HTTPException(status_code=400, detail=f"Points must add up to {POINTS}.")
            coach = str(person["coach_id"])
            conn.execute("DELETE FROM goal_scores WHERE goal_id = ? AND coach_id = ?", (goal_id, coach))
            when = now()
            for player_id, points in cleaned.items():
                conn.execute(
                    """
                    INSERT INTO goal_scores (goal_id, coach_id, player_id, points, submitted_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (goal_id, coach, player_id, points, when),
                )
            return public_goal(conn, get_goal(conn, goal_id), person, detail=True)

    @app.get("/api/goal-involvement/goals/{goal_id}/clip")
    def clip_stream_route(request: Request, goal_id: str) -> FileResponse:
        with db() as conn:
            acting(conn, actor(request), None)
            return clip_response(get_goal(conn, goal_id))

    @app.post("/api/goal-involvement/goals/{goal_id}/clip")
    async def clip_attach_route(
        request: Request,
        goal_id: str,
        file: UploadFile | None = File(None),
        url: str = Form(""),
    ) -> dict[str, Any]:
        with db() as conn:
            person = acting(conn, actor(request), None)
            require_admin(person)
            goal = get_goal(conn, goal_id)
        link = str(url or "").strip()
        if file is not None and file.filename:
            blob = await file.read()
            stored = store_clip(goal_id, filename=file.filename, blob=blob)
            with db() as conn:
                conn.execute(
                    "UPDATE goals SET clip_file=?, clip_url='', clip_added_at=?, clip_added_by=? WHERE id=?",
                    (stored, now(), person["id"], goal_id),
                )
                return public_goal(conn, get_goal(conn, goal_id), person, detail=True)
        if link:
            if not re.match(r"^https?://", link, re.I):
                raise HTTPException(status_code=400, detail="Clip links must start with http:// or https://.")
            with db() as conn:
                drop_clip(goal)
                conn.execute(
                    "UPDATE goals SET clip_file='', clip_url=?, clip_added_at=?, clip_added_by=? WHERE id=?",
                    (link, now(), person["id"], goal_id),
                )
                return public_goal(conn, get_goal(conn, goal_id), person, detail=True)
        raise HTTPException(status_code=400, detail="Attach a video file or paste a link.")

    @app.delete("/api/goal-involvement/goals/{goal_id}/clip")
    def clip_remove_route(request: Request, goal_id: str) -> dict[str, Any]:
        with db() as conn:
            person = acting(conn, actor(request), None)
            require_admin(person)
            goal = get_goal(conn, goal_id)
            drop_clip(goal)
            conn.execute(
                "UPDATE goals SET clip_file='', clip_url='', clip_added_at=NULL, clip_added_by=NULL WHERE id=?",
                (goal_id,),
            )
            return public_goal(conn, get_goal(conn, goal_id), person, detail=True)

    @app.post("/api/goal-involvement/goals/{goal_id}/close")
    def close_route(request: Request, goal_id: str, body: CloseBody) -> dict[str, Any]:
        with db() as conn:
            person = acting(conn, actor(request), None)
            require_admin(person)
            get_goal(conn, goal_id)
            conn.execute(
                "UPDATE goals SET status='closed', closed_at=?, closed_by=?, close_note=? WHERE id=?",
                (now(), person["id"], body.note.strip(), goal_id),
            )
            return public_goal(conn, get_goal(conn, goal_id), person, detail=True)

    @app.post("/api/goal-involvement/goals/{goal_id}/reopen")
    def reopen_route(request: Request, goal_id: str) -> dict[str, Any]:
        with db() as conn:
            person = acting(conn, actor(request), None)
            require_admin(person)
            get_goal(conn, goal_id)
            conn.execute(
                "UPDATE goals SET status='open', closed_at=NULL, closed_by=NULL, close_note=NULL WHERE id=?",
                (goal_id,),
            )
            return public_goal(conn, get_goal(conn, goal_id), person, detail=True)

    @app.delete("/api/goal-involvement/goals/{goal_id}/scores")
    def reset_route(request: Request, goal_id: str) -> dict[str, Any]:
        with db() as conn:
            person = acting(conn, actor(request), None)
            require_admin(person)
            get_goal(conn, goal_id)
            conn.execute("DELETE FROM goal_scores WHERE goal_id = ?", (goal_id,))
            return public_goal(conn, get_goal(conn, goal_id), person, detail=True)

    @app.patch("/api/goal-involvement/goals/{goal_id}/players")
    def players_route(request: Request, goal_id: str, body: PlayersBody) -> dict[str, Any]:
        with db() as conn:
            person = acting(conn, actor(request), None)
            require_admin(person)
            goal = get_goal(conn, goal_id)
            names: dict[int, str] = {}
            try:
                iteration = resolve_iteration(str(goal.get("season") or "") or None)
                names = player_names(int(iteration["id"]))
            except Exception:
                names = {}
            existing = {int(row["id"]): row for row in parse_players(goal.get("players_on_pitch"))}
            merged = []
            seen: set[int] = set()
            for player_id in body.player_ids:
                pid = int(player_id)
                if pid in seen:
                    continue
                seen.add(pid)
                merged.append(existing.get(pid) or player_card(pid, names))
            conn.execute("UPDATE goals SET players_on_pitch=? WHERE id=?", (json.dumps(merged), goal_id))
            return public_goal(conn, get_goal(conn, goal_id), person, detail=True)

    @app.get("/api/goal-involvement/players")
    def players_table(
        season: str | None = Query(None),
        date_from: str | None = Query(None, alias="from"),
        date_to: str | None = Query(None, alias="to"),
        competition: str | None = Query(None),
    ) -> dict[str, Any]:
        with db() as conn:
            return player_dashboard(
                conn, season=season, date_from=date_from, date_to=date_to, competition=competition
            )

    @app.get("/api/goal-involvement/players/{player_id}")
    def player_detail(
        player_id: int,
        season: str | None = Query(None),
        date_from: str | None = Query(None, alias="from"),
        date_to: str | None = Query(None, alias="to"),
        competition: str | None = Query(None),
    ) -> dict[str, Any]:
        with db() as conn:
            payload = player_dashboard(
                conn,
                season=season,
                date_from=date_from,
                date_to=date_to,
                competition=competition,
                player_id=player_id,
            )
        rows = payload.get("players") or []
        if not rows:
            raise HTTPException(status_code=404, detail="No completed scores for this player yet.")
        return {"player": rows[0], "competitions": payload.get("competitions") or []}

    @app.get("/api/goal-involvement/admin")
    def admin_route(request: Request, season: str | None = Query(None)) -> dict[str, Any]:
        with db() as conn:
            person = acting(conn, actor(request), None)
            require_admin(person)
            coach_rows = coaches(conn)
            matrix = []
            for goal in list_goals(conn, season=season):
                submitted = set(submitted_ids(conn, str(goal["id"])))
                matrix.append(
                    {
                        **public_goal(conn, goal, person),
                        "by_coach": {row["id"]: row["id"] in submitted for row in coach_rows if row["active"]},
                    }
                )
            users = [
                {
                    "id": str(user.get("username") or ""),
                    "display_name": str(user.get("display_name") or user.get("username") or ""),
                    "role": str(user.get("role") or "analysis"),
                }
                for user in hub_users()
            ]
            return {
                "settings": settings(conn),
                "coaches": coach_rows,
                "hub_users": users,
                "goals": matrix,
                "preview": player_dashboard(
                    conn,
                    season=season,
                    date_from=None,
                    date_to=None,
                    competition=None,
                    include_incomplete=True,
                ),
            }

    @app.get("/api/goal-involvement/matrix")
    def matrix_route(request: Request, season: str | None = Query(None)) -> dict[str, Any]:
        with db() as conn:
            acting(conn, actor(request), None)
            return score_matrix(conn, season=season)

    @app.get("/api/goal-involvement/send-out")
    def send_out_route(request: Request, season: str | None = Query(None)) -> dict[str, Any]:
        with db() as conn:
            require_admin(acting(conn, actor(request), None))
            return send_out(conn, base_url=link_base_url(request), season=season)

    @app.get("/api/goal-involvement/links")
    def links_route(
        request: Request,
        season: str | None = Query(None),
        match_id: int | None = Query(None),
    ) -> dict[str, Any]:
        with db() as conn:
            person = acting(conn, actor(request), None)
            require_admin(person)
            matches = matches_for_links(conn, season)
            chosen = int(match_id) if match_id else (matches[0]["match_id"] if matches else 0)
            rows = (
                scoring_link_rows(conn, match_id=chosen, base_url=link_base_url(request))
                if chosen
                else []
            )
            match = next((row for row in matches if row["match_id"] == chosen), None)
            return {
                "matches": matches,
                "match_id": chosen,
                "match": match,
                "coaches": rows,
                "base_url": link_base_url(request),
                "secure": link_base_url(request).startswith("https://"),
            }

    @app.put("/api/goal-involvement/coaches")
    def save_coaches(request: Request, body: CoachesBody) -> dict[str, Any]:
        person = actor(request)
        require_admin(person)
        with db() as conn:
            conn.execute("DELETE FROM coaches")
            when = now()
            for index, coach in enumerate(body.coaches):
                coach_id = coach.id.strip()
                if not coach_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO coaches (id, display_name, active, sort_order, created_at, phone, email)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        coach_id,
                        coach.display_name.strip() or coach_id,
                        1 if coach.active else 0,
                        coach.sort_order or index,
                        when,
                        coach.phone.strip(),
                        coach.email.strip(),
                    ),
                )
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", ("expected_coach_count", str(body.expected_coach_count)))
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", ("quorum", str(body.quorum)))
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", ("disagreement_threshold", str(body.disagreement_threshold)))
            return {"ok": True, "coaches": coaches(conn), "settings": settings(conn)}

    @app.post("/api/goal-involvement/sync")
    def sync_route(
        request: Request,
        season: str | None = Query(None),
        force: bool = Query(False),
    ) -> dict[str, Any]:
        person = actor(request)
        require_admin(person)
        chosen = season or "26/27"
        if not chosen:
            raise HTTPException(status_code=400, detail="No Port Vale season available.")
        return maybe_sync_season(chosen, force=force)

    @app.get("/api/goal-involvement/fixtures")
    def fixtures_route(season: str | None = Query(None)) -> dict[str, Any]:
        from app.xg_chance_analysis import build_xg_chance_fixtures

        return {"fixtures": build_xg_chance_fixtures(season)}

    @app.post("/api/goal-involvement/goals")
    def manual_route(request: Request, body: ManualGoalBody) -> dict[str, Any]:
        person = actor(request)
        require_admin(person)
        side = body.team_for_or_against.strip().lower()
        if side not in {"scored", "conceded"}:
            raise HTTPException(status_code=400, detail="team_for_or_against must be scored or conceded.")
        season = default_season()
        iteration = resolve_iteration(season)
        iteration_id = int(iteration["id"])
        names = player_names(iteration_id)
        vale_id = vale_squad_id(iteration_id)
        if not vale_id:
            raise HTTPException(status_code=400, detail="Port Vale squad not found.")
        pitch = on_pitch(body.match_id, vale_id, float(body.minute) * 60.0, names)
        if body.player_ids:
            have = {int(row["id"]) for row in pitch}
            for player_id in body.player_ids:
                if int(player_id) not in have:
                    pitch.append(player_card(int(player_id), names))
        opponent = "Opponent"
        is_home = True
        match_date = datetime.now(UTC).strftime("%Y-%m-%d")
        try:
            detail = fetch_match_detail(body.match_id)
            home_id = int(detail.get("homeSquadId") or -1)
            away_id = int(detail.get("awaySquadId") or -1)
            is_home = home_id == vale_id
            squads = squads_map(iteration_id)
            opp_id = away_id if is_home else home_id
            opponent = str((squads.get(opp_id) or {}).get("name") or "Opponent")
            match_date = iso_date(detail.get("scheduledDate")) or match_date
        except Exception:
            pass
        goal_id = f"manual_{uuid.uuid4().hex[:10]}"
        with db() as conn:
            conn.execute(
                """
                INSERT INTO goals (
                    id, match_id, event_id, date, season, competition, opponent, is_home,
                    scoreline, scoreline_before, team_for_or_against, minute, minute_label,
                    scorer_id, scorer_name, players_on_pitch, status, created_at
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, '', '', ?, ?, ?, NULL, ?, ?, 'open', ?)
                """,
                (
                    goal_id, body.match_id, match_date, str(iteration.get("season") or season),
                    str(iteration.get("competition_name") or "League"), opponent, int(is_home),
                    side, float(body.minute), minute_label(float(body.minute)), body.scorer_name.strip(),
                    json.dumps(pitch), now(),
                ),
            )
            return public_goal(conn, get_goal(conn, goal_id), person, detail=True)
