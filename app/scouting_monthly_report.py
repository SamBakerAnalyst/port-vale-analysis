"""Player of the Month PDF — top 10 overall + per-profile strengths for each position."""

from __future__ import annotations

import calendar
import json
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fpdf import FPDF
from pydantic import BaseModel, Field

from app.label_utils import humanize_profile_name
from app.pdf_report import pdf_safe
from app.scouting_monthly import (
    MONTHLY_DEFAULT_MIN_MINUTES,
    ScoutingMonthlyListRequest,
    build_scouting_monthly_list,
    prefetch_monthly_match_kpis,
)

POTM_DEFAULT_LEAGUES: tuple[str, ...] = (
    "National League",
    "League One",
    "League Two",
    "PL2",
    "Scottish Prem",
    "Irish Prem",
)
POTM_TOP_N = 10
POTM_DISK_CACHE_DIR = Path.home() / ".cache" / "impect-scouting" / "potm"


class ScoutingMonthlyReportRequest(BaseModel):
    year: int
    month: int = Field(ge=1, le=12)
    leagues: list[str] = Field(default_factory=lambda: list(POTM_DEFAULT_LEAGUES))
    min_minutes: float = MONTHLY_DEFAULT_MIN_MINUTES
    positions: list[str] = Field(default_factory=list)
    top_n: int = Field(default=POTM_TOP_N, ge=3, le=20)
    include_season_scores: bool = False


