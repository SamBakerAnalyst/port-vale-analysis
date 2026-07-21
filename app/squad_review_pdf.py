from __future__ import annotations

from io import BytesIO
from typing import Any

from fpdf import FPDF

from app.label_utils import humanize_profile_name
from app.pdf_report import SLIDE_HEIGHT_MM, SLIDE_WIDTH_MM, pdf_safe
from app.squad_photos import fetch_photo_bytes, resolve_squad_photo_url

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


def _try_player_photo(name: str) -> BytesIO | None:
    url = resolve_squad_photo_url(name)
    if not url:
        return None
    try:
        image_bytes, _ = fetch_photo_bytes(url)
    except RuntimeError:
        return None
    return BytesIO(image_bytes)


class SquadComparisonPDF(FPDF):
    """16:9 Keynote / widescreen slide deck."""

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


def _add_comparison_page(pdf: SquadComparisonPDF, data: dict[str, Any]) -> None:
    players: list[dict[str, Any]] = data.get("players") or []
    profiles: list[dict[str, Any]] = data.get("profiles") or []
    if len(players) < 2:
        return

    pdf.add_page()
    frame_x, frame_y, frame_w, frame_h = pdf._frame_rect()
    inner_x = frame_x + INNER_PAD_MM
    inner_y = frame_y + INNER_PAD_MM
    inner_w = frame_w - (INNER_PAD_MM * 2)
    cursor_y = inner_y

    position_label = pdf_safe(str(data.get("positionLabel", "Player"))).upper()
    pdf.set_xy(inner_x, cursor_y)
    pdf.set_font("Helvetica", "B", 10)
    pdf._text_rgb((245, 197, 24))
    pdf.cell(inner_w, 5, pdf_safe("PORT VALE F.C."))

    cursor_y += 7
    pdf.set_xy(inner_x, cursor_y)
    pdf.set_font("Helvetica", "B", 20)
    pdf._text_rgb((245, 245, 245))
    pdf.cell(inner_w, 10, pdf_safe(f"{position_label} COMPARISON"))

    cursor_y += 12
    pdf.set_xy(inner_x, cursor_y)
    pdf.set_font("Helvetica", "", 11)
    pdf._text_rgb((156, 163, 175))
    season_line = pdf_safe(
        f"{data.get('competition', 'League One')} · {data.get('season', '')}"
    )
    pdf.cell(inner_w, 5, season_line)

    cursor_y += 11
    player_count = len(players)
    profile_count = max(len(profiles), 1)
    photo_h = {3: 46.0, 4: 38.0, 5: 32.0}.get(player_count, 40.0)
    photo_w = min(30.0, photo_h * 0.72)
    label_col_w = min(88.0 if player_count >= 5 else 96.0, inner_w * 0.24)
    player_col_w = (inner_w - label_col_w) / player_count

    for index, player in enumerate(players):
        color = PLAYER_COLORS[index % len(PLAYER_COLORS)]
        col_x = inner_x + label_col_w + (index * player_col_w)
        photo_x = col_x + ((player_col_w - photo_w) / 2)
        photo_y = cursor_y

        pdf._fill_rgb((31, 41, 55))
        pdf._draw_rgb((245, 197, 24))
        pdf.set_line_width(0.45)
        pdf.rect(photo_x, photo_y, photo_w, photo_h, style="DF")

        photo = _try_player_photo(str(player.get("name", "")))
        if photo is not None:
            try:
                pdf.image(photo, x=photo_x, y=photo_y, w=photo_w, h=photo_h)
            except Exception:
                photo = None
        if photo is None:
            pdf.set_xy(photo_x, photo_y + (photo_h / 2) - 5)
            pdf.set_font("Helvetica", "B", 14)
            pdf._text_rgb((107, 114, 128))
            pdf.cell(photo_w, 10, _player_initials(str(player.get("name", ""))), align="C")

        name_y = photo_y + photo_h + 3
        pdf.set_xy(col_x, name_y)
        pdf.set_font("Helvetica", "B", 10)
        pdf._text_rgb(color)
        pdf.multi_cell(player_col_w, 4.5, pdf_safe(str(player.get("name", ""))), align="C")

        pdf.set_xy(col_x, name_y + 10)
        pdf.set_font("Courier", "", 8.5)
        pdf._text_rgb((156, 163, 175))
        pdf.cell(player_col_w, 4, f"({int(player.get('minutes') or 0)}')", align="C")

    photo_block_h = photo_h + 18
    cursor_y += photo_block_h

    legend_h = 24.0
    note_h = 8.0
    grid_bottom = frame_y + frame_h - INNER_PAD_MM - legend_h - note_h - 2
    available_grid_h = max(24.0, grid_bottom - cursor_y)
    profile_count = max(len(profiles), 1)
    row_h = min(15.5, max(10.5, available_grid_h / profile_count))

    for profile in profiles:
        api_name = profile.get("apiName", "")
        label = profile.get("label") or humanize_profile_name(api_name)
        main_label, sub_label = _profile_label_parts(label)

        row_values = [
            player.get("profileScores", {}).get(api_name) for player in players
        ]
        numeric_values = [float(value) for value in row_values if value is not None]
        leader_value = max(numeric_values) if numeric_values else None

        pdf.set_xy(inner_x, cursor_y + 1)
        pdf.set_font("Helvetica", "B", 10)
        pdf._text_rgb((209, 213, 219))
        pdf.cell(label_col_w, 5, pdf_safe(main_label))

        if sub_label:
            pdf.set_xy(inner_x, cursor_y + 6)
            pdf.set_font("Helvetica", "", 8.5)
            pdf._text_rgb((107, 114, 128))
            pdf.cell(label_col_w, 4, pdf_safe(sub_label))
            label_offset = 6
        else:
            label_offset = 0

        for index, value in enumerate(row_values):
            color = PLAYER_COLORS[index % len(PLAYER_COLORS)]
            col_x = inner_x + label_col_w + (index * player_col_w)
            is_leader = (
                value is not None
                and leader_value is not None
                and float(value) == leader_value
            )
            if is_leader:
                fill = tuple(int(channel * 0.18 + 255 * 0.06) for channel in color)
                pdf._fill_rgb(fill)
                pdf.rect(col_x + 1.5, cursor_y + 1, player_col_w - 3, row_h - 2, style="F")

            pdf.set_xy(col_x, cursor_y + ((row_h - 8) / 2) + (label_offset * 0.15))
            pdf.set_font("Courier", "B", 13)
            pdf._text_rgb(color)
            display = "—" if value is None else f"{round(float(value))}%"
            pdf.cell(player_col_w, 8, display, align="C")

        cursor_y += row_h

    legend_y = frame_y + frame_h - INNER_PAD_MM - legend_h - note_h
    pdf._draw_rgb((42, 42, 42))
    pdf.set_line_width(0.25)
    pdf.line(inner_x, legend_y, inner_x + inner_w, legend_y)

    legend_y += 4
    legend_item_w = inner_w / player_count
    for index, player in enumerate(players):
        color = PLAYER_COLORS[index % len(PLAYER_COLORS)]
        item_x = inner_x + (index * legend_item_w)
        pdf._fill_rgb(color)
        pdf.rect(item_x + (legend_item_w / 2) - 10, legend_y, 20, 1.4, style="F")

        pdf.set_xy(item_x, legend_y + 3)
        pdf.set_font("Helvetica", "B", 9)
        pdf._text_rgb((245, 245, 245))
        pdf.cell(legend_item_w, 4, pdf_safe(str(player.get("name", ""))), align="C")

        pdf.set_xy(item_x, legend_y + 7.5)
        pdf.set_font("Helvetica", "", 7.5)
        pdf._text_rgb((156, 163, 175))
        meta = pdf_safe(
            f"{player.get('positionLabel', '')} · {player.get('club', 'FC Port Vale')}"
        )
        pdf.cell(legend_item_w, 4, meta, align="C")

    note = pdf_safe(str((data.get("scoring") or {}).get("note", "")))
    if note:
        pdf.set_xy(inner_x, frame_y + frame_h - INNER_PAD_MM - note_h + 1)
        pdf.set_font("Helvetica", "", 7)
        pdf._text_rgb((107, 114, 128))
        pdf.multi_cell(inner_w, 3.5, note, align="C")


def build_squad_review_pdf(pages: list[dict[str, Any]]) -> bytes:
    pdf = SquadComparisonPDF()
    rendered = False
    for page_data in pages:
        if len(page_data.get("players") or []) < 2:
            continue
        _add_comparison_page(pdf, page_data)
        rendered = True

    if not rendered:
        raise ValueError("No comparisons with at least two players were available for export.")

    output = pdf.output(dest="S")
    if isinstance(output, str):
        return output.encode("latin-1")
    return bytes(output)
