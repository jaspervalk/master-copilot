"""Tentamenvragen voor een ander vak dan FDS: eigen vormen, en getallen die
worden nagerekend.

Het SSO-tentamen is rekenwerk: een toetsingsgrootheid, een interval, een
optimum, een kortste pad. Een modelantwoord met een verkeerd getal leert je het
verkeerde antwoord, en het model rekent zich daar geregeld in vast (bij de
codekaarten zat het vijf van de zestien keer fout over zijn eigen uitvoer).
Daarom draagt een rekenvraag een narekening per getal.
"""
from __future__ import annotations

from app.models import Chunk
from app.services.practice.exam_generation import (
    ExamDraft,
    NumberCheck,
    RubricDraft,
    accept_exam_draft,
    exam_instructions,
)
from app.services.practice.exam_style import Scoring, Style
from app.services.practice.sandbox import evaluate


MATERIAAL = (
    "The one-sample proportion test uses the test statistic T = (p-hat - p0) / sqrt(p0 (1 - p0) / n). "
    "Under H0 the test statistic is approximately standard normally distributed."
)
SSO_STYLE = Style(
    intro="Je maakt oefenvragen voor het schriftelijke tentamen Statistics, Simulation and Optimization.",
    templates={
        "test_procedure": "Open: hypothesen, de juiste toets, de toetsingsgrootheid, conclusie.",
        "graphical_lp": "Open: los een LP met twee variabelen grafisch op.",
    },
    numeric=frozenset({"test_procedure", "graphical_lp"}),
)
SSO_SCORING = Scoring(choice_points=1.0, open_points=(0.5, 0.75))


def _chunk() -> Chunk:
    return Chunk(id="c1", document_id="d1", chunk_index=0, page_start=1, page_end=1, token_count=40,
                 text=MATERIAAL, normalized_text=MATERIAAL)


def _draft(**overrides) -> ExamDraft:
    values = dict(
        chunk_id="c1", kind="open", template="test_procedure", topic="one-sample proportion test",
        question="The NS claims at least 90% of 252 planned buses go; 215 went. Compute the test statistic T.",
        options=[], correct=[], multi=False, compute="", points=0.5, max_items=0,
        rubric=[
            RubricDraft(criterion="Uses the one-sample proportion test statistic.", points=0.25,
                        source_quote="The one-sample proportion test uses the test statistic"),
            RubricDraft(criterion="T is approximately standard normal under H0.", points=0.25,
                        source_quote="Under H0 the test statistic is approximately standard normally distributed"),
        ],
        model_answer="p-hat = 215/252 = 0.853, so T = (0.853 - 0.9) / sqrt(0.9 * 0.1 / 252) = -2.48.",
        source_quote="The one-sample proportion test uses the test statistic",
        explanation="Gebruik p0 onder de wortel, niet p-hat.",
        checks=[NumberCheck(label="T", setup="n = 252\nx = 215\np0 = 0.9",
                            expression="(x / n - p0) / np.sqrt(p0 * (1 - p0) / n)")],
    )
    values.update(overrides)
    return ExamDraft(**values)


def _accept(draft: ExamDraft) -> str | None:
    return accept_exam_draft(draft, {"c1": _chunk()}, set(), scoring=SSO_SCORING, style=SSO_STYLE)


def test_the_sandbox_can_solve_an_lp_and_find_a_shortest_path():
    """Zonder deze twee valt deel 2 van SSO niet na te rekenen."""
    lp = evaluate("", "optimize.linprog([2, 4], A_ub=[[-1, -1.5], [-1, -3]], b_ub=[-6, -9]).fun")
    pad = evaluate(
        "w = np.array([[0, 6, 4, 7, 0], [1, 0, 0, 1, 0], [0, 1, 0, 3, 4], [0, 0, 0, 0, 1], [0, 0, 0, 0, 0]])",
        "csgraph.dijkstra(w, indices=0)[4]",
    )

    assert lp.error is None and abs(lp.number - 14.0) < 1e-6
    assert pad.error is None and pad.number == 7.0


def test_a_numeric_question_whose_checks_match_its_model_answer_is_accepted():
    assert _accept(_draft()) is None


def test_a_numeric_question_without_checks_is_refused():
    reden = _accept(_draft(checks=[]))

    assert reden is not None and "narekening" in reden


def test_a_check_whose_number_is_not_in_the_model_answer_is_refused():
    """Het model schreef 2,36 op waar 2,223 uitkwam: precies wat dit vangt."""
    verkeerd = _draft(model_answer="p-hat = 215/252 = 0.853, so T = (0.853 - 0.9) / sqrt(0.9 * 0.1 / 252) = -2.36.")

    reden = _accept(verkeerd)

    assert reden is not None and "-2.478" in reden


