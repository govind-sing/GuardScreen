from io import BytesIO

from pypdf import PdfReader
from docx import Document

from app.core.exceptions import UnsupportedFileTypeError, ExtractionFailedError


def extract_text(file_bytes: bytes, file_type: str) -> str:
    """
    Pure extraction: bytes in, text out. No judgment about whether the
    result is "enough" text — that decision belongs to the caller.

    Raises UnsupportedFileTypeError or ExtractionFailedError on failure.
    Synchronous by design — the caller (worker task) is responsible for
    offloading this to a thread via asyncio.to_thread() if needed, since
    this module has no reason to know about the event loop.
    """
    if file_type == "pdf":
        return _extract_pdf(file_bytes)
    elif file_type == "docx":
        return _extract_docx(file_bytes)
    else:
        raise UnsupportedFileTypeError(f"Unsupported file_type: {file_type!r}")


def _extract_pdf(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(file_bytes))
    except Exception as e:
        raise ExtractionFailedError(f"Could not open PDF: {e}") from e

    if reader.is_encrypted:
        raise ExtractionFailedError("PDF is password-protected")

    try:
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as e:
        raise ExtractionFailedError(f"Failed extracting PDF text: {e}") from e

    return "\n".join(pages_text).strip()


def _extract_docx(file_bytes: bytes) -> str:
    try:
        doc = Document(BytesIO(file_bytes))
    except Exception as e:
        raise ExtractionFailedError(f"Could not open docx: {e}") from e

    paragraphs = [p.text for p in doc.paragraphs]
    return "\n".join(paragraphs).strip()