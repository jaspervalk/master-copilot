from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.services.path_metadata import SUPPORTED_SUFFIXES


MAGIC_BYTES: dict[str, bytes] = {
    ".pdf": b"%PDF-",
    # Een .pptx is een zip-archief.
    ".pptx": b"PK\x03\x04",
}


class InvalidFileError(ValueError):
    """De inhoud past niet bij de extensie, of de extensie wordt niet ondersteund."""


class FileTooLargeError(Exception):
    def __init__(self, size: int, limit: int) -> None:
        super().__init__(f"Bestand van {size} bytes overschrijdt de limiet van {limit} bytes")
        self.size = size
        self.limit = limit


def _text(content: bytes, label: str) -> str:
    """Tekst heeft geen magic bytes; wat wel moet: geldige UTF-8, zonder
    nulbytes (dan is het een binair bestand met een verkeerde naam)."""
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidFileError(f"Een {label} moet UTF-8-tekst zijn") from exc
    if "\x00" in decoded:
        raise InvalidFileError(f"Een {label} moet tekst zijn, geen binaire inhoud")
    return decoded


def validate_upload(content: bytes, filename: str) -> None:
    """Controleer grootte en magic bytes vóór er iets naar schijf gaat."""
    if not content:
        raise ValueError("Het geüploade bestand is leeg")
    if len(content) > settings.max_upload_size_bytes:
        raise FileTooLargeError(size=len(content), limit=settings.max_upload_size_bytes)

    suffix = Path(filename).suffix.lower()
    if suffix == ".md":
        _text(content, ".md-bestand")
        return
    if suffix == ".py":
        _text(content, "Python-script")
        return
    if suffix == ".ipynb":
        # Een notebook is JSON met een lijst cellen. Alleen "geldige JSON" is
        # niet genoeg: dan gaat een databestand met de verkeerde naam er ook door.
        try:
            notebook = json.loads(_text(content, "notebook"))
        except json.JSONDecodeError as exc:
            raise InvalidFileError(f"Dit is geen leesbaar notebook: {exc.msg}") from None
        if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
            raise InvalidFileError("Dit notebook heeft geen cellen; is het wel een .ipynb?")
        return
    magic = MAGIC_BYTES.get(suffix)
    if magic is None:
        # De lijst komt uit path_metadata, niet met de hand: toen hij hier nog
        # letterlijk stond, weigerde de upload notebooks die de ingest al kon.
        raise InvalidFileError(
            f"Extensie '{suffix}' wordt niet ondersteund; gebruik {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    if not content.startswith(magic):
        raise InvalidFileError(f"De inhoud begint niet met de verwachte kop voor {suffix}")