def _overall_score(profile_scores: dict[str, Any]) -> float | None:
    values = [float(v) for v in profile_scores.values() if v is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _player_id_key(player: dict[str, Any]) -> str | None:
    raw_id = str(player.get("id") or "")
    if ":" in raw_id:
        return raw_id.split(":", 1)[1]
    player_id = player.get("playerId")
    if player_id is not None:
        return str(int(player_id))
    return None


def _format_score_with_season(
    monthly: float | None,
    season: float | None,
    *,
    decimals: int = 0,
) -> str:
    if monthly is None:
        return "—"
    monthly_text = f"{monthly:.{decimals}f}"
    if season is None:
        return monthly_text
    return f"{monthly_text} ({season:.{decimals}f})"


def _load_season_score_lookup(
    position: str,
    leagues: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Map playerId -> list of season score snapshots (current + previous if available)."""
    from app.scouting import ScoutingLongListRequest, build_scouting_long_list

    by_player: dict[str, list[dict[str, Any]]] = {}
    for season_mode in ("current", "previous"):
        try:
            data = build_scouting_long_list(
                ScoutingLongListRequest(
                    position=position,
                    leagues=leagues,
                    min_minutes=0,
                    season_mode=season_mode,
                )
            )
        except HTTPException:
            continue

        for player in data.get("players") or []:
            key = _player_id_key(player)
            if not key:
                continue
            scores = dict(player.get("profileScores") or {})
            by_player.setdefault(key, []).append(
                {
                    "profileScores": scores,
                    "overall": _overall_score(scores),
                    "minutes": player.get("minutes"),
                    "season": str(player.get("season") or ""),
                }
            )
    return by_player


def _pick_season_snapshot(
    options: list[dict[str, Any]],
    preferred_season: str | None,
) -> dict[str, Any] | None:
    if not options:
        return None
    preferred = str(preferred_season or "").strip()
    if preferred:
        for option in options:
            if str(option.get("season") or "").strip() == preferred:
                return option
    # Prefer the season with more minutes when labels don't match.
    return max(options, key=lambda item: float(item.get("minutes") or 0))


def _attach_season_scores(
    players: list[dict[str, Any]],
    season_lookup: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for player in players:
        key = _player_id_key(player)
        season = _pick_season_snapshot(
            season_lookup.get(key or "", []),
            str(player.get("season") or "") or None,
        )
        row = dict(player)
        if season:
            row["seasonProfileScores"] = season.get("profileScores") or {}
            row["seasonOverall"] = season.get("overall")
            row["seasonMinutes"] = season.get("minutes")
        else:
            row["seasonProfileScores"] = {}
            row["seasonOverall"] = None
            row["seasonMinutes"] = None
        enriched.append(row)
    return enriched


def _rank_overall(players: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for player in players:
        overall = _overall_score(player.get("profileScores") or {})
        if overall is None:
            continue
        ranked.append({**player, "overall": overall})
    ranked.sort(key=lambda item: item["overall"], reverse=True)
    return ranked[:top_n]


def _rank_by_profile(
    players: list[dict[str, Any]],
    profile_api_name: str,
    top_n: int,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for player in players:
        value = (player.get("profileScores") or {}).get(profile_api_name)
        if value is None:
            continue
        ranked.append(
            {
                **player,
                "profileValue": float(value),
                "_profileApiName": profile_api_name,
            }
        )
    ranked.sort(key=lambda item: item["profileValue"], reverse=True)
    return ranked[:top_n]


def _short_profile_label(label: str) -> str:
    text = humanize_profile_name(label) if str(label).upper().startswith("PV") else str(label or "")
    upper = text.upper()
    short = {
        "LINK / DEEP PLAY MAKER": "Link / Deep PM",
        "THREAT IN BEHIND": "Threat Behind",
        "GOAL THREAT": "Goal Threat",
        "HOLD UP": "Hold Up",
        "PRESSER": "Presser",
        "BALL PLAYING": "Ball Playing GK",
        "BOX GOALKEEPER": "Box GK",
        "SHOT STOPPING": "Shot Stopper",
        "SWEEPER": "Sweeper Keeper",
        "DEEP CREATOR": "Deep Creator",
    }
    for key, value in short.items():
        if key in upper:
            return value
    cleaned = text.replace("GOALKEEPER", "GK").replace("Goalkeeper", "GK")
    return cleaned[:24]


def _compact_score(value: float | None, *, decimals: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f}"


def _compact_panels_per_page() -> tuple[int, int]:
    """Columns × rows of mini-lists on one landscape A4 page."""
    return 3, 4


class MonthlyReportPDF(FPDF):
    NAVY = (15, 23, 42)
    SLATE = (30, 41, 59)
    MUTED = (100, 116, 139)
    ACCENT = (56, 189, 248)
    GREEN = (16, 185, 129)
    LIGHT = (248, 250, 252)
    WHITE = (255, 255, 255)
    LINE = (226, 232, 240)
    ROW_ALT = (241, 245, 249)
    MARGIN = 7.0
    HEADER_H = 14.0
    FOOTER_H = 8.0
    COMPACT_ROW_H = 3.35
    COMPACT_TITLE_H = 5.0
    COMPACT_HEADER_H = 3.8
    COMPACT_GAP = 2.8

    def __init__(self, month_label: str, leagues: list[str]) -> None:
        super().__init__(orientation="L", unit="mm", format="A4")
        self.month_label = pdf_safe(month_label)
        self.leagues_label = pdf_safe(" · ".join(leagues))
        self.set_auto_page_break(auto=False)
        self.set_margins(self.MARGIN, self.MARGIN, self.MARGIN)
        self.alias_nb_pages()

    def _fill(self, color: tuple[int, int, int]) -> None:
        self.set_fill_color(*color)

    def _rgb(self, color: tuple[int, int, int]) -> None:
        self.set_text_color(*color)

    def _draw(self, color: tuple[int, int, int]) -> None:
        self.set_draw_color(*color)

    def footer(self) -> None:
        self.set_y(-8)
        self.set_font("Helvetica", "", 8)
        self._rgb(self.MUTED)
        self.cell(
            0,
            4,
            pdf_safe(
                f"Port Vale · Player of the Month · {self.month_label} · "
                f"Page {self.page_no()}/{{nb}}"
            ),
            align="C",
        )

    def add_cover(
        self,
        *,
        min_minutes: float,
        position_count: int,
        generated_at: str,
        warnings: list[str],
    ) -> None:
        self.add_page()
        self._fill(self.NAVY)
        self.rect(0, 0, self.w, self.h, style="F")
        self._fill(self.ACCENT)
        self.rect(0, self.h - 4, self.w, 4, style="F")

        self.set_xy(18, 34)
        self.set_font("Helvetica", "B", 16)
        self._rgb(self.ACCENT)
        self.cell(0, 8, "PORT VALE FC  ·  SCOUTING")

        self.set_xy(18, 50)
        self.set_font("Helvetica", "B", 40)
        self._rgb(self.WHITE)
        self.cell(0, 16, "Player of the Month")

        self.set_xy(18, 72)
        self.set_font("Helvetica", "B", 26)
        self._rgb(self.ACCENT)
        self.cell(0, 12, self.month_label)

        self.set_xy(18, 94)
        self.set_font("Helvetica", "", 14)
        self._rgb((203, 213, 225))
        self.multi_cell(
            220,
            6,
            pdf_safe(
                f"{len(self.leagues_label.split(' · '))} leagues · top {POTM_TOP_N} overall + per profile\n"
                f"{min_minutes:.0f}+ minutes in the month · league-only rankings\n"
                f"Compact digest — rank, player, age, club, score"
            ),
        )

        self.set_xy(18, 128)
        self.set_font("Helvetica", "", 10)
        self._rgb((148, 163, 184))
        self.multi_cell(
            230,
            5.5,
            pdf_safe(
                "Each league: one page of overall tops by position, then profile leader pages.\n"
                "Scores are month percentiles vs peers in that league (0–100)."
            ),
        )

        if warnings:
            self.set_xy(18, 168)
            self.set_font("Helvetica", "", 9)
            self._rgb((251, 191, 36))
            self.multi_cell(250, 4.5, pdf_safe("Notes: " + " · ".join(warnings[:5])))

        self.set_xy(18, self.h - 18)
        self.set_font("Helvetica", "", 10)
        self._rgb((148, 163, 184))
        self.cell(0, 5, pdf_safe(f"Generated {generated_at}"))

    def _page_header(self, title: str, subtitle: str = "") -> None:
        self._fill(self.NAVY)
        self.rect(0, 0, self.w, self.HEADER_H, style="F")
        self.set_xy(self.MARGIN, 3.5)
        self.set_font("Helvetica", "B", 11)
        self._rgb(self.WHITE)
        self.cell(0, 4.5, pdf_safe(title))
        if subtitle:
            self.set_xy(self.MARGIN, 9.0)
            self.set_font("Helvetica", "", 7.5)
            self._rgb((203, 213, 225))
            self.cell(0, 3.5, pdf_safe(subtitle))
        self.set_xy(self.w - 52, 4.0)
        self.set_font("Helvetica", "B", 9)
        self._rgb(self.ACCENT)
        self.cell(44, 5, self.month_label, align="R")

    def _panel_height(self, row_count: int) -> float:
        return (
            self.COMPACT_TITLE_H
            + self.COMPACT_HEADER_H
            + row_count * self.COMPACT_ROW_H
            + 1.5
        )

    def _draw_compact_list(
        self,
        x: float,
        y: float,
        width: float,
        *,
        title: str,
        rows: list[dict[str, Any]],
    ) -> None:
        height = self._panel_height(len(rows))
        self._fill(self.WHITE)
        self._draw(self.LINE)
        self.rect(x, y, width, height, style="DF")

        self._fill(self.SLATE)
        self.rect(x, y, width, self.COMPACT_TITLE_H, style="F")
        self.set_xy(x + 1.8, y + 1.2)
        self.set_font("Helvetica", "B", 7.5)
        self._rgb(self.WHITE)
        self.cell(width - 3.6, 3.5, pdf_safe(title))

        pad = 1.6
        rank_w = 5.5
        age_w = 7.0
        score_w = 9.0
        club_w = min(24.0, width * 0.28)
        name_w = width - pad * 2 - rank_w - age_w - club_w - score_w

        header_y = y + self.COMPACT_TITLE_H + 0.6
        self.set_font("Helvetica", "B", 6.5)
        self._rgb(self.MUTED)
        self.set_xy(x + pad, header_y)
        self.cell(rank_w, 3, "#")
        self.cell(name_w, 3, "Player")
        self.cell(age_w, 3, "Age", align="C")
        self.cell(club_w, 3, "Club")
        self.cell(score_w, 3, "Scr", align="R")

        row_top = header_y + self.COMPACT_HEADER_H - 2.0
        name_chars = max(8, int(name_w / 1.85))
        club_chars = max(6, int(club_w / 1.75))

        for index, row in enumerate(rows):
            ry = row_top + index * self.COMPACT_ROW_H
            if index % 2 == 0:
                self._fill(self.ROW_ALT)
                self.rect(x + 0.5, ry, width - 1.0, self.COMPACT_ROW_H, style="F")

            text_y = ry + (self.COMPACT_ROW_H - 3.2) / 2
            self.set_xy(x + pad, text_y)
            self.set_font("Helvetica", "B", 7)
            self._rgb(self.GREEN)
            self.cell(rank_w, 3.2, str(row.get("rank") or index + 1))

            self.set_font("Helvetica", "B", 7)
            self._rgb(self.NAVY)
            self.cell(name_w, 3.2, pdf_safe(str(row.get("name") or ""))[:name_chars])

            self.set_font("Helvetica", "", 7)
            self._rgb(self.SLATE)
            age = row.get("age")
            self.cell(age_w, 3.2, "" if age is None else str(age), align="C")

            self.set_font("Helvetica", "", 6.5)
            self._rgb(self.MUTED)
            self.cell(club_w, 3.2, pdf_safe(str(row.get("club") or ""))[:club_chars])

            self.set_font("Helvetica", "B", 7)
            self._rgb(self.NAVY)
            self.cell(score_w, 3.2, pdf_safe(str(row.get("score") or "—")), align="R")

    def _compact_rows_from_players(
        self,
        players: list[dict[str, Any]],
        *,
        score_key: str = "overall",
        profile_api: str | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, player in enumerate(players):
            if score_key == "overall":
                score = _compact_score(player.get("overall"), decimals=0)
            else:
                score = _compact_score(player.get("profileValue"), decimals=0)
            rows.append(
                {
                    "rank": index + 1,
                    "name": player.get("name") or "",
                    "age": player.get("age"),
                    "club": player.get("club") or "",
                    "score": score,
                }
            )
        return rows

    def _layout_compact_panels(
        self,
        panels: list[tuple[str, list[dict[str, Any]]]],
        *,
        page_title: str,
        page_subtitle: str,
    ) -> None:
        if not panels:
            return

        cols, row_count = _compact_panels_per_page()
        panels_per_page = cols * row_count
        usable_w = self.w - self.MARGIN * 2
        usable_h = self.h - self.HEADER_H - self.FOOTER_H - 2.0
        panel_w = (usable_w - self.COMPACT_GAP * (cols - 1)) / cols
        panel_h = (usable_h - self.COMPACT_GAP * (row_count - 1)) / row_count
        start_y = self.HEADER_H + 1.5

        for page_start in range(0, len(panels), panels_per_page):
            chunk = panels[page_start : page_start + panels_per_page]
            cont = " (cont.)" if page_start else ""
            self.add_page()
            self._fill(self.LIGHT)
            self.rect(0, 0, self.w, self.h, style="F")
            self._page_header(f"{page_title}{cont}", page_subtitle)

            for index, (title, rows) in enumerate(chunk):
                col = index % cols
                row = index // cols
                x = self.MARGIN + col * (panel_w + self.COMPACT_GAP)
                y = start_y + row * (panel_h + self.COMPACT_GAP)
                self._draw_compact_list(x, y, panel_w, title=title, rows=rows)

    def add_league_compact_pages(
        self,
        *,
        league: str,
        sections: list[dict[str, Any]],
        top_n: int,
        min_minutes: float,
    ) -> None:
        overall_panels: list[tuple[str, list[dict[str, Any]]]] = []
        profile_panels: list[tuple[str, list[dict[str, Any]]]] = []

        for section in sections:
            position_label = str(section.get("positionLabel") or section.get("position") or "")
            top_overall = list(section.get("topOverall") or [])[:top_n]
            if top_overall:
                overall_panels.append(
                    (
                        f"{position_label} · overall",
                        self._compact_rows_from_players(top_overall),
                    )
                )

            profiles = [
                {
                    "apiName": profile.get("apiName") or profile.get("api_name") or "",
                    "label": profile.get("label") or "",
                }
                for profile in section.get("profiles") or []
                if profile.get("apiName") or profile.get("api_name")
            ]
            players = list(section.get("players") or [])
            for profile in profiles:
                ranked = _rank_by_profile(players, profile["apiName"], top_n)
                if not ranked:
                    continue
                short = _short_profile_label(profile["label"])
                profile_panels.append(
                    (
                        f"{position_label} · {short}",
                        self._compact_rows_from_players(
                            ranked,
                            score_key="profile",
                            profile_api=profile["apiName"],
                        ),
                    )
                )

        subtitle = f"{league} · {min_minutes:.0f}+ min · month percentiles"
        self._layout_compact_panels(
            overall_panels,
            page_title=f"{league} · Top {top_n} overall",
            page_subtitle=subtitle,
        )
        self._layout_compact_panels(
            profile_panels,
            page_title=f"{league} · Top {top_n} by profile",
            page_subtitle=subtitle,
        )


def _potm_disk_cache_key(body: ScoutingMonthlyReportRequest) -> str:
    leagues = sorted(league for league in body.leagues if league)
    return (
        f"potm:{body.year}:{body.month:02d}:"
        f"{'|'.join(leagues)}:{body.min_minutes:.0f}:{body.top_n}"
    )


def _load_potm_disk_cache(body: ScoutingMonthlyReportRequest) -> dict[str, Any] | None:
    path = POTM_DISK_CACHE_DIR / f"{_potm_disk_cache_key(body).replace('|', '_').replace(':', '-')}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("leagueReports"):
            return payload
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return None


def _save_potm_disk_cache(body: ScoutingMonthlyReportRequest, payload: dict[str, Any]) -> None:
    try:
        POTM_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = POTM_DISK_CACHE_DIR / f"{_potm_disk_cache_key(body).replace('|', '_').replace(':', '-')}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        return


def _standout_row_to_potm_player(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "age": row.get("age"),
        "club": row.get("club"),
        "league": row.get("league"),
        "minutes": row.get("minutes"),
        "profileScores": dict(row.get("profileScores") or {}),
    }


def _empty_potm_section(position: str, position_label: str) -> dict[str, Any]:
    return {
        "position": position,
        "positionLabel": position_label,
        "profiles": [],
        "players": [],
        "topOverall": [],
    }


def _potm_payload_from_standouts_raw(
    raw: dict[str, Any],
    body: ScoutingMonthlyReportRequest,
) -> dict[str, Any]:
    from app.scouting import _profiles_for_position, _scouting_export_positions, _scouting_position_label

    leagues = [league for league in body.leagues if league] or list(POTM_DEFAULT_LEAGUES)
    positions = body.positions or _scouting_export_positions()
    month_label = f"{calendar.month_name[body.month]} {body.year}"
    all_players = list(raw.get("players") or [])
    league_reports: list[dict[str, Any]] = []

    for league in leagues:
        sections: list[dict[str, Any]] = []
        for position in positions:
            position_label = _scouting_position_label(position)
            try:
                profile_names = _profiles_for_position(position)
            except HTTPException:
                profile_names = []
            profiles = [
                {"apiName": name, "label": humanize_profile_name(name)} for name in profile_names
            ]
            league_players = [
                _standout_row_to_potm_player(row)
                for row in all_players
                if row.get("position") == position
                and str(row.get("league") or "") == league
                and float(row.get("minutes") or 0) >= body.min_minutes
            ]
            sections.append(
                {
                    "position": position,
                    "positionLabel": position_label,
                    "profiles": profiles,
                    "players": league_players,
                    "topOverall": _rank_overall(league_players, body.top_n),
                }
            )
        league_reports.append({"league": league, "sections": sections})

    return {
        "monthLabel": month_label,
        "year": body.year,
        "month": body.month,
        "leagues": leagues,
        "minMinutes": body.min_minutes,
        "topN": body.top_n,
        "leagueReports": league_reports,
        "warnings": list(raw.get("warnings") or []),
        "generatedAt": datetime.now().strftime("%d %b %Y, %H:%M"),
        "source": "standouts_cache",
    }


def _try_potm_from_standouts_cache(body: ScoutingMonthlyReportRequest) -> dict[str, Any] | None:
    from app.home_dashboard import (
        STANDOUTS_CACHE_TTL,
        STANDOUTS_LEAGUES,
        _load_standouts_disk,
        _standouts_cache,
        _standouts_raw_cache_key,
    )

    leagues = [league for league in body.leagues if league] or list(POTM_DEFAULT_LEAGUES)
    if any(league not in STANDOUTS_LEAGUES for league in leagues):
        return None

    cache_key = _standouts_raw_cache_key("month", year=body.year, month=body.month)
    raw: dict[str, Any] | None = None
    now = time.time()

    cached = _standouts_cache.get(cache_key)
    if cached and now - cached[0] < STANDOUTS_CACHE_TTL:
        raw = cached[1]
    if raw is None:
        disk = _load_standouts_disk(cache_key)
        if disk:
            raw = disk[1]

    if not raw or raw.get("building") or not raw.get("players"):
        return None
    if int(raw.get("year") or 0) != body.year or int(raw.get("month") or 0) != body.month:
        return None

    return _potm_payload_from_standouts_raw(raw, body)


def build_monthly_report_payload(body: ScoutingMonthlyReportRequest) -> dict[str, Any]:
    from app.scouting import _scouting_export_positions, _scouting_position_label

    disk_payload = _load_potm_disk_cache(body)
    if disk_payload:
        disk_payload["source"] = "potm_disk_cache"
        return disk_payload

    cached_payload = _try_potm_from_standouts_cache(body)
    if cached_payload:
        _save_potm_disk_cache(body, cached_payload)
        return cached_payload

    from app.home_dashboard import _schedule_standouts_refresh

    _schedule_standouts_refresh("month", year=body.year, month=body.month)

    leagues = [league for league in body.leagues if league]
    if not leagues:
        leagues = list(POTM_DEFAULT_LEAGUES)

    positions = body.positions or _scouting_export_positions()
    month_label = f"{calendar.month_name[body.month]} {body.year}"
    league_sections: dict[str, list[dict[str, Any]]] = {league: [] for league in leagues}
    warnings: list[str] = []

    try:
        prefetch = prefetch_monthly_match_kpis(
            leagues=leagues,
            year=body.year,
            month=body.month,
            warm_position_scores=True,
        )
        warnings.extend(prefetch.get("warnings") or [])
    except HTTPException as exc:
        if exc.status_code == 429:
            raise
        warnings.append(str(exc.detail))

    # One Impect pull per position (all leagues together) — not once per league × position.
    for position in positions:
        position_label = _scouting_position_label(position)
        try:
            data = build_scouting_monthly_list(
                ScoutingMonthlyListRequest(
                    position=position,
                    leagues=leagues,
                    year=body.year,
                    month=body.month,
                    min_minutes=body.min_minutes,
                )
            )
        except HTTPException as exc:
            warnings.append(f"{position_label}: {exc.detail}")
            for league in leagues:
                league_sections[league].append(_empty_potm_section(position, position_label))
            continue

        players = list(data.get("players") or [])
        profiles = list(data.get("profiles") or [])
        for note in data.get("warnings") or []:
            warnings.append(str(note))

        for league in leagues:
            league_players = [
                player for player in players if str(player.get("league") or "") == league
            ]
            if body.include_season_scores:
                try:
                    season_lookup = _load_season_score_lookup(position, [league])
                    league_players = _attach_season_scores(league_players, season_lookup)
                except Exception as exc:
                    warnings.append(
                        f"{league} · {position_label}: season scores unavailable ({exc})."
                    )
            league_sections[league].append(
                {
                    "position": position,
                    "positionLabel": data.get("positionLabel") or position_label,
                    "profiles": profiles,
                    "players": league_players,
                    "topOverall": _rank_overall(league_players, body.top_n),
                    "matchCount": data.get("matchCount"),
                }
            )

    league_reports = [
        {"league": league, "sections": league_sections[league]} for league in leagues
    ]

    payload = {
        "monthLabel": month_label,
        "year": body.year,
        "month": body.month,
        "leagues": leagues,
        "minMinutes": body.min_minutes,
        "topN": body.top_n,
        "leagueReports": league_reports,
        "warnings": warnings,
        "generatedAt": datetime.now().strftime("%d %b %Y, %H:%M"),
        "source": "live_impect",
    }
    _save_potm_disk_cache(body, payload)
    return payload


def build_monthly_report_pdf(body: ScoutingMonthlyReportRequest) -> bytes:
    payload = build_monthly_report_payload(body)
    league_reports = list(payload.get("leagueReports") or [])
    position_count = len(league_reports[0].get("sections") or []) if league_reports else 0
    pdf = MonthlyReportPDF(payload["monthLabel"], payload["leagues"])
    pdf.add_cover(
        min_minutes=float(payload["minMinutes"]),
        position_count=position_count,
        generated_at=str(payload["generatedAt"]),
        warnings=list(payload.get("warnings") or []),
    )

    for league_report in payload["leagueReports"]:
        league = str(league_report.get("league") or "")
        sections = list(league_report.get("sections") or [])
        pdf.add_league_compact_pages(
            league=league,
            sections=sections,
            top_n=int(payload["topN"]),
            min_minutes=float(payload["minMinutes"]),
        )

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()
