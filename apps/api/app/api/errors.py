from __future__ import annotations

from fastapi import HTTPException

from app.services.canvas.client import CanvasError, CanvasNotConfigured
from app.services.coach import CoachError
from app.services.documents import DuplicateDocumentError
from app.services.parsing import EmptyDocumentError, UnsupportedFileTypeError
from app.services.path_metadata import CorpusPathError
from app.services.upload_safety import FileTooLargeError, InvalidFileError

__all__ = ["DuplicateDocumentError", "to_http_exception"]


def to_http_exception(exc: Exception) -> HTTPException:
    """Vertaal domeinfouten naar statuscodes, met de oorspronkelijke tekst."""
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, FileTooLargeError):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, DuplicateDocumentError):
        return HTTPException(status_code=409, detail=str(exc))
    # Geen configuratie is een vraag aan de gebruiker (400); een antwoord van
    # Canvas dat niet deugt is een probleem verderop (502).
    if isinstance(exc, CanvasNotConfigured):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, CanvasError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(
        exc, (InvalidFileError, CorpusPathError, UnsupportedFileTypeError, EmptyDocumentError, CoachError)
    ):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))
