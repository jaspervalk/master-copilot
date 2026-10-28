from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


_CHUNK_SIZE = 1024 * 1024


def file_checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def checksum_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_CHUNK_SIZE):
            digest.update(block)
    return digest.hexdigest()


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def move_to_trash(path: Path, *, corpus_root: Path, trash_root: Path) -> Path | None:
    """Verplaats een corpusbestand naar de prullenbak in plaats van het te wissen.

    Hard wissen zou onherstelbaar zijn, en laten staan zou het bij de volgende
    sync weer laten opduiken. De relatieve structuur blijft behouden, zodat je
    het bestand kunt terugzetten.
    """
    if not path.exists():
        return None
    try:
        relative = path.resolve().relative_to(corpus_root.resolve())
    except ValueError:
        relative = Path(path.name)

    destination = trash_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination = destination.with_name(
            f"{destination.stem}-{path.stat().st_mtime_ns}{destination.suffix}"
        )
    shutil.move(str(path), str(destination))
    return destination
