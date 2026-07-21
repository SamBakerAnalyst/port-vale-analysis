from __future__ import annotations

from io import BytesIO
from typing import Any
from urllib.request import urlopen

from fpdf import FPDF

from app.label_utils import humanize_profile_name
from app.paths import PORT_VALE_BADGE
from app.pdf_report import SLIDE_HEIGHT_MM, SLIDE_WIDTH_MM, pdf_safe

PLAYER_COLORS: list[tuple[int, int, int]] = [
    (74, 144, 217),
    (229, 115, 168),
    (77, 182, 172),
    (245, 197, 24),
    (167, 139, 250),
]

FRAME_INSET_MM = 5.0
INNER_PAD_MM = 10.0


def _profile_label_parts(label: str) -> tuple[str, str | None]:
    text = str(label or "").strip()
    parts = [part.strip() for part in text.split(" - ") if part.strip()]
    if len(parts) > 1:
        main = parts[0].upper()
        sub = " - ".join(parts[1:])
        if sub.upper() == main:
            return main, None
        return main, sub
    return text.upper(), None


def _player_initials(name: str) -> str:
    parts = [part for part in str(name or "").split() if part]
    return "".join(part[0].upper() for part in parts[:2]) or "?"


def _photo_from_data_url(data_url: str | None) -> BytesIO | None:
    if not data_url or not str(data_url).startswith("data:image"):
        return None
    try:
        header, encoded = str(data_url).split(",", 1)
        import base64

        return BytesIO(base64.b64decode(encoded))
    except Exception:
        return None


def _average_color(value: float | None) -> tuple[int, int, int]:
    if value is None:
        return (239, 68, 68)
    if value >= 66:
        return (34, 197, 94)
    if value >= 33:
        return (245, 158, 11)
    return (239, 68, 68)


