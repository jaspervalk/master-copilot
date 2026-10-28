from app.schemas import QueryFilters
from app.services.qdrant_index import build_filter


def test_no_filters_returns_none():
    assert build_filter(None) is None
    assert build_filter(QueryFilters()) is None


def test_course_and_week_become_match_values():
    query_filter = build_filter(QueryFilters(course_slug="deep-learning", week=3))

    values = {condition.key: condition.match.value for condition in query_filter.must}
    assert values == {"course_slug": "deep-learning", "week": 3}


def test_doc_kinds_become_a_match_any():
    query_filter = build_filter(QueryFilters(doc_kinds=["book", "slides"]))

    condition = query_filter.must[0]
    assert condition.key == "doc_kind"
    assert set(condition.match.any) == {"book", "slides"}


def test_empty_doc_kinds_list_is_ignored():
    assert build_filter(QueryFilters(doc_kinds=[])) is None


def test_assignment_status_is_included():
    query_filter = build_filter(QueryFilters(assignment_status="open"))

    assert query_filter.must[0].key == "assignment_status"
    assert query_filter.must[0].match.value == "open"


def test_hidden_weeks_become_must_not_on_kind_and_week():
    query_filter = build_filter(QueryFilters(course_slug="sso"), hidden={"sso": {4, 6}})

    assert [c.key for c in query_filter.must] == ["course_slug"]
    must_not = query_filter.must_not
    # Eén uitsluiting per (vak, week): doc_kind in {solution, submission} én die week én dat vak.
    assert len(must_not) == 2
    keys = sorted(tuple(sorted(cond.key for cond in item.must)) for item in must_not)
    assert keys == [("course_slug", "doc_kind", "week"), ("course_slug", "doc_kind", "week")]


def test_hidden_weeks_apply_without_a_course_filter():
    query_filter = build_filter(None, hidden={"sso": {4}})

    assert query_filter is not None
    assert query_filter.must == []
    assert len(query_filter.must_not) == 1


def test_no_hidden_weeks_adds_no_must_not():
    assert build_filter(QueryFilters(course_slug="sso"), hidden={}).must_not is None


def _span(document_id="doc-1", page_start=430, page_end=440):
    from app.services.weeks import PageSpan

    return PageSpan(document_id=document_id, page_start=page_start, page_end=page_end)


def test_without_a_reading_plan_week_stays_a_hard_filter():
    query_filter = build_filter(QueryFilters(course_slug="sso", week=2))

    keys = {condition.key for condition in query_filter.must}
    assert keys == {"course_slug", "week"}
    assert query_filter.should is None


def test_a_reading_plan_turns_week_into_an_or():
    """Een boek heeft geen week; het hoort erbij via zijn bladzijden."""
    query_filter = build_filter(QueryFilters(course_slug="sso", week=2), week_spans=[_span()])

    assert {condition.key for condition in query_filter.must} == {"course_slug"}
    assert len(query_filter.should) == 2
    eigen_week, uit_boek = query_filter.should
    assert eigen_week.must[0].key == "week"
    assert {condition.key for condition in uit_boek.must} == {"document_id", "page_end", "page_start"}


def test_every_span_becomes_its_own_alternative():
    query_filter = build_filter(
        QueryFilters(course_slug="sso", week=2),
        week_spans=[_span(page_start=430, page_end=440), _span(page_start=700, page_end=710)],
    )

    assert len(query_filter.should) == 3  # eigen week + twee leesstukken
