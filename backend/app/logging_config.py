"""Logging setup, shared by the app, the test suite and (later) eval/run_eval.py."""

from __future__ import annotations

import logging

from app.config import Settings

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(level=settings.log_level.upper(), format=_FORMAT)

    # uvicorn installs its own handlers; align them with ours so levels are not
    # silently overridden.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(settings.log_level.upper())
