"""Application logging.

Until this existed the root logger sat at WARNING with no handlers, so every
`logger.info()` in the app was thrown away and warnings arrived through Python's
handler of last resort with no timestamp, level or logger name. That is why a
broken cache read as "the page is slow" for a fortnight — the code said what was
wrong, nobody could read it.

Set `LOG_LEVEL=DEBUG` in the environment to turn the volume up.
"""

from __future__ import annotations

import logging
import os

DEFAULT_LEVEL = "INFO"

# Third-party chatter that is INFO-level noise rather than signal.
NOISY_LOGGERS = ("urllib3", "httpx", "httpcore", "PIL", "matplotlib", "fontTools")

_MARKER = "_port_vale_hub_handler"


def configure_logging() -> str:
    """Send app logs to stderr with timestamps. Safe to call more than once."""
    level_name = (os.environ.get("LOG_LEVEL") or DEFAULT_LEVEL).strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level_name, level = DEFAULT_LEVEL, logging.INFO

    root = logging.getLogger()
    # Add our handler once, and leave uvicorn's own handlers alone — its loggers
    # set propagate=False, so nothing is logged twice.
    if not any(getattr(h, _MARKER, False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        setattr(handler, _MARKER, True)
        root.addHandler(handler)

    root.setLevel(level)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    return level_name
