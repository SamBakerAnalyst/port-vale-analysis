"""On-disk player name index for the all-leagues `/api/players` search.

Search reads only this index — no Impect calls while a user types. The index is
rebuilt in the background when missing or older than `INDEX_MAX_AGE_SECONDS`.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from typing import Any

from app.paths import CACHE_ROOT

logger = logging.getLogger("impect.dashboard")

INDEX_PATH = CACHE_ROOT / "player-search-index.json"
INDEX_MAX_AGE_SECONDS = 6 * 3600
INCOMPLETE_INDEX_MAX_AGE_SECONDS = 600
BUILD_ATTEMPTS = 4
BUILD_RETRY_DELAY_SECONDS = 45
INDEX_VERSION = 2

_lock = threading.Lock()
_build_lock = threading.Lock()
_index: dict[str, Any] | None = None


def _load_from_disk() -> dict[str, Any] | None:
    try:
        payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("version") != INDEX_VERSION or not payload.get("players"):
        return None
    return _prepare(payload)


def _prepare(payload: dict[str, Any]) -> dict[str, Any]:
    payload["label_map"] = {int(k): v for k, v in payload["label_map"].items()}
    payload["iteration_meta"] = {int(k): v for k, v in payload["iteration_meta"].items()}
    payload["squad_names"] = {
        int(it): {int(sq): name for sq, name in names.items()}
        for it, names in payload["squad_names"].items()
    }
    payload["names_lower"] = [p["name"].lower() for p in payload["players"]]
    payload["by_id"] = {int(p["impect_player_id"]): p for p in payload["players"]}
    return payload


def _current() -> dict[str, Any] | None:
    global _index
    with _lock:
        if _index is None:
            _index = _load_from_disk()
        return _index


def build_index() -> dict[str, Any]:
    from app import main as m

    iteration_ids = m._catalog_iteration_ids(None, "index")
    players_by_iteration: dict[int, list[dict[str, Any]]] = {}
    missing = list(iteration_ids)
    for attempt in range(BUILD_ATTEMPTS):
        if attempt:
            time.sleep(BUILD_RETRY_DELAY_SECONDS)
        fetched = m._fetch_players_parallel(missing)
        players_by_iteration.update({k: v for k, v in fetched.items() if v})
        missing = [it for it in iteration_ids if not players_by_iteration.get(it)]
        if not missing:
            break
    if not players_by_iteration:
        raise RuntimeError("Impect returned no players for the search index.")
    merged = m._merge_player_options(iteration_ids, players_by_iteration)
    squad_names: dict[int, dict[int, str]] = {}
    for iteration_id in iteration_ids:
        try:
            squad_names[iteration_id] = m._fetch_squad_names(iteration_id)
        except Exception:
            squad_names[iteration_id] = {}
    payload = {
        "version": INDEX_VERSION,
        "built_at": time.time(),
        "iteration_ids": iteration_ids,
        "missing_iteration_ids": missing,
        "label_map": m._iteration_label_map(iteration_ids),
        "iteration_meta": m._iteration_meta_map(),
        "squad_names": squad_names,
        "players": merged,
    }
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, INDEX_PATH)
    prepared = _prepare(json.loads(json.dumps(payload)))
    global _index
    with _lock:
        _index = prepared
    logger.info(
        "Player search index built: %s players across %s seasons (%s missing)",
        len(merged),
        len(iteration_ids),
        len(missing),
    )
    return prepared


def _build_in_background() -> None:
    if not _build_lock.acquire(blocking=False):
        return

    def run() -> None:
        try:
            build_index()
        except Exception:
            logger.exception("Player search index build failed")
        finally:
            _build_lock.release()

    threading.Thread(target=run, name="player-search-index", daemon=True).start()


def ensure_fresh() -> None:
    index = _current()
    if index is None:
        _build_in_background()
        return
    max_age = (
        INCOMPLETE_INDEX_MAX_AGE_SECONDS
        if index.get("missing_iteration_ids")
        else INDEX_MAX_AGE_SECONDS
    )
    if time.time() - index["built_at"] > max_age:
        _build_in_background()


def _enrich(index: dict[str, Any], player: dict[str, Any]) -> dict[str, Any]:
    from app import main as m

    squad_names = index["squad_names"]
    return m._enrich_player_label(
        m._enrich_player_seasons(
            copy.deepcopy(player), index["label_map"], index["iteration_meta"], squad_names
        ),
        index["iteration_meta"],
        squad_names,
    )


def player_by_id(player_id: int) -> dict[str, Any] | None:
    """Indexed player with club/league filled in, or None if not indexed."""
    index = _current()
    if index is None:
        return None
    player = index["by_id"].get(int(player_id))
    return _enrich(index, player) if player is not None else None


def search(query: str) -> dict[str, Any] | None:
    """Matching players enriched like the live catalog, or None if no index yet."""
    from app import main as m

    ensure_fresh()
    index = _current()
    if index is None:
        return None
    variants = m._search_name_variants(query)
    players = [
        _enrich(index, player)
        for player, name in zip(index["players"], index["names_lower"])
        if any(variant in name for variant in variants)
    ]
    return {"players": players, "season_count": len(index["iteration_ids"])}
