from __future__ import annotations

import math
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from fpdf import FPDF

from app.pdf_report import SLIDE_HEIGHT_MM, SLIDE_WIDTH_MM, pdf_safe

FRAME_INSET_MM = 5.0
INNER_PAD_MM = 10.0

BG = (13, 13, 13)
GOLD = (245, 197, 24)
ACCENT = (52, 211, 153)
CARD = (26, 26, 26)
CARD_BORDER = (42, 42, 42)
PANEL_ALT = (32, 32, 32)
TEXT = (245, 245, 245)
MUTED = (156, 163, 175)
DIM = (107, 114, 128)

LIVE = (52, 211, 153)
VIDEO = (251, 191, 36)
NOT_COVERED = (71, 85, 105)

LEAGUE_COLORS: dict[str, tuple[int, int, int]] = {
    "League One": (61, 139, 253),
    "League Two": (52, 211, 153),
    "National League": (251, 191, 36),
    "Scottish Prem": (167, 139, 250),
    "PL2": (249, 115, 22),
    "Irish Prem": (34, 211, 238),
}

FALLBACK_COLORS: list[tuple[int, int, int]] = [
    (56, 189, 248),
    (244, 114, 182),
    (74, 222, 128),
    (250, 204, 21),
    (196, 181, 253),
    (251, 146, 60),
]

COVERAGE_SEGMENTS = (
    ("Live games covered", "live", LIVE),
    ("Video games covered", "video", VIDEO),
    ("Games not covered", "not_covered", NOT_COVERED),
)


def _league_color(league: str, index: int = 0) -> tuple[int, int, int]:
    return LEAGUE_COLORS.get(league) or FALLBACK_COLORS[index % len(FALLBACK_COLORS)]


