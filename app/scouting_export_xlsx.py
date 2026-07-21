from __future__ import annotations

import re
from io import BytesIO
from typing import Any

import xlsxwriter


def _excel_sheet_name(label: str, used: set[str]) -> str:
    cleaned = re.sub(r"[\[\]\:\*\?\/\\]", "", str(label or "Sheet")).strip()
    cleaned = cleaned[:31] or "Sheet"
    base = cleaned
    suffix = 2
    while cleaned.casefold() in used:
        tail = f" {suffix}"
        cleaned = f"{base[: 31 - len(tail)]}{tail}"
        suffix += 1
    used.add(cleaned.casefold())
    return cleaned


def _profile_columns(body: Any) -> list[tuple[str, str]]:
    profiles = getattr(body, "profiles", None) or []
    columns: list[tuple[str, str]] = []
    for profile in profiles:
        api_name = getattr(profile, "api_name", None) or getattr(profile, "apiName", "")
        label = getattr(profile, "label", None) or api_name
        weight = getattr(profile, "weight", 0) or 0
        header = f"{label} (min {int(weight)})" if weight > 0 else label
        columns.append((api_name, header))
    return columns


def _player_profile_scores(player: Any) -> dict[str, float | None]:
    scores = getattr(player, "profile_scores", None) or getattr(player, "profileScores", {}) or {}
    return dict(scores)


def _write_list_sheet(
    workbook: xlsxwriter.Workbook,
    sheet_name: str,
    *,
    title: str,
    meta_lines: list[str],
    profile_columns: list[tuple[str, str]],
    players: list[Any],
) -> None:
    worksheet = workbook.add_worksheet(sheet_name)
    header_fmt = workbook.add_format({"bold": True, "bg_color": "#1a222d", "font_color": "#e8edf4"})
    meta_fmt = workbook.add_format({"italic": True, "font_color": "#8b9bb0"})
    num_fmt = workbook.add_format({"num_format": "0.0"})
    rank_fmt = workbook.add_format({"align": "center", "num_format": "0"})
    int_fmt = workbook.add_format({"num_format": "0"})
    overall_fmt = workbook.add_format({"bold": True, "num_format": "0.0", "font_color": "#34d399"})

    row = 0
    worksheet.write(row, 0, title, workbook.add_format({"bold": True, "font_size": 12}))
    row += 1
    for line in meta_lines:
        if line:
            worksheet.write(row, 0, line, meta_fmt)
            row += 1
    row += 1

    headers = ["Rank", "Name", "Age", "Min", "Height", "Foot", "League", "Club"]
    headers.extend(header for _, header in profile_columns)
    headers.append("Overall")

    for col, header in enumerate(headers):
        worksheet.write(row, col, header, header_fmt)

    header_row = row
    row += 1

    for player in players:
        scores = _player_profile_scores(player)
        values: list[Any] = [
            getattr(player, "rank", None),
            getattr(player, "name", ""),
            getattr(player, "age", None),
            getattr(player, "minutes", None),
            getattr(player, "height", "") or "",
            getattr(player, "foot", "") or "",
            getattr(player, "league", "") or "",
            getattr(player, "club", "") or "",
        ]
        for api_name, _ in profile_columns:
            value = scores.get(api_name)
            values.append(value if value is not None else "")
        overall = getattr(player, "overall", None)
        values.append(overall if overall is not None else "")

        minutes = getattr(player, "minutes", None)
        if minutes is not None and minutes != "":
            minutes = int(round(float(minutes)))
        values[3] = minutes

        for col, value in enumerate(values):
            if col == 0:
                worksheet.write(row, col, value, rank_fmt)
            elif col >= 8 and col < 8 + len(profile_columns):
                if value == "":
                    worksheet.write(row, col, "")
                else:
                    worksheet.write(row, col, value, num_fmt)
            elif col == len(values) - 1:
                if value == "":
                    worksheet.write(row, col, "")
                else:
                    worksheet.write(row, col, value, overall_fmt)
            elif col in (2, 3):
                if value == "" or value is None:
                    worksheet.write(row, col, "")
                else:
                    worksheet.write(row, col, int(value), int_fmt)
            else:
                worksheet.write(row, col, value)
        row += 1

    worksheet.freeze_panes(header_row + 1, 0)
    worksheet.autofilter(header_row, 0, max(header_row, row - 1), len(headers) - 1)
    worksheet.set_column(0, 0, 6)
    worksheet.set_column(1, 1, 24)
    worksheet.set_column(2, 3, 8)
    worksheet.set_column(4, 4, 12)
    worksheet.set_column(5, 5, 6)
    worksheet.set_column(6, 7, 16)
    if profile_columns:
        worksheet.set_column(8, 7 + len(profile_columns), 14)
    worksheet.set_column(8 + len(profile_columns), 8 + len(profile_columns), 10)


