import pytest

from app.models import Chunk, Document
from app.schemas import QueryFilters
from app.services.hybrid_index import HybridIndex, reset_hybrid_index, rrf_fuse


@pytest.fixture(autouse=True)
def _clean_singleton():
    reset_hybrid_index()
    yield
    reset_hybrid_index()


_counter = iter(range(1000))


def _document(db, *, course, kind, week=None, status=None, texts) -> Document:
    unique = next(_counter)
    document = Document(
        title=f"{course}-{kind}",
        source_path=f"{course}/{kind}/{unique}.pdf",
        checksum=f"{unique:064d}",
        course_slug=course,
        doc_kind=kind,
        week=week,
        assignment_status=status,
        ingestion_status="indexed",
    )
    for index, text in enumerate(texts):
        document.chunks.append(
            Chunk(
                chunk_index=index,
                section_path=None,
                page_start=1,
                page_end=1,
                token_count=len(text.split()),
                text=text,
                normalized_text=text.lower(),
                chunk_metadata={},
            )
        )
    db.add(document)
    db.commit()
    return document


def test_rebuild_counts_indexed_chunks(db_session):
    _document(db_session, course="dl", kind="book", texts=["backpropagation chain rule", "convex loss"])
    index = HybridIndex()

    assert index.rebuild_from_sql(db_session) == 2
    assert index.ready


def test_pending_documents_are_excluded(db_session):
    document = _document(db_session, course="dl", kind="book", texts=["gradient descent"])
    document.ingestion_status = "pending"
    db_session.commit()

    assert HybridIndex().rebuild_from_sql(db_session) == 0


def test_search_ranks_the_matching_chunk_first(db_session):
    _document(db_session, course="dl", kind="book", texts=["elbo variational bound", "iets heel anders"])
    index = HybridIndex()
    index.rebuild_from_sql(db_session)

    results = index.search("elbo", limit=2)

    assert results
    chunk = db_session.get(Chunk, results[0][0])
    assert "elbo" in chunk.normalized_text


def test_course_filter_excludes_other_courses(db_session):
    _document(db_session, course="dl", kind="book", texts=["elbo variational bound"])
    _document(db_session, course="stats", kind="book", texts=["elbo variational bound"])
    index = HybridIndex()
    index.rebuild_from_sql(db_session)

    results = index.search("elbo", limit=10, filters=QueryFilters(course_slug="dl"))

    assert len(results) == 1
    assert db_session.get(Chunk, results[0][0]).document.course_slug == "dl"


def test_doc_kind_and_week_filters_apply(db_session):
    _document(db_session, course="dl", kind="slides", week=3, texts=["dropout regularisatie"])
    _document(db_session, course="dl", kind="book", week=None, texts=["dropout regularisatie"])
    index = HybridIndex()
    index.rebuild_from_sql(db_session)

    only_slides = index.search("dropout", limit=10, filters=QueryFilters(doc_kinds=["slides"]))
    only_week_3 = index.search("dropout", limit=10, filters=QueryFilters(week=3))

    assert len(only_slides) == 1
    assert len(only_week_3) == 1


def test_assignment_status_filter_applies(db_session):
    _document(db_session, course="dl", kind="assignment", week=1, status="open", texts=["bewijs convexiteit"])
    _document(db_session, course="dl", kind="assignment", week=2, status="submitted", texts=["bewijs convexiteit"])
    index = HybridIndex()
    index.rebuild_from_sql(db_session)

    results = index.search("convexiteit", limit=10, filters=QueryFilters(assignment_status="submitted"))

    assert len(results) == 1
    assert db_session.get(Chunk, results[0][0]).document.week == 2


def test_filter_that_matches_nothing_returns_empty(db_session):
    _document(db_session, course="dl", kind="book", texts=["elbo"])
    index = HybridIndex()
    index.rebuild_from_sql(db_session)

    assert index.search("elbo", limit=10, filters=QueryFilters(course_slug="onbekend")) == []


def test_rrf_fuse_rewards_agreement():
    fused = rrf_fuse([("a", 0.9), ("b", 0.8)], [("b", 4.0), ("c", 1.0)])

    assert fused[0][0] == "b"
    assert {chunk_id for chunk_id, _ in fused} == {"a", "b", "c"}


def test_solutions_of_open_weeks_are_excluded_from_sparse_results(db_session):
    _document(db_session, course="sso", kind="solution", week=4, texts=["ridge uitwerking week vier"])
    _document(db_session, course="sso", kind="solution", week=2, texts=["ridge uitwerking week twee"])
    _document(db_session, course="sso", kind="book", texts=["ridge regressie in het boek"])
    index = HybridIndex()
    index.rebuild_from_sql(db_session)

    hits = index.search("ridge", limit=10, hidden={"sso": {4}})
    hit_ids = {chunk_id for chunk_id, _ in hits}
    kinds_weeks = {(e.doc_kind, e.week) for e in index._entries if e.chunk_id in hit_ids}

    assert ("solution", 4) not in kinds_weeks
    assert ("solution", 2) in kinds_weeks
    assert ("book", None) in kinds_weeks


def test_hidden_weeks_of_another_course_do_not_apply(db_session):
    _document(db_session, course="fds", kind="solution", week=4, texts=["numpy uitwerking"])
    index = HybridIndex()
    index.rebuild_from_sql(db_session)

    assert index.search("numpy", limit=10, hidden={"sso": {4}})


def test_a_book_chapter_counts_towards_its_week_through_the_reading_plan(db_session):
    """Zonder leesplan bereikt een weekfilter alleen slides."""
    from app.services.weeks import PageSpan

    boek = _document(db_session, course="sso", kind="book", texts=["ridge regressie hoofdstuk"])
    _document(db_session, course="sso", kind="slides", week=2, texts=["ridge op de slides"])
    index = HybridIndex()
    index.rebuild_from_sql(db_session)
    entry = next(e for e in index._entries if e.doc_kind == "book")

    zonder = index.search("ridge", limit=10, filters=QueryFilters(course_slug="sso", week=2))
    met = index.search(
        "ridge", limit=10, filters=QueryFilters(course_slug="sso", week=2),
        week_spans=[PageSpan(boek.id, entry.page_start, entry.page_end)],
    )

    assert entry.chunk_id not in {chunk_id for chunk_id, _ in zonder}
    assert entry.chunk_id in {chunk_id for chunk_id, _ in met}


def test_a_chapter_outside_the_reading_plan_stays_out(db_session):
    from app.services.weeks import PageSpan

    boek = _document(db_session, course="sso", kind="book", texts=["deep learning hoofdstuk"])
    index = HybridIndex()
    index.rebuild_from_sql(db_session)

    hits = index.search(
        "deep learning", limit=10, filters=QueryFilters(course_slug="sso", week=2),
        week_spans=[PageSpan(boek.id, 9000, 9100)],
    )

    assert hits == []
