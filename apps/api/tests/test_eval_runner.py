from app.eval.cases import EvalCase, ExpectedHit
from app.eval.metrics import Hit
from app.eval.runner import run_cases, unknown_source_paths


def _case(id="c", question="vraag", expected=None, **kwargs):
    return EvalCase(
        id=id,
        course_slug="sso",
        question=question,
        expected=expected if expected is not None else [ExpectedHit(source_path="a.pdf", pages=(10, 12))],
        **kwargs,
    )


def _search_returning(*hits):
    calls = []

    def search(question, course_slug, top_k):
        calls.append((question, course_slug, top_k))
        return list(hits)[:top_k]

    search.calls = calls
    return search


def test_rank_comes_from_the_first_overlapping_hit():
    search = _search_returning(Hit("a.pdf", 1, 2, 0.9), Hit("a.pdf", 11, 11, 0.8))

    report = run_cases([_case()], search, top_k=8, mode="hybrid", abstain_threshold=0.2)

    assert report.results[0].rank == 2
    assert report.results[0].error is None


def test_search_receives_the_course_filter_and_top_k():
    search = _search_returning()

    run_cases([_case()], search, top_k=5, mode="hybrid", abstain_threshold=0.2)

    assert search.calls == [("vraag", "sso", 5)]


def test_unverified_cases_are_skipped_and_counted():
    search = _search_returning(Hit("a.pdf", 10, 10, 0.9))

    report = run_cases(
        [_case(id="ok"), _case(id="seed", unverified=True)],
        search, top_k=8, mode="hybrid", abstain_threshold=0.2,
    )

    assert [r.case_id for r in report.results] == ["ok"]
    assert report.skipped_unverified == 1


def test_a_failing_search_becomes_an_error_and_the_run_continues():
    def search(question, course_slug, top_k):
        if question == "kapot":
            raise RuntimeError("netwerk weg")
        return [Hit("a.pdf", 10, 10, 0.9)]

    report = run_cases(
        [_case(id="a", question="kapot"), _case(id="b", question="goed")],
        search, top_k=8, mode="hybrid", abstain_threshold=0.2,
    )

    assert report.results[0].error == "netwerk weg"
    assert report.results[0].rank is None
    assert report.results[1].rank == 1


def test_abstain_case_is_ok_when_no_hit_reaches_the_threshold():
    """Zonder antwoordmodel is 'niets relevants' = geen score boven de drempel."""
    search = _search_returning(Hit("a.pdf", 1, 1, 0.15), Hit("a.pdf", 2, 2, 0.10))
    case = _case(id="uit", expected=[], expect_abstain=True)

    report = run_cases([case], search, top_k=8, mode="hybrid", abstain_threshold=0.2)

    assert report.results[0].abstain_ok is True
    assert report.results[0].rank is None


def test_abstain_case_fails_when_a_hit_is_confident():
    search = _search_returning(Hit("a.pdf", 1, 1, 0.55))
    case = _case(id="uit", expected=[], expect_abstain=True)

    report = run_cases([case], search, top_k=8, mode="hybrid", abstain_threshold=0.2)

    assert report.results[0].abstain_ok is False


def test_normal_cases_have_no_abstain_verdict():
    report = run_cases([_case()], _search_returning(), top_k=8, mode="hybrid", abstain_threshold=0.2)

    assert report.results[0].abstain_ok is None


def test_unknown_source_paths_are_listed_once():
    cases = [
        _case(id="a", expected=[ExpectedHit(source_path="weg.pdf", pages=(1, 1))]),
        _case(id="b", expected=[ExpectedHit(source_path="weg.pdf", pages=(2, 2))]),
        _case(id="c", expected=[ExpectedHit(source_path="er.pdf", pages=(1, 1))]),
    ]

    assert unknown_source_paths(cases, known={"er.pdf"}) == ["weg.pdf"]


def test_report_records_mode_and_top_k():
    report = run_cases([], _search_returning(), top_k=3, mode="dense", abstain_threshold=0.2)

    assert report.mode == "dense"
    assert report.top_k == 3
    assert report.created_at


def test_answer_fn_fills_outcome_and_mentions():
    from app.eval.answers import AnswerOutcome

    case = _case(id="m", must_mention=["kettingregel"])
    outcome = AnswerOutcome(
        text="Backprop past de kettingregel toe.", abstained=False, confidence="high", latency_ms=5
    )

    report = run_cases(
        [case], _search_returning(Hit("a.pdf", 10, 10, 0.9)),
        top_k=8, mode="hybrid", abstain_threshold=0.2,
        answer=lambda question, course, top_k, coach: outcome,
    )

    assert report.results[0].answer == outcome
    assert report.results[0].mentions_ok is True


def test_with_an_answer_fn_abstain_uses_the_model_verdict():
    from app.eval.answers import AnswerOutcome

    case = _case(id="uit", expected=[], expect_abstain=True)
    confident_search = _search_returning(Hit("a.pdf", 1, 1, 0.9))

    def abstaining(question, course, top_k, coach):
        return AnswerOutcome(
            text="Dit staat niet in je materiaal.", abstained=True, confidence="low", latency_ms=1
        )

    report = run_cases(
        [case], confident_search, top_k=8, mode="hybrid", abstain_threshold=0.2, answer=abstaining
    )

    assert report.results[0].abstain_ok is True


def test_a_failing_answer_fn_is_recorded_without_losing_retrieval():
    def broken(question, course, top_k, coach):
        raise RuntimeError("model down")

    report = run_cases(
        [_case()], _search_returning(Hit("a.pdf", 10, 10, 0.9)),
        top_k=8, mode="hybrid", abstain_threshold=0.2, answer=broken,
    )

    assert report.results[0].rank == 1
    assert report.results[0].error == "antwoord: model down"


def test_leaked_terms_are_reported():
    from app.eval.answers import AnswerOutcome

    case = _case(id="lek", must_not_mention=["2.92", "np(1-p)"])
    outcome = AnswerOutcome(text="Het antwoord is 2.92.", abstained=False, confidence="high", latency_ms=1)

    report = run_cases(
        [case], _search_returning(Hit("a.pdf", 10, 10, 0.9)),
        top_k=8, mode="hybrid", abstain_threshold=0.2,
        answer=lambda question, course, top_k, coach: outcome,
    )

    assert report.results[0].leaks == ["2.92"]
    assert report.results[0].mentions_ok is None


def test_coach_case_resolves_the_document_and_passes_it_to_the_answer_fn():
    from app.eval.answers import AnswerOutcome
    from app.eval.cases import CoachCase

    seen = {}

    def answer(question, course, top_k, coach):
        seen["coach"] = coach
        return AnswerOutcome(text="hint", abstained=False, confidence="high", latency_ms=1)

    case = _case(id="c", coach=CoachCase(document="sso/assignments/week-04/a1.pdf", reveal=True))

    run_cases(
        [case], _search_returning(Hit("a.pdf", 10, 10, 0.9)),
        top_k=8, mode="hybrid", abstain_threshold=0.2, answer=answer,
        document_ids={"sso/assignments/week-04/a1.pdf": "doc-1"},
    )

    assert seen["coach"] == {"document_id": "doc-1", "reveal": True}


def test_coach_case_with_unknown_document_is_an_error():
    from app.eval.cases import CoachCase

    case = _case(id="c", coach=CoachCase(document="weg.pdf"))

    report = run_cases(
        [case], _search_returning(), top_k=8, mode="hybrid", abstain_threshold=0.2,
        answer=lambda q, c, k, coach: None, document_ids={},
    )

    assert "weg.pdf" in report.results[0].error
