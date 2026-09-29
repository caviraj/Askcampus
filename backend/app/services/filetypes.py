"""Recognising and describing the file types we accept.

One module owns this because two callers need to agree: the upload route decides
whether bytes are acceptable, and Storage has to be told a content type that the
bucket's allowed_mime_types permits (migration 0003). If those drifted, every
upload of that type would fail with an opaque "mime type is not supported".

Magic bytes are checked by hand rather than with python-magic, which needs a
system libmagic shared library that does not exist on Windows.
"""

from __future__ import annotations

import codecs
import io
import zipfile

# Storage content types, keyed by extension. Must match the bucket's
# allowed_mime_types in supabase/migrations/0003_documents_bucket.sql.
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
}

_ZIP_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF-"
# The PDF specification permits leading bytes before the header, so the signature
# is searched rather than required at offset 0. Requiring offset 0 rejects
# otherwise valid files that some generators emit.
_PDF_SEARCH_WINDOW = 1024
# A DOCX is a ZIP: this entry point and the main document part are what make it
# Word rather than Excel, PowerPoint, or a zip bomb.
_DOCX_REQUIRED_ENTRIES = frozenset({"[Content_Types].xml", "word/document.xml"})

# Exported because the text extractor needs the same rule, and the two must not
# drift: UTF-16 is the one encoding that cannot be recognised from the bytes
# alone, only from a byte order mark.
UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)


class UnsupportedFileError(Exception):
    """The bytes are not the type their extension claims."""


def normalise_extension(filename: str) -> str:
    """The lower-case extension of a filename, without the dot."""
    _, _, extension = filename.rpartition(".")
    return extension.strip().lower()


def content_type_for(file_type: str) -> str:
    """The content type to store `file_type` as.

    Always passed explicitly to Storage: its default is text/plain, so omitting it
    stores a PDF as plain text and nothing about the result looks wrong.
    """
    try:
        return CONTENT_TYPES[file_type.strip().lstrip(".").lower()]
    except KeyError as exc:
        raise UnsupportedFileError(f"No content type is known for '{file_type}'.") from exc


def validate_file_bytes(
    data: bytes,
    file_type: str,
    *,
    max_uncompressed_bytes: int,
) -> None:
    """Raise UnsupportedFileError unless `data` really is `file_type`.

    The extension has already been checked by the caller; this is the check that
    a renamed file cannot pass.
    """
    normalised = file_type.strip().lstrip(".").lower()

    if normalised == "pdf":
        if _PDF_MAGIC not in data[:_PDF_SEARCH_WINDOW]:
            raise UnsupportedFileError("The file does not look like a PDF.")
        return

    if normalised == "docx":
        _validate_docx(data, max_uncompressed_bytes=max_uncompressed_bytes)
        return

    if normalised == "txt":
        _validate_txt(data)
        return

    raise UnsupportedFileError(f"'{file_type}' files are not accepted.")


def _validate_docx(data: bytes, *, max_uncompressed_bytes: int) -> None:
    """A .docx is a ZIP, so ZIP magic alone proves nothing.

    An .xlsx, a .pptx and a zip bomb all start with PK\\x03\\x04. Only the presence
    of Word's entry points distinguishes it.
    """
    if not data.startswith(_ZIP_MAGIC):
        raise UnsupportedFileError("The file does not look like a Word document.")

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if not _DOCX_REQUIRED_ENTRIES <= names:
                raise UnsupportedFileError("The file is a ZIP archive but not a Word document.")
            # file_size is the declared uncompressed size from the central
            # directory. A 20 MB archive can declare gigabytes, so this is checked
            # before python-docx is allowed to read it.
            total = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise UnsupportedFileError("The file could not be read as a Word document.") from exc

    if total > max_uncompressed_bytes:
        raise UnsupportedFileError(
            f"The document would expand to {total // (1024 * 1024)} MB, "
            f"above the limit of {max_uncompressed_bytes // (1024 * 1024)} MB."
        )


def _validate_txt(data: bytes) -> None:
    """Text has no magic number, and pretending otherwise is the trap.

    The honest check is that the bytes are plausibly text: no NUL byte, which
    every binary format contains early, and decodable as text.

    UTF-16 is checked for a BOM first, because it cannot be detected any other
    way and because the NUL rule below would reject it: ASCII text in UTF-16 is
    mostly NUL bytes by construction. Without this branch a legitimate
    Notepad-saved .txt file is refused as binary.
    """
    if not data:
        raise UnsupportedFileError("The file is empty.")

    sample = data[:8192]

    if data.startswith(UTF16_BOMS):
        # final=False so a character straddling the 8 KB boundary is treated as
        # truncated rather than as an encoding error.
        try:
            codecs.getincrementaldecoder("utf-16")().decode(sample, final=False)
        except UnicodeDecodeError as exc:
            raise UnsupportedFileError("The file is not valid UTF-16 text.") from exc
        return

    if b"\x00" in sample:
        raise UnsupportedFileError("The file contains binary data, not text.")

    for encoding in ("utf-8-sig", "cp1252"):
        # final=False for the same boundary reason as above.
        try:
            codecs.getincrementaldecoder(encoding)().decode(sample, final=False)
        except UnicodeDecodeError:
            continue
        return

    raise UnsupportedFileError("The file could not be read as text.")