def test_a_check_that_does_not_compute_a_number_is_refused():
    reden = _accept(_draft(checks=[NumberCheck(label="T", setup="", expression="undefined_name + 1")]))

    assert reden is not None and "T" in reden


def test_a_course_style_brings_its_own_intro_and_forms():
    instructies = exam_instructions("sso", SSO_SCORING, SSO_STYLE)

    assert "Statistics, Simulation and Optimization" in instructies
    assert "test_procedure" in instructies and "graphical_lp" in instructies
    assert "Fundamentals of Data Science" not in instructies
    # Een voorbeeld per soort narekening: zonder voorbeeld gaf het model bij een
    # LP vaak geen narekening, of een die zijn eigen getallen overdeed.
    assert "optimize.linprog" in instructies and "csgraph.dijkstra" in instructies
    # Een vorm van FDS bestaat in deze stijl niet.
    assert "hoort niet bij een open vraag" in _accept(_draft(template="distinguish"))


LP_STYLE = Style(
    intro="SSO",
    templates={"graphical_lp": "Open: los een LP grafisch op."},
    numeric=frozenset({"graphical_lp"}),
    solvers={"graphical_lp": "optimize."},
)
LP_MATERIAAL = "Shifting the objective line in a parallel way shows the first feasible solution that is reached."


def _lp_draft(**overrides) -> ExamDraft:
    values = dict(
        chunk_id="c1", kind="open", template="graphical_lp", topic="graphical solution",
        question="max 3x + 5y s.t. x + 3y <= 12, 2x + y <= 10, x, y >= 0. Solve graphically.",
        options=[], correct=[], multi=False, compute="", points=0.75, max_items=0,
        rubric=[RubricDraft(criterion="Finds the optimal corner by shifting the objective line.", points=0.75,
                            source_quote="Shifting the objective line in a parallel way")],
        model_answer="The optimum is the intersection of x + 3y = 12 and 2x + y = 10: x = 3.6, y = 2.8, profit 24.8.",
        source_quote="Shifting the objective line in a parallel way",
        explanation="Snijpunt van de twee restricties.",
        checks=[NumberCheck(label="profit", setup="",
                            expression="-optimize.linprog([-3, -5], A_ub=[[1, 3], [2, 1]], b_ub=[12, 10]).fun")],
    )
    values.update(overrides)
    return ExamDraft(**values)


def _accept_lp(draft: ExamDraft) -> str | None:
    chunk = Chunk(id="c1", document_id="d1", chunk_index=0, page_start=1, page_end=1, token_count=20,
                  text=LP_MATERIAAL, normalized_text=LP_MATERIAAL)
    return accept_exam_draft(draft, {"c1": chunk}, set(), scoring=Scoring(1.0, (0.75,)), style=LP_STYLE)


def test_an_lp_solved_with_the_solver_is_accepted():
    assert _accept_lp(_lp_draft()) is None


def test_an_lp_checked_with_its_own_arithmetic_is_refused():
    """In de eerste SSO-ronde rekende de narekening 3*6 + 5*2 = 28 na, terwijl
    (6, 2) niet eens toegelaten was: het optimum is 24.8. Een narekening die het
    eigen rekenwerk overdoet, controleert niets."""
    eigen = _lp_draft(
        model_answer="The optimum is x = 6, y = 2 with profit 3*6 + 5*2 = 28.",
        checks=[NumberCheck(label="profit", setup="", expression="3 * 6 + 5 * 2")],
    )

    reden = _accept_lp(eigen)

    assert reden is not None and "optimize." in reden


def test_the_criteria_of_a_checked_question_need_no_literal_quote():
    """De aantekeningen van SSO deel 2 zijn formules in notebookopmaak; een
    criterium als 'het optimum is (3.6, 2.8)' staat daar nooit letterlijk in, en
    zo vielen alle grafische LP's af. De narekening met de solver is hier de
    strengere controle; de vraag zelf moet nog wel op een citaat steunen."""
    los = _lp_draft(rubric=[RubricDraft(criterion="Optimum (3.6, 2.8) with profit 24.8.", points=0.75,
                                        source_quote="the optimum is at the intersection of both constraints")])

    assert _accept_lp(los) is None


def test_an_unchecked_form_still_needs_quotes_for_its_criteria():
    vrij = _draft(template="test_procedure", checks=[], rubric=[
        RubricDraft(criterion="Anything.", points=0.5, source_quote="this sentence is nowhere in the material")])
    style = Style(intro="SSO", templates={"test_procedure": "Open."}, numeric=frozenset())

    reden = accept_exam_draft(vrij, {"c1": _chunk()}, set(), scoring=SSO_SCORING, style=style)

    assert reden is not None and "citaat" in reden
