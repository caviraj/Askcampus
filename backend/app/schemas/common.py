"""Shared response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    environment: str


class ErrorResponse(BaseModel):
    """Stable error body for every non-2xx response.

    `code` is a machine-readable constant; `detail` is the human-readable
    sentence shown to the user, worded per DESIGN_SYSTEM.md section 9 — it says
    what happened and what to do next, and does not apologize.
    """

    detail: str
    code: str
