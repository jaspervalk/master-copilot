"""Nakijken van tentamenvragen. Het model wordt nagebootst; wat getest wordt is
wat er ná het model gebeurt — want daar zit het slot tegen een mild oordeel."""
import pytest

from app.models import PracticeCard
from app.services.practice.grading import (
    CriterionVerdict,
    InvalidChoice,
    NoGrader,
    OpenVerdict,
    grade_choice,
    grade_open,
    parse_letters,
)


def _choice(*, answer=(2,), multi=False, points=1.5):
    return PracticeCard(
        course_slug="fundamentals-of-ds", document_id="", chunk_id="", section_path="Mock Exam 1 › 3",
        page_start=6, page_end=6, kind="mc", question="What is the False Negative Rate?",
        reference_answer="c", points=points,
        spec={"options": ["6/11", "5/6", "1/6", "5/11"], "multi": multi, "answer": list(answer)},
    )


def _open(*, points=4.0, rubric=None, max_items=None):
    return PracticeCard(
        id="kaart-1", course_slug="fundamentals-of-ds", document_id="", chunk_id="",
        section_path="Mock Exam 1 › 3", page_start=7, page_end=7, kind="open",
        question="What are the disadvantages of having a very low parameter k in k-nn?",
        reference_answer="Overfitting and high variance.", points=points,
        spec={
            "rubric": rubric or [
                {"criterion": "Overfitting.", "points": 2},
                {"criterion": "High variance.", "points": 2},
            ],
            "max_items": max_items,
        },
    )


class _FakeGrader:
    def __init__(self, verdict: OpenVerdict):
        self.calls = []
        outer = self

        class _Responses:
            def parse(self, *, model, instructions, input, text_format):
                outer.calls.append({"instructions": instructions, "input": input})
                return type("Parsed", (), {"output_parsed": verdict})()

        self.responses = _Responses()


# --- meerkeuze --------------------------------------------------------------


@pytest.mark.parametrize("typed", ["c", "C", " c ", "(c)"])
def test_a_letter_can_be_typed_in_several_ways(typed):
    assert parse_letters(typed, 4) == [2]


def test_several_letters_are_one_choice():
    assert parse_letters("b, d", 4) == parse_letters("db", 4) == [1, 3]


def test_a_letter_beyond_the_options_is_refused():
    with pytest.raises(InvalidChoice, match="e is geen optie"):
        parse_letters("e", 4)


def test_the_right_option_scores_the_points():
    result = grade_choice(_choice(), "c")

    assert (result.correct, result.score, result.max_score) == (True, 1.5, 1.5)


def test_the_recall_instead_of_the_false_negative_rate_scores_nothing():
    result = grade_choice(_choice(), "b")

    assert (result.correct, result.score, result.expected) == (False, 0.0, [2])


def test_a_multiple_answer_question_needs_exactly_the_right_set():
    """Zoals op het tentamen: alle goede, en geen foute erbij."""
    card = _choice(answer=(1, 3), multi=True)

    assert grade_choice(card, "b, d").correct
    assert not grade_choice(card, "b").correct
    assert not grade_choice(card, "a, b, d").correct


def test_a_single_answer_question_refuses_two_letters():
    with pytest.raises(InvalidChoice, match="precies één"):
        grade_choice(_choice(), "b, c")


# --- open vragen ------------------------------------------------------------

ANTWOORD = "With k = 1 the model overfits: it follows the noise, so it has high variance."


def test_points_backed_by_a_real_quote_are_kept():
    grader = _FakeGrader(OpenVerdict(
        criteria=[
            CriterionVerdict(criterion=0, awarded=2, evidence="the model overfits", comment="Goed."),
            CriterionVerdict(criterion=1, awarded=2, evidence="it has high variance", comment="Goed."),
        ],
        feedback="Volledig.",
    ))

    result = grade_open(_open(), ANTWOORD, client=grader)

    assert (result.score, result.max_score, result.correct) == (4.0, 4.0, True)
    assert [c.awarded for c in result.criteria] == [2, 2]


def test_a_point_for_something_you_did_not_write_is_withdrawn():
    """Het slot: een mild model dat een citaat verzint levert geen punten op."""
    grader = _FakeGrader(OpenVerdict(
        criteria=[
            CriterionVerdict(criterion=0, awarded=2, evidence="the model overfits", comment="Goed."),
            CriterionVerdict(criterion=1, awarded=2, evidence="low bias but high variance", comment="Goed."),
        ],
        feedback="",
    ))

    result = grade_open(_open(), "With k = 1 the model overfits.", client=grader)

    assert result.score == 2.0
    assert result.criteria[1].withdrawn
    assert result.criteria[1].awarded == 0


def test_quotes_are_matched_regardless_of_case_and_punctuation():
    grader = _FakeGrader(OpenVerdict(
        criteria=[CriterionVerdict(criterion=0, awarded=2, evidence="Model Overfits", comment="")],
        feedback="",
    ))

    result = grade_open(_open(), ANTWOORD, client=grader)

    assert result.criteria[0].awarded == 2


