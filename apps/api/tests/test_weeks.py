from app.models import Chunk, Course, Document
from app.services.weeks import PageSpan, week_scope


BOOK = "sso/books/triola.pdf"


def _book(db, *, course="sso", path=BOOK, sections=(), status="indexed"):
    document = Document(
        title="Triola", source_path=path, checksum=path.ljust(64, "0"),
        course_slug=course, doc_kind="book", ingestion_status=status,
    )
    for index, (section, page) in enumerate(sections):
        document.chunks.append(Chunk(
            chunk_index=index, section_path=section, page_start=page, page_end=page,
            token_count=3, text=f"t{index}", normalized_text=f"t{index}", chunk_metadata={},
        ))
    db.add(document)
    db.commit()
    return document


def _course(db, plans, slug="sso"):
    db.merge(Course(slug=slug, name=slug.upper(), week_plans=plans))
    db.commit()


def test_a_section_prefix_matches_any_segment_of_the_path(db_session):
    """In course.yml schrijf je "9.2", niet het hele bladwijzerpad."""
    document = _book(db_session, sections=[
        ("9 Inferences from One Sample › 9.2 Two Proportions", 430),
        ("9 Inferences from One Sample › 9.2 Two Proportions", 431),
        ("9 Inferences from One Sample › 9.3 Two Means", 440),
        ("10 Correlation › 10.2 Correlation", 500),
    ])
    _course(db_session, {"2": {"reading": [{"document": BOOK, "sections": ["9.2"]}]}})

    scope = week_scope(db_session, "sso", 2)

    assert scope.spans == [PageSpan(document.id, 430, 431)]
    assert scope.unresolved == []


def test_several_sections_give_several_spans(db_session):
    document = _book(db_session, sections=[
        ("9 One Sample › 9.2 Proportions", 430),
        ("9 One Sample › 9.4 Variation", 450),
        ("13 Nonparametric › 13.2 Sign Test", 700),
    ])
    _course(db_session, {"2": {"reading": [{"document": BOOK, "sections": ["9.2", "13.2"]}]}})

    scope = week_scope(db_session, "sso", 2)

    assert sorted((s.page_start, s.page_end) for s in scope.spans) == [(430, 430), (700, 700)]
    assert all(s.document_id == document.id for s in scope.spans)


def test_explicit_pages_win_over_sections(db_session):
    """Voor een boek zonder bruikbare bladwijzers."""
    document = _book(db_session, sections=[("1 Iets", 5)])
    _course(db_session, {"1": {"reading": [{"document": BOOK, "pages": [10, 25], "sections": ["1"]}]}})

    scope = week_scope(db_session, "sso", 1)

    assert scope.spans == [PageSpan(document.id, 10, 25)]


def test_no_sections_and_no_pages_means_the_whole_document(db_session):
    document = _book(db_session, sections=[("a", 3), ("b", 9)])
    _course(db_session, {"1": {"reading": [{"document": BOOK}]}})

    assert week_scope(db_session, "sso", 1).spans == [PageSpan(document.id, 3, 9)]


def test_a_section_that_does_not_exist_is_reported(db_session):
    _book(db_session, sections=[("9 One Sample › 9.2 Proportions", 430)])
    _course(db_session, {"2": {"reading": [{"document": BOOK, "sections": ["99.9"]}]}})

    scope = week_scope(db_session, "sso", 2)

    assert scope.spans == []
    assert "99.9" in scope.unresolved[0]


def test_a_document_from_another_course_is_reported(db_session):
    _book(db_session, course="fundamentals-of-ds", path="fundamentals-of-ds/books/islr.pdf",
          sections=[("10 Deep Learning", 400)])
    _course(db_session, {"2": {"reading": [{"document": "fundamentals-of-ds/books/islr.pdf"}]}})

    scope = week_scope(db_session, "sso", 2)

    assert scope.spans == []
    assert "staat niet" in scope.unresolved[0]


def test_a_failed_document_does_not_count(db_session):
    _book(db_session, status="failed", sections=[("1 Iets", 3)])
    _course(db_session, {"1": {"reading": [{"document": BOOK}]}})

    assert week_scope(db_session, "sso", 1).is_empty


def test_topics_and_lectures_come_along(db_session):
    _book(db_session, sections=[("9 One Sample › 9.2 Proportions", 430)])
    _course(db_session, {"2": {
        "lectures": [3, 4], "topics": ["two-sample tests"],
        "reading": [{"document": BOOK, "sections": ["9.2"]}],
    }})

    scope = week_scope(db_session, "sso", 2)

    assert scope.lectures == [3, 4]
    assert scope.topics == ["two-sample tests"]


def test_a_week_without_a_plan_is_empty_not_an_error(db_session):
    _course(db_session, {})

    scope = week_scope(db_session, "sso", 7)

    assert scope.is_empty
    assert scope.unresolved == []


def test_an_unknown_course_is_empty(db_session):
    assert week_scope(db_session, "bestaat-niet", 1).is_empty
