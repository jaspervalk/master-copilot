from pathlib import Path

import pytest

from app.services.path_metadata import (
    CorpusPath,
    CorpusPathError,
    build_corpus_path,
    parse_corpus_path,
)


def test_parses_book_without_week(tmp_path: Path):
    target = tmp_path / "statistical-learning" / "books" / "bishop-prml.pdf"
    target.parent.mkdir(parents=True)
    target.touch()

    result = parse_corpus_path(target, tmp_path)

    assert result == CorpusPath(
        course_slug="statistical-learning",
        doc_kind="book",
        week=None,
        relative_path="statistical-learning/books/bishop-prml.pdf",
        absolute_path=target.resolve(),
    )


def test_parses_week_from_folder(tmp_path: Path):
    target = tmp_path / "deep-learning" / "slides" / "week-03" / "cnn.pdf"
    target.parent.mkdir(parents=True)
    target.touch()

    result = parse_corpus_path(target, tmp_path)

    assert result.doc_kind == "slides"
    assert result.week == 3


def test_parses_week_from_filename_when_no_week_folder(tmp_path: Path):
    target = tmp_path / "deep-learning" / "assignments" / "week-07-backprop.pdf"
    target.parent.mkdir(parents=True)
    target.touch()

    assert parse_corpus_path(target, tmp_path).week == 7


def test_all_folder_names_map_to_a_kind(tmp_path: Path):
    expected = {
        "books": "book",
        "papers": "paper",
        "slides": "slides",
        "assignments": "assignment",
        "submissions": "submission",
        "solutions": "solution",
        "notes": "note",
    }
    for folder, kind in expected.items():
        target = tmp_path / "vak" / folder / "x.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        assert parse_corpus_path(target, tmp_path).doc_kind == kind


def test_unknown_folder_is_rejected(tmp_path: Path):
    target = tmp_path / "vak" / "random" / "x.pdf"
    target.parent.mkdir(parents=True)
    target.touch()

    with pytest.raises(CorpusPathError) as excinfo:
        parse_corpus_path(target, tmp_path)
    assert "random" in str(excinfo.value)


def test_file_directly_under_course_is_rejected(tmp_path: Path):
    target = tmp_path / "vak" / "x.pdf"
    target.parent.mkdir(parents=True)
    target.touch()

    with pytest.raises(CorpusPathError):
        parse_corpus_path(target, tmp_path)


def test_extra_nesting_is_rejected(tmp_path: Path):
    target = tmp_path / "vak" / "books" / "deel-1" / "hoofdstuk" / "x.pdf"
    target.parent.mkdir(parents=True)
    target.touch()

    with pytest.raises(CorpusPathError):
        parse_corpus_path(target, tmp_path)


def test_invalid_course_slug_is_rejected(tmp_path: Path):
    target = tmp_path / "Statistical Learning" / "books" / "x.pdf"
    target.parent.mkdir(parents=True)
    target.touch()

    with pytest.raises(CorpusPathError):
        parse_corpus_path(target, tmp_path)


def test_build_corpus_path_roundtrips(tmp_path: Path):
    built = build_corpus_path(
        corpus_root=tmp_path,
        course_slug="deep-learning",
        doc_kind="assignment",
        week=3,
        filename="Week 3 — opgaven.pdf",
    )
    assert built == (tmp_path / "deep-learning" / "assignments" / "week-03" / "Week-3-opgaven.pdf").resolve()

    built.parent.mkdir(parents=True)
    built.touch()
    parsed = parse_corpus_path(built, tmp_path)
    assert (parsed.course_slug, parsed.doc_kind, parsed.week) == ("deep-learning", "assignment", 3)


def test_build_rejects_unknown_kind(tmp_path: Path):
    with pytest.raises(CorpusPathError):
        build_corpus_path(
            corpus_root=tmp_path,
            course_slug="vak",
            doc_kind="verzonnen",
            week=None,
            filename="x.pdf",
        )


def test_exercises_folder_is_the_exercise_kind(tmp_path):
    from app.services.path_metadata import parse_corpus_path

    corpus = tmp_path / "corpus"
    target = corpus / "sso" / "exercises" / "week-02" / "triola-6-2.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-")

    parsed = parse_corpus_path(target, corpus)

    assert parsed.doc_kind == "exercise"
    assert parsed.week == 2


def test_build_corpus_path_knows_exercises(tmp_path):
    from app.services.path_metadata import build_corpus_path

    path = build_corpus_path(
        corpus_root=tmp_path, course_slug="sso", doc_kind="exercise", week=2, filename="x.pdf"
    )

    assert path.relative_to(tmp_path.resolve()).as_posix() == "sso/exercises/week-02/x.pdf"


def test_an_exam_has_its_own_kind_and_no_week(tmp_path: Path):
    """Een proeftentamen is geen opdracht en geen oefening: het is de beste
    aanwijzing voor wat het echte tentamen vraagt, en valt buiten de
    spoilerfilter."""
    root = tmp_path / "corpus"
    target = root / "fundamentals-of-ds" / "exams" / "MockExam-FDS-DraftSolution.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-1.4")

    parsed = parse_corpus_path(target, root)

    assert parsed.doc_kind == "exam"
    assert parsed.week is None


def test_markdown_is_a_corpus_file(tmp_path: Path):
    target = tmp_path / "fundamentals-of-ds" / "exercises" / "week-02" / "quiz-01.md"

    result = parse_corpus_path(target, tmp_path)

    assert result.doc_kind == "exercise"
    assert result.week == 2
    assert build_corpus_path(
        corpus_root=tmp_path, course_slug="fundamentals-of-ds", doc_kind="assignment", week=4, filename="Assignment 1.md"
    ).name == "Assignment-1.md"