def test_awarded_points_are_capped_at_the_criterion():
    grader = _FakeGrader(OpenVerdict(
        criteria=[CriterionVerdict(criterion=0, awarded=9, evidence="the model overfits", comment="")],
        feedback="",
    ))

    result = grade_open(_open(), ANTWOORD, client=grader)

    assert result.criteria[0].awarded == 2
    assert result.score == 2


def test_a_criterion_the_model_skipped_scores_nothing():
    grader = _FakeGrader(OpenVerdict(
        criteria=[CriterionVerdict(criterion=0, awarded=2, evidence="the model overfits", comment="")],
        feedback="",
    ))

    result = grade_open(_open(), ANTWOORD, client=grader)

    assert result.criteria[1].awarded == 0
    assert result.criteria[1].comment == "Niet beoordeeld."


def test_three_quarters_counts_as_passed_for_the_review_schedule():
    rubric = [{"criterion": "A", "points": 3}, {"criterion": "B", "points": 1}]
    grader = _FakeGrader(OpenVerdict(
        criteria=[CriterionVerdict(criterion=0, awarded=3, evidence="overfits", comment="")],
        feedback="",
    ))

    result = grade_open(_open(rubric=rubric), ANTWOORD, client=grader)

    assert (result.score, result.correct) == (3.0, True)


def test_an_empty_answer_is_zero_without_asking_a_model():
    result = grade_open(_open(), "   ", client=None)

    assert result.score == 0
    assert not result.correct


def test_without_a_model_an_open_answer_cannot_be_graded(monkeypatch):
    from app.services.practice import grading

    monkeypatch.setattr(grading, "_client", lambda: None)

    with pytest.raises(NoGrader):
        grade_open(_open(), ANTWOORD)


def test_the_prompt_carries_the_rubric_and_the_item_limit():
    grader = _FakeGrader(OpenVerdict(criteria=[], feedback=""))
    card = _open(
        points=6.0,
        rubric=[{"criterion": "First example.", "points": 3}, {"criterion": "Second example.", "points": 3}],
        max_items=2,
    )

    grade_open(card, "Decision trees, linear regression, k-NN.", client=grader)

    prompt = grader.calls[0]["input"]
    assert "[1] (3 punten) First example." in prompt
    assert "Alleen de eerste 2 items" in prompt
    assert "<<<\nDecision trees, linear regression, k-NN.\n>>>" in prompt


# --- de nummering van de criteria ---------------------------------------------
# Het model nummerde de criteria soms vanaf 1 terwijl de code vanaf 0 zocht. Een
# criterium zonder oordeel telde als 0 punten: "PCA" kreeg 0 van 4 bij "Names
# principal component analysis (PCA)", en bij "(linear) regression, decision
# trees" kwam het oordeel over het eerste voorbeeld bij het tweede criterium.


def test_the_rubric_is_numbered_from_one_in_the_prompt():
    grader = _FakeGrader(OpenVerdict(criteria=[], feedback=""))

    grade_open(_open(), ANTWOORD, client=grader)

    prompt = grader.calls[0]["input"]
    assert "[1] (2 punten) Overfitting." in prompt and "[2] (2 punten) High variance." in prompt
    assert "[0]" not in prompt


def test_a_single_criterion_numbered_one_is_not_lost():
    card = _open(rubric=[{"criterion": "Names principal component analysis (PCA).", "points": 4}])
    grader = _FakeGrader(OpenVerdict(
        criteria=[CriterionVerdict(criterion=1, awarded=4, evidence="PCA", comment="Goed.")],
        feedback="",
    ))

    result = grade_open(card, "PCA", client=grader)

    assert result.score == 4.0


def test_criteria_numbered_from_one_land_on_their_own_criterion():
    grader = _FakeGrader(OpenVerdict(
        criteria=[
            CriterionVerdict(criterion=1, awarded=2, evidence="the model overfits", comment="Goed."),
            CriterionVerdict(criterion=2, awarded=0, evidence="", comment="Ontbreekt."),
        ],
        feedback="",
    ))

    result = grade_open(_open(), "With k = 1 the model overfits.", client=grader)

    assert [c.awarded for c in result.criteria] == [2, 0]
    assert result.criteria[0].evidence == "the model overfits"


def test_a_grader_that_still_counts_from_zero_is_understood():
    """Een 0 in de nummering zegt dat het model vanaf 0 telt, zoals de oude prompt."""
    grader = _FakeGrader(OpenVerdict(
        criteria=[
            CriterionVerdict(criterion=0, awarded=0, evidence="", comment="Ontbreekt."),
            CriterionVerdict(criterion=1, awarded=2, evidence="it has high variance", comment="Goed."),
        ],
        feedback="",
    ))

    result = grade_open(_open(), ANTWOORD, client=grader)

    assert [c.awarded for c in result.criteria] == [0, 2]


def test_spelling_does_not_cost_points():
    """Een geschreven tentamen is geen spellingtoets. "gradient decent." kreeg 0 van
    4 met als reden "niet correct gespeld", terwijl dezelfde nakijker "gradient
    decent" zonder punt de volle punten gaf."""
    from app.services.practice.grading import GRADER_INSTRUCTIONS

    assert "gradient decent" in GRADER_INSTRUCTIONS
    assert "spel" in GRADER_INSTRUCTIONS.lower()