def _avg_scores(players: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> dict[str, float | None]:
    averages: dict[str, float | None] = {}
    for profile in profiles:
        api_name = profile.get("apiName", "")
        values = [
            float(player.get("profileScores", {}).get(api_name))
            for player in players
            if player.get("profileScores", {}).get(api_name) is not None
        ]
        averages[api_name] = (sum(values) / len(values)) if values else None
    return averages


class SquadBalancePDF(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format=(SLIDE_WIDTH_MM, SLIDE_HEIGHT_MM))
        self.set_auto_page_break(auto=False)
        self.set_margins(0, 0, 0)
        self.set_display_mode(zoom="fullpage", layout="single")

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
        self._fill_rgb((13, 13, 13))
        self._draw_rgb((245, 197, 24))
        self.set_line_width(0.9)
        self.rect(x, y, width, height, style="DF")
        return x, y, width, height


def _add_front_page(pdf: SquadBalancePDF, payload: dict[str, Any]) -> None:
    pdf.add_page()
    frame_x, frame_y, frame_w, frame_h = pdf._frame_rect()
    inner_x = frame_x + INNER_PAD_MM
    inner_y = frame_y + INNER_PAD_MM
    inner_w = frame_w - (INNER_PAD_MM * 2)

    pdf.set_xy(inner_x, inner_y + 18)
    pdf.set_font("Helvetica", "B", 12)
    pdf._text_rgb((245, 197, 24))
    pdf.cell(inner_w, 6, pdf_safe("PORT VALE F.C. · RECRUITMENT"), align="C")

    pdf.set_xy(inner_x, inner_y + 32)
    pdf.set_font("Helvetica", "B", 32)
    pdf._text_rgb((245, 245, 245))
    pdf.cell(inner_w, 14, pdf_safe(str(payload.get("title") or "Squad Balance")), align="C")

    pdf.set_xy(inner_x, inner_y + 50)
    pdf.set_font("Helvetica", "", 13)
    pdf._text_rgb((156, 163, 175))
    pdf.multi_cell(
        inner_w,
        6,
        pdf_safe(
            str(
                payload.get("subtitle")
                or "4-3-3 recruitment plan · last 2 seasons combined at role"
            )
        ),
        align="C",
    )

    positions = payload.get("positions") or []
    total_players = sum(len(pos.get("players") or []) for pos in positions)
    filled = sum(1 for pos in positions if pos.get("players"))

    # Summary card
    card_y = inner_y + 72
    pdf._fill_rgb((26, 26, 26))
    pdf._draw_rgb((42, 42, 42))
    pdf.set_line_width(0.4)
    pdf.rect(inner_x + 20, card_y, inner_w - 40, 42, style="DF")

    pdf.set_xy(inner_x + 28, card_y + 8)
    pdf.set_font("Helvetica", "B", 11)
    pdf._text_rgb((245, 197, 24))
    pdf.cell(inner_w - 56, 6, "SQUAD SUMMARY", align="C")

    pdf.set_xy(inner_x + 28, card_y + 20)
    pdf.set_font("Helvetica", "", 12)
    pdf._text_rgb((229, 231, 235))
    pdf.cell(
        inner_w - 56,
        6,
        pdf_safe(f"{total_players} players · {filled}/{len(positions)} position groups filled"),
        align="C",
    )

    pdf.set_xy(inner_x + 28, card_y + 30)
    pdf.set_font("Helvetica", "", 10)
    pdf._text_rgb((156, 163, 175))
    pdf.cell(
        inner_w - 56,
        5,
        "Profile percentiles · position-specific combined minutes · squad averages",
        align="C",
    )

    # Position roster lines
    list_y = card_y + 56
    pdf.set_xy(inner_x, list_y)
    pdf.set_font("Helvetica", "B", 10)
    pdf._text_rgb((245, 197, 24))
    pdf.cell(inner_w, 5, "BY POSITION")

    list_y += 8
    col_w = inner_w / 3
    for index, position in enumerate(positions):
        players = position.get("players") or []
        col = index % 3
        row = index // 3
        x = inner_x + (col * col_w)
        y = list_y + (row * 18)

        pdf.set_xy(x, y)
        pdf.set_font("Helvetica", "B", 10)
        pdf._text_rgb((245, 245, 245))
        pdf.cell(
            col_w - 4,
            5,
            pdf_safe(f"{position.get('shortLabel', '')}  {position.get('label', '')}"),
        )

        pdf.set_xy(x, y + 5)
        pdf.set_font("Helvetica", "", 8.5)
        pdf._text_rgb((156, 163, 175))
        if not players:
            pdf.cell(col_w - 4, 4, "— empty")
        else:
            names = ", ".join(str(player.get("name", "")) for player in players[:3])
            if len(players) > 3:
                names += f" +{len(players) - 3}"
            pdf.cell(col_w - 4, 4, pdf_safe(names))

    pdf.set_xy(inner_x, frame_y + frame_h - INNER_PAD_MM - 8)
    pdf.set_font("Helvetica", "", 8)
    pdf._text_rgb((107, 114, 128))
    pdf.cell(
        inner_w,
        4,
        "Impect profile scores · minutes are share of play time at the selected position",
        align="C",
    )


def _add_comparison_page(pdf: SquadBalancePDF, position: dict[str, Any]) -> None:
    players: list[dict[str, Any]] = position.get("players") or []
    profiles: list[dict[str, Any]] = position.get("profiles") or []
    if not players:
        return

    averages = _avg_scores(players, profiles)
    player_count = len(players)

    pdf.add_page()
    frame_x, frame_y, frame_w, frame_h = pdf._frame_rect()
    inner_x = frame_x + INNER_PAD_MM
    inner_y = frame_y + INNER_PAD_MM
    inner_w = frame_w - (INNER_PAD_MM * 2)
    cursor_y = inner_y

    pdf.set_xy(inner_x, cursor_y)
    pdf.set_font("Helvetica", "B", 10)
    pdf._text_rgb((245, 197, 24))
    pdf.cell(inner_w, 5, pdf_safe("SQUAD BALANCE"))

    cursor_y += 7
    pdf.set_xy(inner_x, cursor_y)
    pdf.set_font("Helvetica", "B", 20)
    pdf._text_rgb((245, 245, 245))
    title = f"{str(position.get('label', 'Player')).upper()} COMPARISON"
    pdf.cell(inner_w - 20, 10, pdf_safe(title))

    # Badge
    badge = pdf_safe(str(position.get("shortLabel", "")))
    pdf._draw_rgb((245, 197, 24))
    pdf.set_line_width(0.5)
    pdf.circle(inner_x + inner_w - 8, cursor_y + 5, 7, style="D")
    pdf.set_xy(inner_x + inner_w - 15, cursor_y + 2)
    pdf.set_font("Helvetica", "B", 10)
    pdf._text_rgb((245, 197, 24))
    pdf.cell(14, 6, badge, align="C")

    cursor_y += 12
    pdf.set_xy(inner_x, cursor_y)
    pdf.set_font("Helvetica", "", 10)
    pdf._text_rgb((156, 163, 175))
    pdf.cell(inner_w, 5, "4-3-3 recruitment plan · last 2 seasons combined at role")

    cursor_y += 10
    photo_h = {1: 42.0, 2: 40.0, 3: 36.0, 4: 32.0, 5: 28.0}.get(player_count, 32.0)
    photo_w = min(28.0, photo_h * 0.72)
    label_col_w = min(78.0, inner_w * 0.22)
    avg_col_w = min(28.0, inner_w * 0.12)
    player_col_w = (inner_w - label_col_w - avg_col_w) / max(player_count, 1)

    # Photos
    for index, player in enumerate(players):
        color = PLAYER_COLORS[index % len(PLAYER_COLORS)]
        col_x = inner_x + label_col_w + (index * player_col_w)
        photo_x = col_x + ((player_col_w - photo_w) / 2)

        pdf._fill_rgb((31, 41, 55))
        pdf._draw_rgb(color)
        pdf.set_line_width(0.45)
        pdf.rect(photo_x, cursor_y, photo_w, photo_h, style="DF")

        photo = _photo_from_data_url(player.get("photoDataUrl"))
        if photo is not None:
            try:
                pdf.image(photo, x=photo_x, y=cursor_y, w=photo_w, h=photo_h)
            except Exception:
                photo = None
        if photo is None:
            pdf.set_xy(photo_x, cursor_y + (photo_h / 2) - 4)
            pdf.set_font("Helvetica", "B", 12)
            pdf._text_rgb((107, 114, 128))
            pdf.cell(photo_w, 8, _player_initials(str(player.get("name", ""))), align="C")

        pdf.set_xy(col_x, cursor_y + photo_h + 2)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf._text_rgb(color)
        pdf.multi_cell(player_col_w, 3.8, pdf_safe(str(player.get("name", ""))), align="C")

        pdf.set_xy(col_x, cursor_y + photo_h + 11)
        pdf.set_font("Courier", "", 7.5)
        pdf._text_rgb((156, 163, 175))
        pdf.cell(player_col_w, 3.5, f"({int(player.get('minutes') or 0)}')", align="C")

    # Average header
    avg_x = inner_x + label_col_w + (player_count * player_col_w)
    pdf._fill_rgb((26, 26, 26))
    pdf._draw_rgb((245, 197, 24))
    avg_photo_w = min(18.0, photo_w * 0.7)
    avg_photo_x = avg_x + ((avg_col_w - avg_photo_w) / 2)
    try:
        badge_path = str(PORT_VALE_BADGE)
        pdf.image(badge_path, x=avg_photo_x, y=cursor_y + 4, w=avg_photo_w, h=avg_photo_w)
    except Exception:
        pdf.ellipse(avg_photo_x, cursor_y + 6, avg_photo_w, avg_photo_w, style="DF")

    pdf.set_xy(avg_x, cursor_y + photo_h + 2)
    pdf.set_font("Helvetica", "B", 8)
    pdf._text_rgb((245, 197, 24))
    pdf.cell(avg_col_w, 4, "Average", align="C")

    pdf.set_xy(avg_x, cursor_y + photo_h + 7)
    pdf.set_font("Helvetica", "", 7)
    pdf._text_rgb((156, 163, 175))
    pdf.cell(avg_col_w, 3.5, f"{player_count} players", align="C")

    cursor_y += photo_h + 16
    legend_h = 18.0
    note_h = 7.0
    grid_bottom = frame_y + frame_h - INNER_PAD_MM - legend_h - note_h
    available = max(20.0, grid_bottom - cursor_y)
    row_h = min(14.0, max(9.5, available / max(len(profiles), 1)))

    for profile in profiles:
        api_name = profile.get("apiName", "")
        label = profile.get("label") or humanize_profile_name(api_name)
        main_label, sub_label = _profile_label_parts(label)

        pdf.set_xy(inner_x, cursor_y + 1)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf._text_rgb((209, 213, 219))
        pdf.cell(label_col_w, 4.5, pdf_safe(main_label))
        if sub_label:
            pdf.set_xy(inner_x, cursor_y + 5.5)
            pdf.set_font("Helvetica", "", 7)
            pdf._text_rgb((107, 114, 128))
            pdf.cell(label_col_w, 3.5, pdf_safe(sub_label))

        for index, player in enumerate(players):
            color = PLAYER_COLORS[index % len(PLAYER_COLORS)]
            value = player.get("profileScores", {}).get(api_name)
            col_x = inner_x + label_col_w + (index * player_col_w)
            pdf._fill_rgb((24, 24, 24))
            pdf.rect(col_x + 1, cursor_y + 1, player_col_w - 2, row_h - 2, style="F")
            if value is not None:
                bar_w = max(1.0, (player_col_w - 2) * (float(value) / 100.0))
                fill = tuple(int(c * 0.45) for c in color)
                pdf._fill_rgb(fill)
                pdf.rect(col_x + 1, cursor_y + 1, bar_w, row_h - 2, style="F")
            pdf.set_xy(col_x, cursor_y + ((row_h - 6) / 2))
            pdf.set_font("Courier", "B", 11)
            pdf._text_rgb(color)
            display = "—" if value is None else f"{round(float(value))}%"
            pdf.cell(player_col_w, 6, display, align="C")

        avg_value = averages.get(api_name)
        avg_color = _average_color(avg_value)
        pdf._fill_rgb((24, 24, 24))
        pdf.rect(avg_x + 1, cursor_y + 1, avg_col_w - 2, row_h - 2, style="F")
        if avg_value is not None:
            bar_w = max(1.0, (avg_col_w - 2) * (float(avg_value) / 100.0))
            pdf._fill_rgb(tuple(int(c * 0.55) for c in avg_color))
            pdf.rect(avg_x + 1, cursor_y + 1, bar_w, row_h - 2, style="F")
        pdf.set_xy(avg_x, cursor_y + ((row_h - 6) / 2))
        pdf.set_font("Courier", "B", 11)
        pdf._text_rgb(avg_color)
        display = "—" if avg_value is None else f"{round(float(avg_value))}%"
        pdf.cell(avg_col_w, 6, display, align="C")

        cursor_y += row_h

    legend_y = frame_y + frame_h - INNER_PAD_MM - legend_h - note_h
    pdf._draw_rgb((42, 42, 42))
    pdf.set_line_width(0.25)
    pdf.line(inner_x, legend_y, inner_x + inner_w, legend_y)
    legend_y += 3
    legend_w = (inner_w - avg_col_w) / max(player_count, 1)
    for index, player in enumerate(players):
        color = PLAYER_COLORS[index % len(PLAYER_COLORS)]
        item_x = inner_x + (index * legend_w)
        pdf._fill_rgb(color)
        pdf.rect(item_x + (legend_w / 2) - 8, legend_y, 16, 1.2, style="F")
        pdf.set_xy(item_x, legend_y + 2.5)
        pdf.set_font("Helvetica", "B", 8)
        pdf._text_rgb((245, 245, 245))
        pdf.cell(legend_w, 3.5, pdf_safe(str(player.get("name", ""))), align="C")
        pdf.set_xy(item_x, legend_y + 6.5)
        pdf.set_font("Helvetica", "", 6.5)
        pdf._text_rgb((156, 163, 175))
        meta = f"{player.get('club', '')} · {int(player.get('minutes') or 0)}'"
        pdf.cell(legend_w, 3, pdf_safe(meta), align="C")

    pdf.set_xy(avg_x, legend_y + 2.5)
    pdf.set_font("Helvetica", "B", 8)
    pdf._text_rgb((245, 197, 24))
    pdf.cell(avg_col_w, 3.5, "Average", align="C")

    pdf.set_xy(inner_x, frame_y + frame_h - INNER_PAD_MM - note_h + 1)
    pdf.set_font("Helvetica", "", 6.5)
    pdf._text_rgb((107, 114, 128))
    pdf.cell(
        inner_w,
        3.5,
        "Minutes are position-attributed from the last two seasons with data at this role.",
        align="C",
    )


def build_squad_balance_pdf(payload: dict[str, Any]) -> bytes:
    pdf = SquadBalancePDF()
    _add_front_page(pdf, payload)

    rendered = False
    for position in payload.get("positions") or []:
        if position.get("players"):
            _add_comparison_page(pdf, position)
            rendered = True

    if not rendered:
        raise ValueError("Add at least one player before exporting a PDF.")

    output = pdf.output(dest="S")
    if isinstance(output, str):
        return output.encode("latin-1")
    return bytes(output)