def _pie_slice_points(
    cx: float,
    cy: float,
    radius: float,
    start_deg: float,
    end_deg: float,
    *,
    steps: int = 48,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = [(cx, cy)]
    for step in range(steps + 1):
        angle = math.radians(start_deg + (end_deg - start_deg) * step / steps)
        points.append((cx + radius * math.cos(angle), cy - radius * math.sin(angle)))
    return points


def _league_scout_breakdown(
    staff_rows: list[dict[str, Any]],
    league: str,
) -> list[tuple[str, int, int, int]]:
    scout_stats: dict[str, dict[str, Any]] = {}
    for row in staff_rows:
        scout = str(row.get("staff") or "")
        bucket = scout_stats.setdefault(scout, {"live": 0, "video": 0, "seen": set()})
        seen: set[str] = bucket["seen"]
        for fixture in row.get("fixtures") or []:
            if str(fixture.get("league") or "") != league:
                continue
            fixture_id = str(fixture.get("fixture_id") or "")
            if fixture_id and fixture_id in seen:
                continue
            if fixture_id:
                seen.add(fixture_id)
            watch_type = str(fixture.get("watch_type") or "").strip().upper()
            if watch_type == "LIVE":
                bucket["live"] = int(bucket["live"]) + 1
            elif watch_type == "VIDEO":
                bucket["video"] = int(bucket["video"]) + 1

    rows: list[tuple[str, int, int, int]] = []
    for scout, bucket in scout_stats.items():
        live = int(bucket["live"])
        video = int(bucket["video"])
        total = live + video
        if total:
            rows.append((scout, live, video, total))
    return sorted(rows, key=lambda item: (-item[3], item[0]))


def _format_filters(data: dict[str, Any]) -> str:
    parts = [
        f"Period: {data.get('period_label') or 'All time'}",
        f"Season: {', '.join(data.get('seasons') or ['All'])}",
    ]
    staff = str(data.get("staff_filter") or "").strip()
    if staff:
        parts.append(f"Scout: {staff}")
    generated = data.get("generated_at")
    if generated:
        try:
            stamp = datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
            parts.append(stamp.astimezone().strftime("%d %b %Y %H:%M"))
        except ValueError:
            pass
    return " · ".join(parts)


class ScoutSummaryPDF(FPDF):
    """16:9 widescreen scout summary — dark Keynote-style deck."""

    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format=(SLIDE_WIDTH_MM, SLIDE_HEIGHT_MM))
        self.set_auto_page_break(auto=False)
        self.set_margins(0, 0, 0)
        self.set_display_mode(zoom="fullpage", layout="single")
        self.alias_nb_pages()

    def _fill_rgb(self, color: tuple[int, int, int]) -> None:
        self.set_fill_color(*color)

    def _text_rgb(self, color: tuple[int, int, int]) -> None:
        self.set_text_color(*color)

    def _draw_rgb(self, color: tuple[int, int, int]) -> None:
        self.set_draw_color(*color)

    def _frame_rect(self) -> tuple[float, float, float, float]:
        x = FRAME_INSET_MM
        y = FRAME_INSET_MM
        width = SLIDE_WIDTH_MM - (FRAME_INSET_MM * 2)
        height = SLIDE_HEIGHT_MM - (FRAME_INSET_MM * 2)
        self._fill_rgb(BG)
        self._draw_rgb(GOLD)
        self.set_line_width(0.9)
        self.rect(x, y, width, height, style="DF")
        return x, y, width, height

    def _inner_bounds(
        self,
    ) -> tuple[float, float, float, float]:
        frame_x, frame_y, frame_w, frame_h = self._frame_rect()
        return (
            frame_x + INNER_PAD_MM,
            frame_y + INNER_PAD_MM,
            frame_w - (INNER_PAD_MM * 2),
            frame_h - (INNER_PAD_MM * 2),
        )

    def _slide_header(
        self,
        inner_x: float,
        inner_y: float,
        inner_w: float,
        *,
        eyebrow: str,
        title: str,
        subtitle: str = "",
        accent: tuple[int, int, int] | None = None,
    ) -> float:
        accent = accent or GOLD
        self.set_xy(inner_x, inner_y)
        self.set_font("Helvetica", "B", 10)
        self._text_rgb(accent)
        self.cell(inner_w, 5, pdf_safe(eyebrow))

        y = inner_y + 7
        self.set_xy(inner_x, y)
        self.set_font("Helvetica", "B", 22)
        self._text_rgb(TEXT)
        self.cell(inner_w, 10, pdf_safe(title))
        y += 12

        if subtitle:
            self.set_xy(inner_x, y)
            self.set_font("Helvetica", "", 11)
            self._text_rgb(MUTED)
            self.cell(inner_w, 5, pdf_safe(subtitle))
            y += 8
        return y + 2

    def _draw_card(self, x: float, y: float, w: float, h: float) -> None:
        self._fill_rgb(CARD)
        self._draw_rgb(CARD_BORDER)
        self.set_line_width(0.35)
        self.rect(x, y, w, h, style="DF")

    def _kpi_row(
        self,
        x: float,
        y: float,
        w: float,
        items: list[tuple[str, str, str]],
    ) -> float:
        gap = 5.0
        card_w = (w - gap * (len(items) - 1)) / len(items)
        card_h = 24.0
        for index, (value, label, hint) in enumerate(items):
            card_x = x + index * (card_w + gap)
            self._draw_card(card_x, y, card_w, card_h)
            self.set_xy(card_x + 4, y + 4)
            self.set_font("Helvetica", "B", 20)
            self._text_rgb(TEXT)
            self.cell(card_w - 8, 9, pdf_safe(value), align="C")
            self.set_xy(card_x + 4, y + 13)
            self.set_font("Helvetica", "B", 8.5)
            self._text_rgb(GOLD)
            self.cell(card_w - 8, 4, pdf_safe(label), align="C")
            if hint:
                self.set_xy(card_x + 4, y + 17.5)
                self.set_font("Helvetica", "", 7)
                self._text_rgb(DIM)
                self.cell(card_w - 8, 3.5, pdf_safe(hint), align="C")
        return y + card_h

    def _table_header_dark(
        self,
        x: float,
        y: float,
        columns: list[tuple[str, float]],
    ) -> float:
        row_h = 7.0
        self._fill_rgb((31, 41, 55))
        total_w = sum(width for _label, width in columns)
        cursor_x = x
        for label, width in columns:
            self.set_xy(cursor_x + 2, y + 1.5)
            self.set_font("Helvetica", "B", 8.5)
            self._text_rgb(GOLD)
            self.cell(width - 4, 4, pdf_safe(label))
            cursor_x += width
        self._draw_rgb(CARD_BORDER)
        self.rect(x, y, total_w, row_h, style="D")
        return y + row_h

    def _table_row_dark(
        self,
        x: float,
        y: float,
        columns: list[tuple[str, float]],
        *,
        shaded: bool = False,
        bold_first: bool = False,
    ) -> float:
        row_h = 6.8
        total_w = sum(width for _label, width in columns)
        if shaded:
            self._fill_rgb((20, 20, 20))
            self.rect(x, y, total_w, row_h, style="F")
        cursor_x = x
        for index, (value, width) in enumerate(columns):
            self.set_xy(cursor_x + 2, y + 1.2)
            if index == 0 and bold_first:
                self.set_font("Helvetica", "B", 9)
                self._text_rgb(TEXT)
            else:
                self.set_font("Helvetica", "", 9)
                self._text_rgb(MUTED if index else TEXT)
            self.cell(width - 4, 4.5, pdf_safe(value))
            cursor_x += width
        return y + row_h

    def _draw_donut(
        self,
        cx: float,
        cy: float,
        outer_r: float,
        inner_r: float,
        segments: list[tuple[int, tuple[int, int, int]]],
        *,
        center_value: str,
        center_label: str,
        value_font_size: int = 18,
        label_font_size: int = 8,
    ) -> None:
        total = sum(count for count, _color in segments)
        start = 0.0
        if total <= 0:
            self._fill_rgb(NOT_COVERED)
            self.ellipse(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2, style="F")
        else:
            for count, color in segments:
                if count <= 0:
                    continue
                sweep = (count / total) * 360.0
                self._fill_rgb(color)
                self.polygon(
                    _pie_slice_points(cx, cy, outer_r, start, start + sweep),
                    style="F",
                )
                start += sweep

        if total > 0:
            self._draw_rgb(BG)
            self.set_line_width(0.35)
            start = 0.0
            for count, _color in segments:
                if count <= 0:
                    continue
                sweep = (count / total) * 360.0
                edge = _pie_slice_points(cx, cy, outer_r, start + sweep, start + sweep, steps=1)
                if len(edge) > 1:
                    self.line(cx, cy, edge[1][0], edge[1][1])
                start += sweep

        self._fill_rgb(BG)
        self.ellipse(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2, style="F")
        value_offset = value_font_size * 0.38
        label_offset = value_font_size * 0.12
        self.set_xy(cx - inner_r, cy - value_offset)
        self.set_font("Helvetica", "B", value_font_size)
        self._text_rgb(TEXT)
        self.cell(inner_r * 2, value_font_size * 0.45, pdf_safe(center_value), align="C")
        self.set_xy(cx - inner_r, cy + label_offset)
        self.set_font("Helvetica", "", label_font_size)
        self._text_rgb(MUTED)
        self.cell(inner_r * 2, label_font_size * 0.5, pdf_safe(center_label), align="C")

    def _draw_coverage_bar(
        self,
        x: float,
        y: float,
        width: float,
        *,
        label: str,
        count: int,
        pct: float,
        color: tuple[int, int, int],
        max_count: int,
    ) -> float:
        label_w = 62.0
        value_w = 28.0
        track_w = max(width - label_w - value_w - 4, 40.0)
        track_h = 8.0

        self.set_xy(x, y + 1)
        self.set_font("Helvetica", "B", 9)
        self._text_rgb(TEXT)
        self.cell(label_w, 4.5, pdf_safe(label))

        track_x = x + label_w
        self._fill_rgb((38, 38, 38))
        self._draw_rgb(CARD_BORDER)
        self.rect(track_x, y + 0.5, track_w, track_h, style="DF")
        fill_w = track_w * (count / max_count) if max_count else 0.0
        if fill_w > 0:
            self._fill_rgb(color)
            self.rect(track_x, y + 0.5, fill_w, track_h, style="F")

        self.set_xy(track_x + track_w + 2, y + 1)
        self.set_font("Helvetica", "B", 8.5)
        self._text_rgb(color)
        self.cell(value_w, 4.5, pdf_safe(f"{count} ({pct:.1f}%)"), align="R")
        return y + 11.5

    def add_overview_slide(self, data: dict[str, Any], staff_rows: list[dict[str, Any]]) -> None:
        totals = data.get("totals") or {}
        self.add_page()
        inner_x, inner_y, inner_w, inner_h = self._inner_bounds()
        cursor_y = self._slide_header(
            inner_x,
            inner_y,
            inner_w,
            eyebrow="PORT VALE F.C. · SCOUTING OPERATIONS",
            title="SCOUT SUMMARY",
            subtitle=_format_filters(data),
        )

        assigned = int(totals.get("assigned") or 0)
        live = int(totals.get("live") or 0)
        video = int(totals.get("video") or 0)
        reports = int(totals.get("scouting_reports") or 0)
        covered_pct = ((live + video) / assigned * 100.0) if assigned else 0.0

        covered = live + video
        mix_den = covered or 1
        cursor_y = self._kpi_row(
            inner_x,
            cursor_y,
            inner_w,
            [
                (str(assigned), "GAMES COVERED", "Assigned fixtures"),
                (str(live), "LIVE", f"{(live / mix_den * 100):.0f}% of covered mix"),
                (str(video), "VIDEO", f"{(video / mix_den * 100):.0f}% of covered mix"),
                (str(reports), "PLAYER REPORTS", "Marked in period"),
            ],
        )
        cursor_y += 8

        table_h = inner_y + inner_h - cursor_y - 4
        self._draw_card(inner_x, cursor_y, inner_w, table_h)
        table_x = inner_x + 6
        table_w = inner_w - 12
        header_y = cursor_y + 6
        self.set_xy(table_x, header_y)
        self.set_font("Helvetica", "B", 11)
        self._text_rgb(GOLD)
        self.cell(table_w, 5, "COVERAGE BY SCOUT")
        header_y += 8

        name_w = table_w * 0.46
        num_w = (table_w - name_w) / 3
        columns = [("Scout", name_w), ("Total", num_w), ("Live", num_w), ("Video", num_w)]
        row_y = self._table_header_dark(table_x, header_y, columns)
        for index, row in enumerate(staff_rows):
            row_y = self._table_row_dark(
                table_x,
                row_y,
                [
                    (str(row.get("staff") or ""), name_w),
                    (str(row.get("total") or 0), num_w),
                    (str(row.get("live") or 0), num_w),
                    (str(row.get("video") or 0), num_w),
                ],
                shaded=index % 2 == 1,
                bold_first=True,
            )

        self.set_xy(inner_x, inner_y + inner_h - 5)
        self.set_font("Helvetica", "", 8)
        self._text_rgb(DIM)
        self.cell(
            inner_w,
            4,
            pdf_safe(f"Live + video split across {assigned} covered games ({covered_pct:.0f}% live/video mix)"),
            align="R",
        )

    def add_league_slide(
        self,
        data: dict[str, Any],
        league_row: dict[str, Any],
        staff_rows: list[dict[str, Any]],
        *,
        league_index: int,
    ) -> None:
        league = str(league_row.get("league") or "Unknown")
        live = int(league_row.get("live") or 0)
        video = int(league_row.get("video") or 0)
        not_covered = int(league_row.get("not_covered") or 0)
        total = int(league_row.get("total") or (live + video + not_covered))
        covered = live + video
        coverage_pct = (covered / total * 100.0) if total else 0.0
        accent = _league_color(league, league_index)

        self.add_page()
        inner_x, inner_y, inner_w, inner_h = self._inner_bounds()
        cursor_y = self._slide_header(
            inner_x,
            inner_y,
            inner_w,
            eyebrow="PORT VALE F.C. · LEAGUE COVERAGE",
            title=pdf_safe(league).upper(),
            subtitle=_format_filters(data),
            accent=accent,
        )

        left_w = inner_w * 0.38
        right_x = inner_x + left_w + 10
        right_w = inner_w - left_w - 10
        panel_top = cursor_y
        panel_h = inner_y + inner_h - panel_top

        self._draw_card(inner_x, panel_top, left_w, panel_h)
        donut_cx = inner_x + left_w / 2
        donut_cy = panel_top + panel_h / 2 - 4
        self._draw_donut(
            donut_cx,
            donut_cy,
            outer_r=34,
            inner_r=22,
            segments=[
                (live, LIVE),
                (video, VIDEO),
                (not_covered, NOT_COVERED),
            ],
            center_value=f"{coverage_pct:.1f}%",
            center_label="covered",
        )

        legend_y = panel_top + panel_h - 18
        legend_x = inner_x + 10
        for label, _key, color in COVERAGE_SEGMENTS:
            self._fill_rgb(color)
            self.rect(legend_x, legend_y + 1, 3, 3, style="F")
            self.set_xy(legend_x + 5, legend_y)
            self.set_font("Helvetica", "", 7.5)
            self._text_rgb(MUTED)
            self.cell(34, 4, pdf_safe(label.split(" games")[0]))
            legend_x += 38

        self.set_xy(inner_x, panel_top + panel_h - 10)
        self.set_font("Helvetica", "", 8.5)
        self._text_rgb(MUTED)
        self.cell(left_w, 4, pdf_safe(f"{total} games in period"), align="C")

        self._draw_card(right_x, panel_top, right_w, panel_h)
        detail_x = right_x + 8
        detail_w = right_w - 16
        detail_y = panel_top + 8

        self.set_xy(detail_x, detail_y)
        self.set_font("Helvetica", "B", 11)
        self._text_rgb(GOLD)
        self.cell(detail_w, 5, "BREAKDOWN")
        detail_y += 9

        stat_w = (detail_w - 8) / 3
        stats = [
            (str(total), "IN PERIOD", DIM),
            (str(covered), "COVERED", accent),
            (str(not_covered), "NOT COVERED", NOT_COVERED),
        ]
        for index, (value, label, color) in enumerate(stats):
            box_x = detail_x + index * (stat_w + 4)
            self._fill_rgb((20, 20, 20))
            self._draw_rgb(CARD_BORDER)
            self.rect(box_x, detail_y, stat_w, 18, style="DF")
            self.set_xy(box_x, detail_y + 3)
            self.set_font("Helvetica", "B", 16)
            self._text_rgb(color)
            self.cell(stat_w, 7, pdf_safe(value), align="C")
            self.set_xy(box_x, detail_y + 11)
            self.set_font("Helvetica", "B", 7.5)
            self._text_rgb(MUTED)
            self.cell(stat_w, 4, pdf_safe(label), align="C")
        detail_y += 26

        counts = {
            "live": live,
            "video": video,
            "not_covered": not_covered,
        }
        max_count = max(total, 1)
        for label, key, color in COVERAGE_SEGMENTS:
            count = counts[key]
            pct = (count / total * 100.0) if total else 0.0
            detail_y = self._draw_coverage_bar(
                detail_x,
                detail_y,
                detail_w,
                label=label,
                count=count,
                pct=pct,
                color=color,
                max_count=max_count,
            )
        detail_y += 4

        scout_rows = _league_scout_breakdown(staff_rows, league)
        self.set_xy(detail_x, detail_y)
        self.set_font("Helvetica", "B", 10)
        self._text_rgb(GOLD)
        self.cell(detail_w, 5, "SCOUT ACTIVITY IN LEAGUE")
        detail_y += 7

        scout_name_w = detail_w * 0.48
        scout_num_w = (detail_w - scout_name_w) / 3
        scout_columns = [
            ("Scout", scout_name_w),
            ("Live", scout_num_w),
            ("Video", scout_num_w),
            ("Total", scout_num_w),
        ]
        detail_y = self._table_header_dark(detail_x, detail_y, scout_columns)
        if not scout_rows:
            detail_y = self._table_row_dark(
                detail_x,
                detail_y,
                [("No assignments in this league", detail_w)],
                bold_first=True,
            )
        else:
            for index, (scout, scout_live, scout_video, scout_total) in enumerate(scout_rows[:6]):
                detail_y = self._table_row_dark(
                    detail_x,
                    detail_y,
                    [
                        (scout, scout_name_w),
                        (str(scout_live), scout_num_w),
                        (str(scout_video), scout_num_w),
                        (str(scout_total), scout_num_w),
                    ],
                    shaded=index % 2 == 1,
                    bold_first=True,
                )

    def add_player_reports_slide(
        self,
        data: dict[str, Any],
        player_reports: list[dict[str, Any]],
        *,
        page_index: int = 0,
        page_size: int = 16,
    ) -> None:
        start = page_index * page_size
        chunk = player_reports[start : start + page_size]
        if not chunk and page_index > 0:
            return

        self.add_page()
        inner_x, inner_y, inner_w, inner_h = self._inner_bounds()
        title_suffix = ""
        total_pages = max(1, math.ceil(len(player_reports) / page_size))
        if total_pages > 1:
            title_suffix = f" ({page_index + 1}/{total_pages})"

        cursor_y = self._slide_header(
            inner_x,
            inner_y,
            inner_w,
            eyebrow="PORT VALE F.C. · SCOUTING OPERATIONS",
            title=f"PLAYERS WITH REPORTS{title_suffix}",
            subtitle=f"{len(player_reports)} players · {_format_filters(data)}",
        )

        panel_h = inner_y + inner_h - cursor_y
        self._draw_card(inner_x, cursor_y, inner_w, panel_h)
        table_x = inner_x + 8
        table_w = inner_w - 16
        row_y = cursor_y + 8

        player_w = table_w * 0.34
        team_w = table_w * 0.30
        pos_w = table_w * 0.16
        count_w = table_w - player_w - team_w - pos_w
        columns = [
            ("Player", player_w),
            ("Team", team_w),
            ("Pos", pos_w),
            ("Reports", count_w),
        ]
        row_y = self._table_header_dark(table_x, row_y, columns)

        if not chunk:
            self._table_row_dark(
                table_x,
                row_y,
                [("No player reports marked in this period.", table_w)],
                bold_first=True,
            )
            return

        for index, row in enumerate(chunk):
            row_y = self._table_row_dark(
                table_x,
                row_y,
                [
                    (str(row.get("player_name") or ""), player_w),
                    (str(row.get("team") or ""), team_w),
                    (str(row.get("position_label") or "—"), pos_w),
                    (str(row.get("report_count") or 0), count_w),
                ],
                shaded=index % 2 == 1,
                bold_first=True,
            )

        remaining = len(player_reports) - (start + len(chunk))
        if remaining > 0:
            self.set_xy(table_x, row_y + 2)
            self.set_font("Helvetica", "I", 8)
            self._text_rgb(DIM)
            self.cell(table_w, 4, pdf_safe(f"+ {remaining} more on following slide(s)"))

    def _draw_stacked_team_row(
        self,
        x: float,
        y: float,
        width: float,
        *,
        team: str,
        live: int,
        video: int,
        not_seen: int,
        max_total: int,
    ) -> float:
        label_w = 54.0
        total_w = 12.0
        track_w = max(width - label_w - total_w - 4, 50.0)
        row_h = 7.5
        total = live + video + not_seen
        scale = track_w / max(max_total, 1)

        self.set_xy(x, y + 1)
        self.set_font("Helvetica", "B", 8.5)
        self._text_rgb(TEXT)
        self.cell(label_w, 4.5, pdf_safe(team[:30]))

        track_x = x + label_w
        self._fill_rgb((38, 38, 38))
        self._draw_rgb(CARD_BORDER)
        self.rect(track_x, y + 0.8, track_w, row_h - 1.5, style="DF")

        cursor = track_x
        for count, color in ((live, LIVE), (video, VIDEO), (not_seen, NOT_COVERED)):
            seg_w = count * scale
            if seg_w <= 0:
                continue
            self._fill_rgb(color)
            self.rect(cursor, y + 0.8, seg_w, row_h - 1.5, style="F")
            cursor += seg_w

        self.set_xy(track_x + track_w + 2, y + 1.2)
        self.set_font("Helvetica", "", 8)
        self._text_rgb(MUTED)
        self.cell(total_w, 4, pdf_safe(str(total)), align="R")
        return y + 9.5

    def add_team_exposure_slide(
        self,
        data: dict[str, Any],
        league_row: dict[str, Any],
        *,
        league_index: int,
    ) -> None:
        league = str(league_row.get("league") or "Unknown")
        teams = league_row.get("teams") or []
        accent = _league_color(league, league_index)

        self.add_page()
        inner_x, inner_y, inner_w, inner_h = self._inner_bounds()
        cursor_y = self._slide_header(
            inner_x,
            inner_y,
            inner_w,
            eyebrow="PORT VALE F.C. · TEAM EXPOSURE",
            title=pdf_safe(league).upper(),
            subtitle=_format_filters(data),
            accent=accent,
        )

        panel_h = inner_y + inner_h - cursor_y
        self._draw_card(inner_x, cursor_y, inner_w, panel_h)
        detail_x = inner_x + 8
        detail_w = inner_w - 16
        detail_y = cursor_y + 8

        self.set_xy(detail_x, detail_y)
        self.set_font("Helvetica", "B", 10)
        self._text_rgb(GOLD)
        self.cell(detail_w, 5, "GAMES PER TEAM")
        detail_y += 8

        legend_x = detail_x
        for label, color in (("Live", LIVE), ("Video", VIDEO), ("Not seen", NOT_COVERED)):
            self._fill_rgb(color)
            self.rect(legend_x, detail_y + 1, 3, 3, style="F")
            self.set_xy(legend_x + 5, detail_y)
            self.set_font("Helvetica", "", 8)
            self._text_rgb(MUTED)
            self.cell(24, 4, pdf_safe(label))
            legend_x += 30
        detail_y += 10

        if not teams:
            self.set_xy(detail_x, detail_y)
            self.set_font("Helvetica", "", 9)
            self._text_rgb(MUTED)
            self.cell(detail_w, 5, "No team data for this league in the selected period.")
            return

        max_total = max(int(row.get("total") or 0) for row in teams)
        for team_row in teams:
            if detail_y > inner_y + inner_h - 12:
                break
            detail_y = self._draw_stacked_team_row(
                detail_x,
                detail_y,
                detail_w,
                team=str(team_row.get("team") or ""),
                live=int(team_row.get("live") or 0),
                video=int(team_row.get("video") or 0),
                not_seen=int(team_row.get("not_seen") or 0),
                max_total=max_total,
            )

    def add_one_pager_slide(
        self,
        data: dict[str, Any],
        league_coverage: list[dict[str, Any]],
    ) -> None:
        totals = data.get("totals") or {}
        self.add_page()
        inner_x, inner_y, inner_w, inner_h = self._inner_bounds()
        cursor_y = self._slide_header(
            inner_x,
            inner_y,
            inner_w,
            eyebrow="PORT VALE F.C. · SCOUTING OPERATIONS",
            title="SCOUT SUMMARY",
            subtitle=_format_filters(data),
        )

        assigned = int(totals.get("assigned") or 0)
        live = int(totals.get("live") or 0)
        video = int(totals.get("video") or 0)
        reports = int(totals.get("scouting_reports") or 0)
        covered = live + video
        mix_den = covered or 1

        cursor_y = self._kpi_row(
            inner_x,
            cursor_y,
            inner_w,
            [
                (str(assigned), "GAMES COVERED", "Assigned fixtures"),
                (str(live), "LIVE", f"{(live / mix_den * 100):.0f}% of covered"),
                (str(video), "VIDEO", f"{(video / mix_den * 100):.0f}% of covered"),
                (str(reports), "PLAYER REPORTS", "Marked in period"),
            ],
        )
        cursor_y += 6

        legend_x = inner_x
        for label, color in (("Live", LIVE), ("Video", VIDEO), ("Not covered", NOT_COVERED)):
            self._fill_rgb(color)
            self.rect(legend_x, cursor_y + 1, 3, 3, style="F")
            self.set_xy(legend_x + 5, cursor_y)
            self.set_font("Helvetica", "B", 8)
            self._text_rgb(MUTED)
            self.cell(28, 4, pdf_safe(label))
            legend_x += 34
        cursor_y += 8

        leagues = league_coverage or []
        if not leagues:
            self.set_xy(inner_x, cursor_y + 8)
            self.set_font("Helvetica", "", 10)
            self._text_rgb(MUTED)
            self.cell(inner_w, 6, "No league coverage data for this period.", align="C")
            return

        grid_top = cursor_y
        grid_h = inner_y + inner_h - grid_top - 2
        cols = min(len(leagues), 5)
        rows = math.ceil(len(leagues) / cols)
        cell_w = inner_w / cols
        cell_h = grid_h / rows
        gap = 3.0

        for index, league_row in enumerate(leagues):
            row = index // cols
            col = index % cols
            card_x = inner_x + col * cell_w + (gap / 2)
            card_y = grid_top + row * cell_h + (gap / 2)
            card_w = cell_w - gap
            card_h = cell_h - gap
            self._draw_league_mini_card(card_x, card_y, card_w, card_h, league_row, index)

    def _draw_league_mini_card(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        league_row: dict[str, Any],
        league_index: int,
    ) -> None:
        league = str(league_row.get("league") or "Unknown")
        live = int(league_row.get("live") or 0)
        video = int(league_row.get("video") or 0)
        not_covered = int(league_row.get("not_covered") or 0)
        total = int(league_row.get("total") or (live + video + not_covered))
        covered = live + video
        coverage_pct = (covered / total * 100.0) if total else 0.0
        accent = _league_color(league, league_index)

        self._draw_card(x, y, width, height)

        self.set_xy(x, y + 4)
        self.set_font("Helvetica", "B", 10)
        self._text_rgb(accent)
        self.cell(width, 5, pdf_safe(league), align="C")

        outer_r = min(width / 2 - 8, height / 2 - 18, 28.0)
        inner_r = outer_r * 0.62
        cx = x + width / 2
        cy = y + height / 2 + 2
        self._draw_donut(
            cx,
            cy,
            outer_r=outer_r,
            inner_r=inner_r,
            segments=[
                (live, LIVE),
                (video, VIDEO),
                (not_covered, NOT_COVERED),
            ],
            center_value=f"{coverage_pct:.0f}%",
            center_label="covered",
            value_font_size=12 if outer_r < 24 else 18,
            label_font_size=7 if outer_r < 24 else 8,
        )

        stats_y = y + height - 16
        self.set_xy(x + 3, stats_y)
        self.set_font("Helvetica", "", 7)
        self._text_rgb(MUTED)
        self.cell(width - 6, 3.5, pdf_safe(f"Live {live} · Video {video} · Not {not_covered}"), align="C")
        self.set_xy(x + 3, stats_y + 4)
        self.set_font("Helvetica", "B", 7.5)
        self._text_rgb(DIM)
        self.cell(width - 6, 3.5, pdf_safe(f"{total} games in period"), align="C")

    def add_two_pager_ops_slide(
        self,
        data: dict[str, Any],
        league_coverage: list[dict[str, Any]],
        staff_teams: list[dict[str, Any]],
    ) -> None:
        totals = data.get("totals") or {}
        self.add_page()
        inner_x, inner_y, inner_w, inner_h = self._inner_bounds()
        cursor_y = self._slide_header(
            inner_x,
            inner_y,
            inner_w,
            eyebrow="PORT VALE F.C. · WEEKLY TWO-PAGER · 1/2",
            title="SCOUT OPS SNAPSHOT",
            subtitle=_format_filters(data),
        )

        assigned = int(totals.get("assigned") or 0)
        live = int(totals.get("live") or 0)
        video = int(totals.get("video") or 0)
        reports = int(totals.get("scouting_reports") or 0)
        covered = live + video
        mix_den = covered or 1
        cursor_y = self._kpi_row(
            inner_x,
            cursor_y,
            inner_w,
            [
                (str(assigned), "GAMES COVERED", "Assigned fixtures"),
                (str(live), "LIVE", f"{(live / mix_den * 100):.0f}% of covered"),
                (str(video), "VIDEO", f"{(video / mix_den * 100):.0f}% of covered"),
                (str(reports), "PLAYER REPORTS", "Marked in period"),
            ],
        )
        cursor_y += 5

        left_w = inner_w * 0.46
        right_x = inner_x + left_w + 8
        right_w = inner_w - left_w - 8
        panel_h = inner_y + inner_h - cursor_y

        self._draw_card(inner_x, cursor_y, left_w, panel_h)
        self.set_xy(inner_x + 5, cursor_y + 5)
        self.set_font("Helvetica", "B", 10)
        self._text_rgb(GOLD)
        self.cell(left_w - 10, 5, "GAMES SEEN BY TEAM")

        row_y = cursor_y + 14
        for team in staff_teams or []:
            if row_y > cursor_y + panel_h - 18:
                break
            self.set_xy(inner_x + 5, row_y)
            self.set_font("Helvetica", "B", 9)
            self._text_rgb(TEXT)
            self.cell(left_w - 40, 4.5, pdf_safe(str(team.get("label") or "")))
            self.set_font("Helvetica", "B", 9)
            self._text_rgb(ACCENT)
            self.cell(30, 4.5, pdf_safe(str(team.get("total") or 0)), align="R")
            row_y += 5
            self.set_xy(inner_x + 5, row_y)
            self.set_font("Helvetica", "", 7.5)
            self._text_rgb(MUTED)
            self.cell(
                left_w - 10,
                3.5,
                pdf_safe(
                    f"Live {team.get('live') or 0} · Video {team.get('video') or 0}"
                    f" · Avg {team.get('avg_per_member') or 0}/person"
                ),
            )
            row_y += 7
            for member in (team.get("members") or [])[:6]:
                if row_y > cursor_y + panel_h - 8:
                    break
                self.set_xy(inner_x + 8, row_y)
                self.set_font("Helvetica", "", 8)
                self._text_rgb(MUTED)
                self.cell(left_w - 42, 3.8, pdf_safe(str(member.get("staff") or "")))
                self._text_rgb(TEXT)
                self.cell(28, 3.8, pdf_safe(str(member.get("total") or 0)), align="R")
                row_y += 4.2

        self._draw_card(right_x, cursor_y, right_w, panel_h)
        self.set_xy(right_x + 5, cursor_y + 5)
        self.set_font("Helvetica", "B", 10)
        self._text_rgb(GOLD)
        self.cell(right_w - 10, 5, "LEAGUE COVERAGE")

        leagues = league_coverage or []
        if not leagues:
            self.set_xy(right_x + 5, cursor_y + 24)
            self.set_font("Helvetica", "", 9)
            self._text_rgb(MUTED)
            self.cell(right_w - 10, 5, "No league coverage in this period.")
            return

        grid_top = cursor_y + 14
        grid_h = panel_h - 18
        cols = min(len(leagues), 3)
        rows = math.ceil(len(leagues) / cols)
        cell_w = (right_w - 10) / cols
        cell_h = grid_h / rows
        for index, league_row in enumerate(leagues):
            row = index // cols
            col = index % cols
            card_x = right_x + 5 + col * cell_w
            card_y = grid_top + row * cell_h
            self._draw_league_mini_card(
                card_x + 1,
                card_y + 1,
                cell_w - 2,
                cell_h - 2,
                league_row,
                index,
            )

    def add_two_pager_focus_slide(
        self,
        data: dict[str, Any],
        player_reports: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        least_seen_teams: list[Any],
    ) -> None:
        self.add_page()
        inner_x, inner_y, inner_w, inner_h = self._inner_bounds()
        cursor_y = self._slide_header(
            inner_x,
            inner_y,
            inner_w,
            eyebrow="PORT VALE F.C. · WEEKLY TWO-PAGER · 2/2",
            title="COVERAGE & RECOMMENDATIONS",
            subtitle=_format_filters(data),
        )

        left_w = inner_w * 0.58
        right_x = inner_x + left_w + 8
        right_w = inner_w - left_w - 8
        panel_h = inner_y + inner_h - cursor_y

        self._draw_card(inner_x, cursor_y, left_w, panel_h)
        self.set_xy(inner_x + 5, cursor_y + 5)
        self.set_font("Helvetica", "B", 10)
        self._text_rgb(GOLD)
        self.cell(left_w - 10, 5, "PLAYER REPORTS")

        name_w = left_w * 0.38
        team_w = left_w * 0.28
        pos_w = left_w * 0.16
        count_w = left_w * 0.12
        columns = [
            ("Player", name_w),
            ("Team", team_w),
            ("Pos", pos_w),
            ("Rpts", count_w),
        ]
        row_y = self._table_header_dark(inner_x + 5, cursor_y + 12, columns)
        rows = player_reports[:14] if player_reports else []
        if not rows:
            self.set_xy(inner_x + 5, row_y + 8)
            self.set_font("Helvetica", "", 9)
            self._text_rgb(MUTED)
            self.cell(left_w - 10, 5, "No player reports marked in this period.")
        else:
            for index, row in enumerate(rows):
                row_y = self._table_row_dark(
                    inner_x + 5,
                    row_y,
                    [
                        (str(row.get("player_name") or ""), name_w),
                        (str(row.get("team") or ""), team_w),
                        (str(row.get("position_label") or "—"), pos_w),
                        (str(row.get("report_count") or 0), count_w),
                    ],
                    shaded=index % 2 == 1,
                    bold_first=True,
                )

        top_h = panel_h * 0.55
        bottom_h = panel_h - top_h - 6
        self._draw_card(right_x, cursor_y, right_w, top_h)
        self.set_xy(right_x + 5, cursor_y + 5)
        self.set_font("Helvetica", "B", 10)
        self._text_rgb(GOLD)
        self.cell(right_w - 10, 5, "RECOMMENDATIONS")
        rec_y = cursor_y + 14
        recs = recommendations[:6] if recommendations else []
        if not recs:
            self.set_xy(right_x + 5, rec_y)
            self.set_font("Helvetica", "", 8.5)
            self._text_rgb(MUTED)
            self.cell(right_w - 10, 4.5, "Mark player reports to fill this list.")
        else:
            for row in recs:
                self.set_xy(right_x + 5, rec_y)
                self.set_font("Helvetica", "B", 8.5)
                self._text_rgb(TEXT)
                self.cell(right_w - 10, 4, pdf_safe(str(row.get("player_name") or "")))
                rec_y += 4
                self.set_xy(right_x + 5, rec_y)
                self.set_font("Helvetica", "", 7.5)
                self._text_rgb(MUTED)
                self.cell(
                    right_w - 10,
                    3.5,
                    pdf_safe(
                        f"{row.get('position_label') or '—'} · {row.get('team') or '—'}"
                        f" · {row.get('report_count') or 0} reports"
                    ),
                )
                rec_y += 6

        bottom_y = cursor_y + top_h + 6
        self._draw_card(right_x, bottom_y, right_w, bottom_h)
        self.set_xy(right_x + 5, bottom_y + 5)
        self.set_font("Helvetica", "B", 10)
        self._text_rgb(GOLD)
        self.cell(right_w - 10, 5, "LEAST SEEN TEAMS")
        least_y = bottom_y + 14
        least_rows = least_seen_teams[:8] if least_seen_teams else []
        if not least_rows:
            self.set_xy(right_x + 5, least_y)
            self.set_font("Helvetica", "", 8.5)
            self._text_rgb(MUTED)
            self.cell(right_w - 10, 4.5, "No team exposure data.")
        else:
            for item in least_rows:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    team_name, count = item[0], item[1]
                elif isinstance(item, dict):
                    team_name, count = item.get("team"), item.get("count")
                else:
                    continue
                self.set_xy(right_x + 5, least_y)
                self.set_font("Helvetica", "", 8)
                self._text_rgb(TEXT)
                self.cell(right_w - 28, 4, pdf_safe(str(team_name or "")))
                self._text_rgb(MUTED)
                self.cell(18, 4, pdf_safe(str(count)), align="R")
                least_y += 4.5

    def add_staff_teams_slide(
        self,
        data: dict[str, Any],
        staff_teams: list[dict[str, Any]],
    ) -> None:
        self.add_page()
        inner_x, inner_y, inner_w, inner_h = self._inner_bounds()
        cursor_y = self._slide_header(
            inner_x,
            inner_y,
            inner_w,
            eyebrow="PORT VALE F.C. · FULL REVIEW",
            title="GAMES SEEN BY STAFF TEAM",
            subtitle=_format_filters(data),
        )

        leagues = [str(row.get("ui") or "") for row in (data.get("league_coverage") or [])]
        if not leagues:
            leagues = sorted(
                {
                    league
                    for team in staff_teams
                    for league in (team.get("by_league") or {})
                }
            )[:6]

        name_w = 42.0
        total_w = 16.0
        league_cols = leagues[:6]
        league_w = (inner_w - name_w - total_w) / max(len(league_cols), 1)

        self._draw_card(inner_x, cursor_y, inner_w, inner_y + inner_h - cursor_y)
        row_y = cursor_y + 6
        self.set_xy(inner_x + 5, row_y)
        self.set_font("Helvetica", "B", 7.5)
        self._text_rgb(GOLD)
        self.cell(name_w, 4, "Staff")
        for league in league_cols:
            self.cell(league_w, 4, pdf_safe(league[:10]), align="C")
        self.cell(total_w, 4, "Total", align="R")
        row_y += 6

        for team in staff_teams or []:
            self.set_fill_color(*PANEL_ALT)
            self.rect(inner_x + 4, row_y - 0.5, inner_w - 8, 5, style="F")
            self.set_xy(inner_x + 5, row_y)
            self.set_font("Helvetica", "B", 8)
            self._text_rgb(ACCENT)
            self.cell(name_w, 4, pdf_safe(str(team.get("label") or "")))
            by_league = team.get("by_league") or {}
            for league in league_cols:
                self._text_rgb(TEXT)
                self.cell(league_w, 4, pdf_safe(str(by_league.get(league) or 0)), align="C")
            self.cell(total_w, 4, pdf_safe(str(team.get("total") or 0)), align="R")
            row_y += 6
            for member in team.get("members") or []:
                if row_y > inner_y + inner_h - 8:
                    break
                self.set_xy(inner_x + 8, row_y)
                self.set_font("Helvetica", "", 7.5)
                self._text_rgb(MUTED)
                self.cell(name_w - 3, 3.8, pdf_safe(str(member.get("staff") or "")))
                member_leagues = member.get("by_league") or {}
                for league in league_cols:
                    self._text_rgb(TEXT)
                    self.cell(
                        league_w,
                        3.8,
                        pdf_safe(str(member_leagues.get(league) or 0)),
                        align="C",
                    )
                self.cell(total_w, 3.8, pdf_safe(str(member.get("total") or 0)), align="R")
                row_y += 4.2
            row_y += 2

    def add_position_reports_slide(
        self,
        data: dict[str, Any],
        position_reports: list[dict[str, Any]],
    ) -> None:
        self.add_page()
        inner_x, inner_y, inner_w, inner_h = self._inner_bounds()
        cursor_y = self._slide_header(
            inner_x,
            inner_y,
            inner_w,
            eyebrow="PORT VALE F.C. · REPORTS BY POSITION",
            title="POSITION BREAKDOWN",
            subtitle=_format_filters(data),
        )

        rows = [row for row in (position_reports or []) if str(row.get("bucket_id")) != "unknown" or int(row.get("report_count") or 0)]
        max_count = max((int(row.get("report_count") or 0) for row in rows), default=1) or 1

        # Pitch-style grid of position cards
        layout = [
            (None, None, "9", None, None),
            ("11", None, "10", None, "7"),
            (None, "6", "8", None, None),
            ("3", "4/5", None, "4/5", "2"),
            (None, None, "1", None, None),
        ]
        by_id = {str(row.get("bucket_id")): row for row in rows}
        grid_top = cursor_y
        grid_h = (inner_y + inner_h - cursor_y) * 0.72
        row_h = grid_h / len(layout)
        col_w = inner_w / 5

        for r_index, row_ids in enumerate(layout):
            for c_index, bucket_id in enumerate(row_ids):
                if not bucket_id:
                    continue
                row = by_id.get(bucket_id) or {"label": bucket_id, "report_count": 0, "player_count": 0}
                card_x = inner_x + c_index * col_w + 2
                card_y = grid_top + r_index * row_h + 2
                card_w = col_w - 4
                card_h = row_h - 4
                self._draw_card(card_x, card_y, card_w, card_h)
                count = int(row.get("report_count") or 0)
                fill_ratio = count / max_count if max_count else 0
                if fill_ratio:
                    self.set_fill_color(20, 83, 45)
                    self.rect(card_x, card_y + card_h * (1 - fill_ratio), card_w, card_h * fill_ratio, style="F")
                self.set_xy(card_x, card_y + 3)
                self.set_font("Helvetica", "B", 11)
                self._text_rgb(GOLD)
                self.cell(card_w, 5, pdf_safe(f"{bucket_id} · {row.get('label') or ''}"), align="C")
                self.set_xy(card_x, card_y + card_h / 2 - 2)
                self.set_font("Helvetica", "B", 16)
                self._text_rgb(TEXT)
                self.cell(card_w, 7, pdf_safe(str(count)), align="C")
                self.set_xy(card_x, card_y + card_h - 8)
                self.set_font("Helvetica", "", 7.5)
                self._text_rgb(MUTED)
                self.cell(card_w, 4, pdf_safe(f"{row.get('player_count') or 0} players"), align="C")

        unknown = by_id.get("unknown")
        if unknown and int(unknown.get("report_count") or 0):
            self.set_xy(inner_x, inner_y + inner_h - 6)
            self.set_font("Helvetica", "", 8)
            self._text_rgb(MUTED)
            self.cell(
                inner_w,
                4,
                pdf_safe(
                    f"Also {unknown.get('report_count')} reports with no position tagged"
                    f" ({unknown.get('player_count')} players) — re-mark players from match view to tag roles."
                ),
                align="C",
            )

    def add_player_volume_slide(
        self,
        data: dict[str, Any],
        player_reports: list[dict[str, Any]],
        *,
        page_index: int = 0,
        page_size: int = 18,
    ) -> None:
        self.add_page()
        inner_x, inner_y, inner_w, inner_h = self._inner_bounds()
        total_pages = max(1, math.ceil(len(player_reports or []) / page_size))
        cursor_y = self._slide_header(
            inner_x,
            inner_y,
            inner_w,
            eyebrow="PORT VALE F.C. · REPORTS BY PLAYER",
            title="TOTAL REPORTS PER PLAYER",
            subtitle=pdf_safe(f"{_format_filters(data)} · Page {page_index + 1}/{total_pages}"),
        )

        name_w = inner_w * 0.30
        team_w = inner_w * 0.24
        pos_w = inner_w * 0.12
        count_w = inner_w * 0.10
        staff_w = inner_w * 0.24
        columns = [
            ("Player", name_w),
            ("Team", team_w),
            ("Pos", pos_w),
            ("Reports", count_w),
            ("Staff", staff_w),
        ]
        self._draw_card(inner_x, cursor_y, inner_w, inner_y + inner_h - cursor_y)
        row_y = self._table_header_dark(inner_x + 5, cursor_y + 6, columns)
        start = page_index * page_size
        page_rows = (player_reports or [])[start : start + page_size]
        if not page_rows:
            self.set_xy(inner_x + 5, row_y + 10)
            self.set_font("Helvetica", "", 10)
            self._text_rgb(MUTED)
            self.cell(inner_w - 10, 5, "No player reports in this period.")
            return
        for index, row in enumerate(page_rows):
            staff_label = row.get("staff")
            if isinstance(staff_label, list):
                staff_label = ", ".join(str(item) for item in staff_label if item)
            row_y = self._table_row_dark(
                inner_x + 5,
                row_y,
                [
                    (str(row.get("player_name") or ""), name_w),
                    (str(row.get("team") or ""), team_w),
                    (str(row.get("position_label") or "—"), pos_w),
                    (str(row.get("report_count") or 0), count_w),
                    (str(staff_label or "—"), staff_w),
                ],
                shaded=index % 2 == 1,
                bold_first=True,
            )


