"""Document request and response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Mirrors the check constraint on documents.status in migration 0001.
DocumentStatus = Literal["uploaded", "processing", "ready", "failed"]

# Mirrors the check constraint on documents.category.
Category = Literal[
    "examinations",
    "admissions",
    "departments",
    "events",
    "academic_processes",
    "general",
]


def _blank_to_none(value: str | None) -> str | None:
    """Treat a form field submitted as "" as absent rather than as an empty value.

    Browsers send every field in a multipart form, including untouched optional
    ones, so without this an empty academic_year would be stored as "" and
    rendered as a blank in the admin UI.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class DocumentRead(BaseModel):
    """A document row as returned by the admin API.

    Every field comes from the database. Nothing here is computed or inferred by
    a model, which is what keeps citations honest.
    """

    model_config = ConfigDict(extra="ignore")

    id: UUID
    title: str
    category: Category
    academic_year: str | None = None
    department: str | None = None
    file_type: str
    original_filename: str | None = None
    file_size_bytes: int | None = None
    status: DocumentStatus
    is_active: bool
    error_message: str | None = None
    page_count: int | None = None
    chunk_count: int | None = None
    extracted_chars: int | None = None
    low_text_yield: bool = False
    text_preview: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentListResponse(BaseModel):
    """A page of documents.

    `total` is the unfiltered-by-range count from PostgREST, so the admin UI can
    show "showing 20 of 137" without a second request.
    """

    items: list[DocumentRead]
    total: int
    limit: int
    offset: int


class DocumentUploadMetadata(BaseModel):
    """The non-file fields of a multipart upload.

    Built by hand from the parsed form rather than by FastAPI's Form(), because
    the upload route parses the body itself -- see the comment in
    app/api/documents.py for why.
    """

    title: str = Field(min_length=1, max_length=300)
    category: Category
    academic_year: str | None = Field(default=None, max_length=32)
    department: str | None = Field(default=None, max_length=120)

    @field_validator("title")
    @classmethod
    def _title_must_have_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped

    @field_validator("academic_year", "department")
    @classmethod
    def _normalise_optional(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class DocumentUpdate(BaseModel):
    """A partial update. Only fields the caller sent are applied.

    Every field is optional, and the route uses exclude_unset so that omitting a
    field leaves it alone while explicitly sending null clears it.
    """

    title: str | None = Field(default=None, min_length=1, max_length=300)
    category: Category | None = None
    academic_year: str | None = Field(default=None, max_length=32)
    department: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None

    @field_validator("title")
    @classmethod
    def _title_must_have_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped
