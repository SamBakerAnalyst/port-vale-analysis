"""Player of the Month PDF — top 10 overall + per-profile strengths for each position."""

from __future__ import annotations

import calendar
from datetime import datetime
from io import BytesIO
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

POTM_DEFAULT_LEAGUES = ("League Two", "National League", "Scottish Prem")
POTM_TOP_N = 10


class ScoutingMonthlyReportRequest(BaseModel):
    year: int
    month: int = Field(ge=1, le=12)
    leagues: list[str] = Field(default_factory=lambda: list(POTM_DEFAULT_LEAGUES))
    min_minutes: float = MONTHLY_DEFAULT_MIN_MINUTES
    positions: list[str] = Field(default_factory=list)
    top_n: int = Field(default=POTM_TOP_N, ge=3, le=20)


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


def _profile_row_counts(profile_count: int) -> list[int]:
    """Columns per row so panels fill the page (no orphan empty slot)."""
    if profile_count <= 1:
        return [1]
    if profile_count == 2:
        return [2]
    if profile_count == 3:
        return [3]
    if profile_count == 4:
        return [2, 2]
    if profile_count == 5:
        return [2, 3]
    if profile_count == 6:
        return [3, 3]
    if profile_count == 7:
        return [2, 2, 3]
    if profile_count == 8:
        return [3, 3, 2]
    return [3, 3, 3]


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
    MARGIN = 8.0
    HEADER_H = 22.0
    FOOTER_H = 10.0

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
            7,
            pdf_safe(
                f"{self.leagues_label}\n"
                f"{position_count} positions · top {POTM_TOP_N} overall + top {POTM_TOP_N} per profile\n"
                f"{min_minutes:.0f}+ minutes in the calendar month\n"
                f"Scores = league-relative percentiles · month (season) shown together"
            ),
        )

        self.set_xy(18, 140)
        self.set_font("Helvetica", "", 11)
        self._rgb((148, 163, 184))
        self.multi_cell(
            230,
            6,
            pdf_safe(
                "Page 1 per position: top overall scorers (equal-weighted profile average).\n"
                "Page 2 per position: profile breakdowns — specialists who may not make the overall top 10.\n"
                "Read scores as month percentile, with season percentile in brackets — e.g. 68 (45)."
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

    def _header_bar(self, title: str, subtitle: str) -> None:
        self._fill(self.NAVY)
        self.rect(0, 0, self.w, self.HEADER_H, style="F")
        self._fill(self.ACCENT)
        self.rect(0, self.HEADER_H, self.w, 1.4, style="F")

        self.set_xy(self.MARGIN, 4.5)
        self.set_font("Helvetica", "B", 18)
        self._rgb(self.WHITE)
        self.cell(200, 8, pdf_safe(title))

        self.set_xy(self.MARGIN, 14)
        self.set_font("Helvetica", "", 9)
        self._rgb((203, 213, 225))
        self.cell(210, 5, pdf_safe(subtitle))

        self.set_xy(self.w - 72, 6)
        self.set_font("Helvetica", "B", 12)
        self._rgb(self.ACCENT)
        self.cell(64, 8, self.month_label, align="R")

    def add_overall_page(
        self,
        *,
        position_label: str,
        profiles: list[dict[str, str]],
        players: list[dict[str, Any]],
        leagues: list[str],
        min_minutes: float,
    ) -> None:
        self.add_page()
        self._fill(self.LIGHT)
        self.rect(0, 0, self.w, self.h, style="F")
        self._header_bar(
            f"{position_label}  ·  Top {len(players)} overall",
            f"{' · '.join(leagues)} · {min_minutes:.0f}+ min · month (season) · equal-weighted average",
        )

        if not players:
            self.set_xy(12, 40)
            self.set_font("Helvetica", "I", 12)
            self._rgb(self.MUTED)
            self.cell(0, 8, "No players met the monthly filter for this position.")
            return

        profile_cols = profiles[:6]
        left = self.MARGIN
        y = self.HEADER_H + 4.0
        content_bottom = self.h - self.FOOTER_H
        rank_w = 11.0
        name_w = 46.0
        age_w = 11.0
        min_w = 14.0
        club_w = 36.0
        league_w = 28.0
        overall_w = 26.0
        remaining = self.w - (self.MARGIN * 2) - rank_w - name_w - age_w - min_w - club_w - league_w - overall_w
        profile_w = remaining / max(len(profile_cols), 1)

        headers = ["#", "Name", "Age", "Min", "Club", "League"]
        widths = [rank_w, name_w, age_w, min_w, club_w, league_w]
        for profile in profile_cols:
            headers.append(_short_profile_label(profile["label"]))
            widths.append(profile_w)
        headers.append("Overall")
        widths.append(overall_w)

        header_h = 10.0
        self.set_xy(left, y)
        self.set_font("Helvetica", "B", 9)
        self._fill(self.SLATE)
        self._rgb(self.WHITE)
        for header, width in zip(headers, widths):
            align = "L" if header in {"Name", "Club", "League"} else "C"
            self.cell(width, header_h, pdf_safe(header), border=0, align=align, fill=True)
        y += header_h

        available = content_bottom - y
        row_h = available / max(len(players), 1)
        body_font = 11 if row_h >= 15 else 10 if row_h >= 12 else 9

        for index, player in enumerate(players):
            if index % 2 == 0:
                self._fill(self.WHITE)
            else:
                self._fill(self.ROW_ALT)
            self.rect(left, y, sum(widths), row_h, style="F")

            values = [
                str(index + 1),
                str(player.get("name") or ""),
                "" if player.get("age") is None else str(player.get("age")),
                "" if player.get("minutes") is None else str(int(player.get("minutes"))),
                str(player.get("club") or ""),
                str(player.get("league") or ""),
            ]
            scores = player.get("profileScores") or {}
            season_scores = player.get("seasonProfileScores") or {}
            for profile in profile_cols:
                values.append(
                    _format_score_with_season(
                        scores.get(profile["apiName"]),
                        season_scores.get(profile["apiName"]),
                        decimals=0,
                    )
                )
            values.append(
                _format_score_with_season(
                    player.get("overall"),
                    player.get("seasonOverall"),
                    decimals=1,
                )
            )

            text_y = y + (row_h - 4.5) / 2
            x = left
            for col_index, (value, width) in enumerate(zip(values, widths)):
                self.set_xy(x + 0.8, text_y)
                if col_index == 0:
                    self.set_font("Helvetica", "B", body_font + 1)
                    self._rgb(self.GREEN)
                    align = "C"
                elif col_index == 1:
                    self.set_font("Helvetica", "B", body_font)
                    self._rgb(self.NAVY)
                    align = "L"
                elif col_index == len(values) - 1:
                    self.set_font("Helvetica", "B", body_font)
                    self._rgb(self.GREEN)
                    align = "C"
                elif col_index >= 6:
                    self.set_font("Helvetica", "B", max(body_font - 1, 8))
                    self._rgb(self.SLATE)
                    align = "C"
                else:
                    self.set_font("Helvetica", "", body_font)
                    self._rgb(self.SLATE)
                    align = "L" if col_index in (4, 5) else "C"
                self.cell(width - 1.6, 4.5, pdf_safe(value)[:34], align=align)
                x += width
            y += row_h

    def add_profile_page(
        self,
        *,
        position_label: str,
        profiles: list[dict[str, str]],
        players: list[dict[str, Any]],
        top_n: int,
        leagues: list[str],
    ) -> None:
        self.add_page()
        self._fill(self.LIGHT)
        self.rect(0, 0, self.w, self.h, style="F")
        self._header_bar(
            f"{position_label}  ·  Profile strengths",
            f"Top {top_n} per profile · month (season) · specialists outside overall top 10 · {' · '.join(leagues)}",
        )

        if not profiles or not players:
            self.set_xy(12, 40)
            self.set_font("Helvetica", "I", 12)
            self._rgb(self.MUTED)
            self.cell(0, 8, "No profile breakdown available for this position.")
            return

        gap = 3.5
        start_y = self.HEADER_H + 3.5
        usable_h = self.h - start_y - self.FOOTER_H
        usable_w = self.w - (self.MARGIN * 2)
        row_counts = _profile_row_counts(len(profiles))
        panels_per_page = sum(row_counts)
        row_h = (usable_h - gap * (len(row_counts) - 1)) / max(len(row_counts), 1)

        for index, profile in enumerate(profiles):
            page_index = index // panels_per_page
            local_index = index % panels_per_page
            if page_index > 0 and local_index == 0:
                self.add_page()
                self._fill(self.LIGHT)
                self.rect(0, 0, self.w, self.h, style="F")
                self._header_bar(
                    f"{position_label}  ·  Profile strengths (cont.)",
                    f"Top {top_n} per profile · month (season) · {' · '.join(leagues)}",
                )

            # Locate which row/col this panel sits in for the current page layout.
            cursor = 0
            row_idx = 0
            col_idx = 0
            for r, cols_in_row in enumerate(row_counts):
                if local_index < cursor + cols_in_row:
                    row_idx = r
                    col_idx = local_index - cursor
                    break
                cursor += cols_in_row
            cols_in_row = row_counts[row_idx]
            panel_w = (usable_w - gap * (cols_in_row - 1)) / cols_in_row
            x = self.MARGIN + col_idx * (panel_w + gap)
            y = start_y + row_idx * (row_h + gap)
            ranked = _rank_by_profile(players, profile["apiName"], top_n)
            self._draw_profile_panel(
                x,
                y,
                panel_w,
                row_h,
                profile_label=_short_profile_label(profile["label"]),
                ranked=ranked,
            )

    def _draw_profile_panel(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        profile_label: str,
        ranked: list[dict[str, Any]],
    ) -> None:
        self._fill(self.WHITE)
        self._draw(self.LINE)
        self.rect(x, y, width, height, style="DF")

        title_h = 10.0
        self._fill(self.SLATE)
        self.rect(x, y, width, title_h, style="F")
        self.set_xy(x + 2.5, y + 2.5)
        self.set_font("Helvetica", "B", 10)
        self._rgb(self.WHITE)
        self.cell(width - 5, 5, pdf_safe(profile_label))

        if not ranked:
            self.set_xy(x + 3, y + 16)
            self.set_font("Helvetica", "I", 9)
            self._rgb(self.MUTED)
            self.cell(width - 6, 5, "No scorers")
            return

        pad = 2.2
        rank_w = 9.0
        min_w = 13.0
        score_w = 26.0 if width < 100 else 30.0
        show_club = width >= 105
        leftover = width - pad * 2 - rank_w - min_w - score_w
        if show_club:
            name_w = leftover * 0.58
            club_w = leftover * 0.42
        else:
            name_w = leftover
            club_w = 0.0
        name_chars = max(10, int(name_w / 2.05))
        club_chars = max(5, int(club_w / 2.0)) if show_club else 0

        header_y = y + title_h + 1.5
        self.set_font("Helvetica", "B", 8)
        self._rgb(self.MUTED)
        self.set_xy(x + pad, header_y)
        self.cell(rank_w, 4, "#")
        self.cell(name_w, 4, "Name")
        if show_club:
            self.cell(club_w, 4, "Club")
        self.cell(min_w, 4, "Min", align="R")
        self.cell(score_w, 4, "Mo (Sea)", align="R")

        row_top = header_y + 5.0
        available = height - (row_top - y) - 2.0
        row_h = available / max(len(ranked), 1)
        body_font = 10 if row_h >= 10 else 9 if row_h >= 8 else 8

        for index, player in enumerate(ranked):
            ry = row_top + index * row_h
            if index % 2 == 0:
                self._fill(self.ROW_ALT)
                self.rect(x + 0.6, ry, width - 1.2, row_h, style="F")

            text_y = ry + (row_h - 4) / 2
            self.set_xy(x + pad, text_y)
            self.set_font("Helvetica", "B", body_font)
            self._rgb(self.GREEN)
            self.cell(rank_w, 4, str(index + 1))

            self.set_font("Helvetica", "B", body_font)
            self._rgb(self.NAVY)
            self.cell(name_w, 4, pdf_safe(str(player.get("name") or ""))[:name_chars])

            if show_club:
                self.set_font("Helvetica", "", max(body_font - 1, 7))
                self._rgb(self.MUTED)
                self.cell(club_w, 4, pdf_safe(str(player.get("club") or ""))[:club_chars])

            self.set_font("Helvetica", "", body_font)
            self._rgb(self.SLATE)
            self.cell(min_w, 4, str(int(player.get("minutes") or 0)), align="R")

            profile_name = player.get("_profileApiName")
            season_scores = player.get("seasonProfileScores") or {}
            season_value = season_scores.get(profile_name) if profile_name else None
            self.set_font("Helvetica", "B", body_font)
            self._rgb(self.NAVY)
            self.cell(
                score_w,
                4,
                _format_score_with_season(
                    player.get("profileValue"),
                    season_value,
                    decimals=0,
                ),
                align="R",
            )


def build_monthly_report_payload(body: ScoutingMonthlyReportRequest) -> dict[str, Any]:
    from app.scouting import _scouting_export_positions, _scouting_position_label

    leagues = [league for league in body.leagues if league]
    if not leagues:
        leagues = list(POTM_DEFAULT_LEAGUES)

    positions = body.positions or _scouting_export_positions()
    month_label = f"{calendar.month_name[body.month]} {body.year}"
    sections: list[dict[str, Any]] = []
    warnings: list[str] = []

    # Warm shared match/KPI cache once — every position reuses it instead of
    # re-downloading the same match KPIs 10 times.
    try:
        prefetch = prefetch_monthly_match_kpis(
            leagues=leagues,
            year=body.year,
            month=body.month,
        )
        warnings.extend(prefetch.get("warnings") or [])
    except HTTPException as exc:
        if exc.status_code == 429:
            raise
        warnings.append(str(exc.detail))

    for position in positions:
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
            warnings.append(f"{_scouting_position_label(position)}: {exc.detail}")
            sections.append(
                {
                    "position": position,
                    "positionLabel": _scouting_position_label(position),
                    "profiles": [],
                    "players": [],
                    "topOverall": [],
                }
            )
            continue

        players = list(data.get("players") or [])
        profiles = list(data.get("profiles") or [])
        try:
            season_lookup = _load_season_score_lookup(position, leagues)
            players = _attach_season_scores(players, season_lookup)
        except Exception as exc:
            warnings.append(
                f"{_scouting_position_label(position)}: season scores unavailable ({exc})."
            )
        sections.append(
            {
                "position": position,
                "positionLabel": data.get("positionLabel") or _scouting_position_label(position),
                "profiles": profiles,
                "players": players,
                "topOverall": _rank_overall(players, body.top_n),
                "matchCount": data.get("matchCount"),
            }
        )
        for note in data.get("warnings") or []:
            warnings.append(str(note))

    return {
        "monthLabel": month_label,
        "year": body.year,
        "month": body.month,
        "leagues": leagues,
        "minMinutes": body.min_minutes,
        "topN": body.top_n,
        "sections": sections,
        "warnings": warnings,
        "generatedAt": datetime.now().strftime("%d %b %Y, %H:%M"),
    }


def build_monthly_report_pdf(body: ScoutingMonthlyReportRequest) -> bytes:
    payload = build_monthly_report_payload(body)
    pdf = MonthlyReportPDF(payload["monthLabel"], payload["leagues"])
    pdf.add_cover(
        min_minutes=float(payload["minMinutes"]),
        position_count=len(payload["sections"]),
        generated_at=str(payload["generatedAt"]),
        warnings=list(payload.get("warnings") or []),
    )

    for section in payload["sections"]:
        profiles = [
            {
                "apiName": profile.get("apiName") or profile.get("api_name") or "",
                "label": profile.get("label") or "",
            }
            for profile in section.get("profiles") or []
            if profile.get("apiName") or profile.get("api_name")
        ]
        pdf.add_overall_page(
            position_label=str(section.get("positionLabel") or section.get("position") or ""),
            profiles=profiles,
            players=list(section.get("topOverall") or []),
            leagues=list(payload["leagues"]),
            min_minutes=float(payload["minMinutes"]),
        )
        pdf.add_profile_page(
            position_label=str(section.get("positionLabel") or section.get("position") or ""),
            profiles=profiles,
            players=list(section.get("players") or []),
            top_n=int(payload["topN"]),
            leagues=list(payload["leagues"]),
        )

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()