def build_scout_summary_one_pager_pdf(data: dict[str, Any]) -> bytes:
    totals = data.get("totals") or {}
    league_coverage = data.get("league_coverage") or []

    if not int(totals.get("assigned") or 0):
        raise ValueError("No scout assignments match these filters.")

    pdf = ScoutSummaryPDF()
    pdf.add_one_pager_slide(data, league_coverage)

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def build_scout_summary_two_pager_pdf(data: dict[str, Any]) -> bytes:
    totals = data.get("totals") or {}
    if not int(totals.get("assigned") or 0):
        raise ValueError("No scout assignments match these filters.")

    pdf = ScoutSummaryPDF()
    pdf.add_two_pager_ops_slide(
        data,
        data.get("league_coverage") or [],
        data.get("staff_teams") or [],
    )
    pdf.add_two_pager_focus_slide(
        data,
        data.get("player_reports") or [],
        data.get("recommendations") or [],
        data.get("least_seen_teams") or [],
    )

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def build_scout_summary_player_position_pdf(data: dict[str, Any]) -> bytes:
    totals = data.get("totals") or {}
    player_reports = data.get("player_reports") or []
    position_reports = data.get("position_reports") or []
    if not int(totals.get("assigned") or 0) and not player_reports:
        raise ValueError("No scout assignments or player reports match these filters.")

    pdf = ScoutSummaryPDF()
    pdf.add_position_reports_slide(data, position_reports)

    if player_reports:
        page_size = 18
        total_pages = math.ceil(len(player_reports) / page_size)
        for page_index in range(total_pages):
            pdf.add_player_volume_slide(
                data,
                player_reports,
                page_index=page_index,
                page_size=page_size,
            )
    else:
        pdf.add_player_volume_slide(data, [])

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def build_scout_summary_pdf(data: dict[str, Any]) -> bytes:
    totals = data.get("totals") or {}
    staff_rows = data.get("staff") or []
    staff_teams = data.get("staff_teams") or []
    league_coverage = data.get("league_coverage") or []
    league_team_exposure = data.get("league_team_exposure") or []
    player_reports = data.get("player_reports") or []
    position_reports = data.get("position_reports") or []

    if not int(totals.get("assigned") or 0):
        raise ValueError("No scout assignments match these filters.")

    pdf = ScoutSummaryPDF()
    pdf.add_overview_slide(data, staff_rows)
    pdf.add_staff_teams_slide(data, staff_teams)

    for index, league_row in enumerate(league_coverage):
        pdf.add_league_slide(data, league_row, staff_rows, league_index=index)

    if player_reports:
        page_size = 16
        total_pages = math.ceil(len(player_reports) / page_size)
        for page_index in range(total_pages):
            pdf.add_player_reports_slide(
                data,
                player_reports,
                page_index=page_index,
                page_size=page_size,
            )
    else:
        pdf.add_player_reports_slide(data, [])

    pdf.add_position_reports_slide(data, position_reports)

    for index, league_row in enumerate(league_team_exposure):
        pdf.add_team_exposure_slide(data, league_row, league_index=index)

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def scout_summary_export_filename(
    data: dict[str, Any],
    *,
    report_format: str = "full",
) -> str:
    period = str(data.get("period") or "all").replace(" ", "-")
    season = "-".join(str(item).replace("/", "-") for item in (data.get("seasons") or ["all"]))
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    kind_map = {
        "one_pager": "one-pager",
        "two_pager": "two-pager",
        "player_position": "player-position",
        "full": "full-review",
    }
    kind = kind_map.get(report_format, "full-review")
    return f"scout-summary-{season}-{period}-{kind}-{stamp}.pdf"
