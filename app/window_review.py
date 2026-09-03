"""Summer 26/27 transfer-window Present deck."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.paths import STANDALONE_DIR

# Before = first-team that finished 25/26 (Wikipedia squad table).
# January leavers excluded: Cole, Curtis, Plant, Johnson, Faal recalled.
# Ages as of window close 1 Sep 2026.
# DM = Craig, Byers. All other midfielders counted as MF (no AM/CM split).
WINDOW_CLOSE = "2026-09-01"
BEFORE_SIZE = 34
AFTER_SIZE = 26
BEFORE_AGE = 27.0
AFTER_AGE = 26.3
BEFORE_OWNED_AGE = 27.9
AFTER_OWNED_AGE = 27.1
LOAN_AGE = 21.8
LOANS_BEFORE = 5
LOANS_AFTER = 4
INS_COUNT = 12
OUTS_COUNT = 19
INS_AGE = 24.8
OUTS_AGE = 26.9


def register_window_review_routes(app: FastAPI) -> None:
    @app.get("/window-review", response_class=HTMLResponse)
    @app.get("/window-review/", response_class=HTMLResponse)
    def window_review_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "window-review.html"
        if not html_path.is_file():
            raise HTTPException(status_code=404, detail="Window review deck missing.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
