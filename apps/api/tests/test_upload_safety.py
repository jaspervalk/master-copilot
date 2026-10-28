import pytest

from app.services.upload_safety import FileTooLargeError, InvalidFileError, validate_upload


def test_accepts_a_pdf():
    validate_upload(b"%PDF-1.7 inhoud", "boek.pdf")


def test_accepts_a_pptx():
    validate_upload(b"PK\x03\x04 zipinhoud", "slides.pptx")


def test_rejects_empty_content():
    with pytest.raises(ValueError):
        validate_upload(b"", "leeg.pdf")


def test_rejects_pdf_with_wrong_magic_bytes():
    with pytest.raises(InvalidFileError):
        validate_upload(b"<html>nee</html>", "nep.pdf")


def test_rejects_pptx_with_wrong_magic_bytes():
    with pytest.raises(InvalidFileError):
        validate_upload(b"geen zip", "nep.pptx")


def test_rejects_unsupported_extension():
    with pytest.raises(InvalidFileError):
        validate_upload(b"%PDF-1.7", "aantekening.txt")


def test_rejects_oversized_upload(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_size_bytes", 10)
    with pytest.raises(FileTooLargeError):
        validate_upload(b"%PDF-1.7 veel te lang", "groot.pdf")


def test_accepts_utf8_markdown():
    validate_upload("# Opgave\n\nTekst met é en ≥.".encode(), "opgave.md")


def test_rejects_binary_content_disguised_as_markdown():
    with pytest.raises(InvalidFileError):
        validate_upload(b"%PDF-1.7 \xff\xfe\x00 binair", "nep.md")


def test_accepts_a_notebook():
    notebook = b'{"cells": [{"cell_type": "markdown", "source": "# Lecture 8"}], "nbformat": 4}'

    validate_upload(notebook, "lecture8_linear-optimization.ipynb")


def test_rejects_a_notebook_that_is_not_json():
    with pytest.raises(InvalidFileError) as caught:
        validate_upload(b"%PDF-1.4 geen notebook", "les.ipynb")

    assert "notebook" in str(caught.value)


def test_rejects_json_that_is_not_a_notebook():
    """Geldige JSON zonder cellen is een databestand met de verkeerde naam."""
    with pytest.raises(InvalidFileError) as caught:
        validate_upload(b'{"rows": [1, 2, 3]}', "data.ipynb")

    assert "cellen" in str(caught.value)


def test_the_refusal_names_every_supported_format():
    """De lijst stond hier met de hand, en liep daardoor achter toen notebooks
    erbij kwamen: de ingest kon ze, de upload weigerde ze."""
    from app.services.path_metadata import SUPPORTED_SUFFIXES

    with pytest.raises(InvalidFileError) as caught:
        validate_upload(b"PK\x03\x04", "archief.zip")

    for suffix in SUPPORTED_SUFFIXES:
        assert suffix in str(caught.value)


def test_accepts_a_python_script():
    validate_upload(b"import pulp\nprint(1)\n", "lecture_8_knapsack.py")


def test_rejects_a_binary_file_named_like_a_script():
    with pytest.raises(InvalidFileError):
        validate_upload(b"\x00\x01\x02binair", "nep.py")