def build_scouting_export_xlsx(body: Any) -> bytes:
    players = getattr(body, "players", None) or []
    if not players:
        raise ValueError("No players to export.")

    profile_columns = _profile_columns(body)
    if not profile_columns:
        raise ValueError("No profile columns to export.")

    buffer = BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})

    leagues = ", ".join(getattr(body, "leagues", None) or [])
    meta_lines = [
        f"Generated: {getattr(body, 'generated_at', '') or ''}".strip(),
        f"Season: {getattr(body, 'season_mode_label', '') or getattr(body, 'seasonModeLabel', '') or ''}".strip(),
        f"Leagues: {leagues}" if leagues else "Leagues: (none)",
        f"Min minutes: {getattr(body, 'min_minutes', '')}",
        getattr(body, "scoring_note", "") or "",
    ]
    meta_lines = [line for line in meta_lines if line and line not in ("Season:", "Min minutes: ")]

    sheet_name = _excel_sheet_name(getattr(body, "position_label", "") or "Scouting", set())
    _write_list_sheet(
        workbook,
        sheet_name,
        title=getattr(body, "position_label", "") or "Scouting long list",
        meta_lines=meta_lines,
        profile_columns=profile_columns,
        players=players,
    )
    workbook.close()
    return buffer.getvalue()


def _equal_weight_overall(profile_scores: dict[str, float | None], profile_names: list[str]) -> float | None:
    values = [
        float(profile_scores[name])
        for name in profile_names
        if profile_scores.get(name) is not None
    ]
    if not values:
        return None
    return sum(values) / len(values)


def build_scouting_all_positions_xlsx(
    *,
    sheets: list[dict[str, Any]],
    generated_at: str,
    leagues: list[str],
    min_minutes: float,
    season_mode_label: str,
    scoring_note: str,
) -> bytes:
    if not sheets:
        raise ValueError("No position sheets to export.")

    buffer = BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
    used_names: set[str] = set()
    league_text = ", ".join(leagues)
    meta_lines = [
        f"Generated: {generated_at}",
        f"Season: {season_mode_label}",
        f"Leagues: {league_text}" if league_text else "Leagues: (none)",
        f"Min minutes: {min_minutes:.0f}",
        scoring_note,
    ]
    meta_lines = [line for line in meta_lines if line]

    for sheet in sheets:
        position_label = str(sheet.get("positionLabel") or sheet.get("position_label") or "Position")
        profiles = sheet.get("profiles") or []
        profile_columns = [
            (profile.get("apiName") or profile.get("api_name") or "", profile.get("label") or "")
            for profile in profiles
        ]
        profile_names = [api_name for api_name, _ in profile_columns if api_name]

        ranked_players: list[dict[str, Any]] = []
        for player in sheet.get("players") or []:
            profile_scores = player.get("profileScores") or player.get("profile_scores") or {}
            overall = _equal_weight_overall(profile_scores, profile_names)
            if overall is None:
                continue
            ranked_players.append({**player, "overall": overall, "profileScores": profile_scores})

        ranked_players.sort(key=lambda item: item.get("overall") or -1, reverse=True)

        export_players = []
        for index, player in enumerate(ranked_players, start=1):
            export_players.append(
                type(
                    "PlayerRow",
                    (),
                    {
                        "rank": index,
                        "name": player.get("name", ""),
                        "age": player.get("age"),
                        "minutes": player.get("minutes"),
                        "height": player.get("height", ""),
                        "foot": player.get("foot", ""),
                        "league": player.get("league", ""),
                        "club": player.get("club", ""),
                        "overall": player.get("overall"),
                        "profileScores": player.get("profileScores") or {},
                    },
                )()
            )

        profile_export = [
            type("ProfileCol", (), {"api_name": api, "apiName": api, "label": label, "weight": 0})()
            for api, label in profile_columns
        ]

        _write_list_sheet(
            workbook,
            _excel_sheet_name(position_label, used_names),
            title=f"{position_label} — scouting long list",
            meta_lines=meta_lines,
            profile_columns=[(p.api_name, p.label) for p in profile_export],
            players=export_players,
        )

    workbook.close()
    return buffer.getvalue()
