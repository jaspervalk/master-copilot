"""Oefententamens in de opbouw van het proeftentamen. Het model wordt
nagebootst; getest wordt de opbouw, de keuze van de stof, en de sloten die
voorkomen dat een oefententamen het proeftentamen in andere woorden herhaalt."""
import pytest
import yaml

from app.models import Chunk, Course, Document, PracticeCard
from app.services.hybrid_index import reset_hybrid_index
from app.services.practice.exam_generation import ExamBatch, ExamDraft, NumberCheck, RubricDraft
from app.services.practice.exams import ExamBlueprint
from app.services.practice.practice_exams import (
    ExamLayout,
    SectionMaterial,
    Slot,
    _section_prompt,
    assign_topics,
    course_blueprint,
    covers,
    duplicate_of,
    exam_plans,
    gives_away,
    generate_section,
    load_layout,
    next_origin,
    off_theme,
    plan_sections,
    section_material,
)


BAGGING = (
    "Random forests provide an improvement over bagged trees by way of a small tweak that "
    "decorrelates the trees. As in bagging, we build a number of decision trees on bootstrapped "
    "training samples. But when building these decision trees, each time a split in a tree is "
    "considered, a random sample of m predictors is chosen as split candidates from the full set "
    "of p predictors. Boosting works in a similar way, except that the trees are grown sequentially."
)
KMEANS = (
    "K-means clustering is a simple and elegant approach for partitioning a data set into K distinct, "
    "non-overlapping clusters. To perform K-means clustering, we must first specify the desired number "
    "of clusters K; then the K-means algorithm will assign each observation to exactly one of the K clusters."
)

BLUEPRINT = {
    "id": "mock-exam-1",
    "title": "Mock Exam 1",
    "course": "fundamentals-of-ds",
    "total_points": 17,
    "sections": [
        {
            "number": 3,
            "title": "Supervised Learning",
            "questions": [
                {"id": "3b", "page": 6, "type": "mc_single", "points": 1.5, "week": 3, "topic": "bagging and random forests",
                 "question": "Which is true about bagging?", "options": ["a", "b", "c", "d"], "answer": ["a"]},
                {"id": "3g", "page": 7, "type": "mc_single", "points": 1.5, "week": 2, "topic": "regularization",
                 "question": "Which technique shrinks coefficients?", "options": ["a", "b", "c", "d"], "answer": ["b"]},
                {"id": "3i", "page": 7, "type": "open", "points": 10, "week": 3, "topic": "bagging and random forests",
                 "question": "Please explain what distinguishes Random Forests from Bagging?",
                 "model_answer": "Random forests decorrelate the trees.",
                 "rubric": [{"criterion": "Decorrelation.", "points": 10}]},
            ],
        },
        {
            "number": 5,
            "title": "Ethics and Data Science",
            "questions": [
                {"id": "5f", "page": 11, "type": "open", "points": 4, "week": 6, "topic": "COMPAS case study",
                 "question": "What is the goal of the COMPAS algorithm?",
                 "model_answer": "Predict recidivism.", "rubric": [{"criterion": "Recidivism.", "points": 4}]},
            ],
        },
    ],
}


@pytest.fixture(autouse=True)
def _fresh_index():
    reset_hybrid_index()
    yield
    reset_hybrid_index()


def _book(db, *, text=BAGGING, section="Tree-Based Methods › Bagging", path="fundamentals-of-ds/books/ISLR.pdf",
          kind="book", week=None, pages=(354, 355)):
    document = Document(
        title=path.rsplit("/", 1)[-1], source_path=path, checksum=path.ljust(64, "0")[:64],
        course_slug="fundamentals-of-ds", doc_kind=kind, week=week, ingestion_status="indexed",
    )
    document.chunks.append(Chunk(
        chunk_index=0, section_path=section, page_start=pages[0], page_end=pages[1], token_count=80,
        text=text, normalized_text=text.lower(), chunk_metadata={},
    ))
    db.add(document)
    db.commit()
    return document


def _course(db):
    db.add(Course(slug="fundamentals-of-ds", name="FDS", week_plans={
        "3": {"topics": ["decision trees and ensemble methods"], "reading": [
            {"document": "fundamentals-of-ds/books/ISLR.pdf", "sections": ["Tree-Based Methods"]}]},
        "6": {"topics": ["fairness metrics and bias mitigation"]},
    }))
    db.commit()


def _blueprint_file(tmp_corpus):
    folder = tmp_corpus / "fundamentals-of-ds" / "exams"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mock-exam-1.yml").write_text(yaml.safe_dump(BLUEPRINT), encoding="utf-8")


class _Client:
    def __init__(self, *batches):
        self._batches = list(batches)
        self.calls = []
        outer = self

        class _Responses:
            def parse(self, *, model, instructions, input, text_format):
                outer.calls.append({"instructions": instructions, "input": input})
                cards = outer._batches.pop(0) if outer._batches else []
                return type("Parsed", (), {"output_parsed": ExamBatch(cards=cards)})()

        self.responses = _Responses()


def _mc(chunk_id, question="In a random forest, what is sampled at each split? (one answer)", **overrides):
    values = dict(
        chunk_id=chunk_id, kind="mc", template="definition_mc", topic="random forests", question=question,
        options=["A random sample of m predictors", "A bootstrap sample of trees", "The residuals", "The pruning level"],
        correct=["a"], multi=False, compute="", points=1.5, max_items=0, rubric=[], model_answer="",
        source_quote="a random sample of m predictors is chosen as split candidates",
        explanation="Goed: a. Een random forest trekt bij elke split een deel van de predictoren.",
    )
    values.update(overrides)
    return ExamDraft(**values)


def _open(chunk_id, question="Explain what distinguishes boosting from bagging.", points=10.0):
    return ExamDraft(
        chunk_id=chunk_id, kind="open", template="distinguish", topic="boosting", question=question,
        options=[], correct=[], multi=False, compute="", points=points, max_items=0,
        rubric=[
            RubricDraft(criterion="Bagging builds trees on bootstrapped samples.", points=points / 2,
                        source_quote="we build a number of decision trees on bootstrapped training samples"),
            RubricDraft(criterion="Boosting grows trees sequentially.", points=points / 2,
                        source_quote="except that the trees are grown sequentially"),
        ],
        model_answer="Bagging fits trees on bootstrap samples; boosting grows them sequentially.",
        source_quote="Boosting works in a similar way, except that the trees are grown sequentially",
        explanation="Noem het mechanisme van allebei, anders mis je de helft van de punten.",
    )


# --- de opbouw -------------------------------------------------------------------


def test_a_section_plan_copies_the_slots_and_finds_its_weeks():
    blueprint = ExamBlueprint.model_validate(BLUEPRINT)

    drie, vijf = plan_sections(blueprint, {"3": {"topics": ["decision trees and ensemble methods"]}})

    assert [(slot.kind, slot.points) for slot in drie.slots] == [("mc", 1.5), ("mc", 1.5), ("open", 10.0)]
    assert drie.weeks == [2, 3]
    # Week 3 draagt 11,5 van de 13 punten; week 2 met 1,5 is geen zwaartepunt.
    assert drie.main_weeks == [3]
    assert drie.topics == ["bagging and random forests", "regularization", "decision trees and ensemble methods"]
    assert drie.topic_points == {"bagging and random forests": 11.5, "regularization": 1.5}


def test_a_week_shared_by_two_sections_only_lends_topics_that_fit():
    """Week 2 van FDS is visualisatie én regressie. Regularisatie hoort bij de
    sectie die er in het proeftentamen al naar vraagt, niet bij visualisatie."""
    blueprint = ExamBlueprint.model_validate({
        "id": "m", "title": "M", "course": "c", "total_points": 3,
        "sections": [
            {"number": 2, "title": "Data visualization", "questions": [
                {"id": "2a", "page": 1, "type": "mc_single", "points": 1.5, "week": 2, "topic": "matplotlib subplots",
                 "question": "q", "options": ["a", "b"], "answer": ["a"]}]},
            {"number": 3, "title": "Supervised Learning", "questions": [
                {"id": "3g", "page": 1, "type": "mc_single", "points": 1.5, "week": 2, "topic": "regularization",
                 "question": "q", "options": ["a", "b"], "answer": ["a"]}]},
        ],
    })
    week_plans = {"2": {"topics": ["high-dimensional visualisation", "regularization", "feature engineering"]}}

    twee, drie = plan_sections(blueprint, week_plans)

    assert twee.topics == ["matplotlib subplots", "high-dimensional visualisation"]
    assert drie.topics == ["regularization"]


@pytest.mark.parametrize(
    ("tekst", "onderwerp", "verwacht"),
    [
        ("We compare the cases in this study.", "COMPAS case study", False),
        ("The COMPAS risk score predicts recidivism.", "COMPAS case study", True),
        ("Comparison of Linear Regression with K-Nearest Neighbors", "k-nearest neighbours", True),
        ("Customizing a colormap in matplotlib", "colormaps", True),
        ("The alpha transparency of each point", "fairness metrics and bias mitigation", False),
        ("the bias-variance trade-off", "bias", True),
    ],
)
def test_coverage_needs_the_distinctive_words(tekst, onderwerp, verwacht):
    assert covers(tekst, onderwerp) is verwacht


def _card(question, *, kind="open", answer="", options=None, correct=None, template=""):
    spec = {"options": options or [], "answer": correct or [], "template": template} if kind == "mc" else {}
    return PracticeCard(course_slug="c", document_id="", chunk_id="", section_path="s", page_start=1, page_end=1,
                        kind=kind, question=question, reference_answer=answer, spec=spec, origin="mock-exam-1")


def test_a_rephrased_mock_question_is_not_new():
    mock = [_card("Please explain what distinguishes Random Forests from Bagging?")]

    assert duplicate_of(_open("x", question="Explain what distinguishes random forests from bagging."), mock)
    assert duplicate_of(_open("x", question="Explain what distinguishes boosting from bagging."), mock) is None


def test_a_mock_question_without_its_preamble_is_not_new():
    """Letterlijk uit de eerste ronde: 1f zonder de aanloopzin."""
    mock = [_card(
        "Pandas is a useful framework, despite the fact that NumPy and Python already provide many useful operations "
        "to deal with data. Provide 3 operations/functionality that you can do with Pandas, and not directly with NumPy "
        "and base Python."
    )]
    kopie = _open("x", question="Give 3 operations or functionality that you can do with Pandas, and not directly with NumPy and base Python.")

    assert duplicate_of(kopie, mock)


def test_a_different_question_with_the_same_answer_is_not_new():
    mock = [_card("What is the NumPy functionality to extend a smaller array?", kind="mc",
                  options=["extension", "vectorization", "broadcasting", "list comprehension"], correct=[2])]
    anders = _mc("x", question="Which mechanism lets arrays of different shapes take part in one arithmetic operation?",
                 options=["padding", "broadcasting", "reshaping", "alignment"], correct=["b"])

    assert "hetzelfde goede antwoord" in duplicate_of(anders, mock)


def test_an_open_question_with_the_same_model_answer_is_not_new():
    mock = [_card("What are the disadvantages of having a very low parameter k in k-nn?",
                  answer="A very low k makes the model overfit: the decision boundary follows noise and outliers in the "
                         "training data. This means high variance and poor generalisation.")]
    kopie = _open("x", question="Why is choosing k = 1 in nearest neighbours risky?")
    kopie.model_answer = ("A very low k makes the model overfit the training data and follow noise and outliers, "
                          "which means high variance and poor generalisation.")

    assert "hetzelfde antwoord" in duplicate_of(kopie, mock)


def test_a_question_outside_the_section_theme_is_off_theme():
    blueprint = ExamBlueprint.model_validate(BLUEPRINT)
    drie = plan_sections(blueprint, {})[0]
    kleurschaal = _open("x", question="Which colormap type suits election results?")
    kleurschaal.model_answer = "A diverging colormap, because it has a neutral midpoint."
    kleurschaal.rubric = [RubricDraft(criterion="Names a diverging colormap.", points=10, source_quote="")]

    assert off_theme(kleurschaal, drie)
    assert not off_theme(_open("x", question="Explain what distinguishes boosting from random forests."), drie)


def test_a_scenario_whose_answer_names_the_technique_is_on_theme():
    """Een scenariovraag beschrijft het symptoom, niet de naam van de techniek."""
    drie = plan_sections(ExamBlueprint.model_validate(BLUEPRINT), {})[0]
    scenario = _open("x", question="A polynomial fit has huge coefficients and overfits. What can you do?")
    scenario.model_answer = "Use regularization: penalise the size of the coefficients."

    assert not off_theme(scenario, drie)


def test_the_shared_phrase_of_a_question_form_does_not_make_a_copy():
    """"(Mark all correct answers)" maakte van Naive Bayes een kopie van K-means."""
    mock = [_card("Which of the following are limitations of K-Means? (Mark all correct answers)", kind="mc",
                  options=["a", "b", "c", "d"], correct=[1, 3], template="limitation_mc")]
    naive = _mc("x", question="Which of the following are assumptions of Gaussian Naive Bayes? (Mark all correct answers)",
                template="limitation_mc", correct=["a", "b"], multi=True, explanation="Goed: a, b. Het zijn allebei aannames van de methode.")

    assert duplicate_of(naive, mock) is None


def test_the_same_question_form_about_another_concept_is_new():
    mock = [_card("What best defines supervised learning?", kind="mc", options=["x", "y", "z", "w"], correct=[0],
                  template="definition_mc")]
    anders = _mc("x", question="What best defines unsupervised learning?", options=["p", "q", "r", "s"])

    assert duplicate_of(anders, mock) is None


def test_the_same_question_form_about_the_same_concept_is_a_copy():
    mock = [_card("Which of the following are limitations of K-Means? (Mark all correct answers)", kind="mc",
                  options=["a", "b", "c", "d"], correct=[1, 3], template="limitation_mc")]
    kopie = _mc("x", question="Which of the following are limitations or requirements of k-means? (Mark all correct answers)",
                template="limitation_mc", options=["p", "q", "r", "s"], correct=["a", "b"], multi=True, explanation="Goed: a, b. Het zijn allebei aannames van de methode.")

    assert "hetzelfde onderwerp" in duplicate_of(kopie, mock)


def test_the_answer_of_one_question_as_the_topic_of_another_is_the_same_concept():
    """"Which colormap is this? → sequential" en "What defines a sequential colormap?"."""
    eerder = [_card("A plot uses one continuous progression of colours. Which colormap category is this?", kind="mc",
                    options=["sequential", "diverging", "qualitative", "categorical"], correct=[0], template="taxonomy_mc")]
    zelfde = _mc("x", question="What best defines a sequential colormap?",
                 options=["one continuous progression", "two hues", "unrelated colours", "only 3D"])

    assert "hetzelfde begrip (sequential)" in duplicate_of(zelfde, eerder)


def test_the_mock_question_reversed_is_a_copy():
    """3i heeft een lange aanloop; de omgekeerde vraag heeft vier inhoudswoorden, alle vier daaruit."""
    mock = [_card("Decision trees often reveal low performance when compared with more sophisticated methods. We "
                  "discussed two approaches to build sophisticated classification methods on top of Decisions Trees: "
                  "Bagging and Random Forests. Please explain what distinguishes Random Forests from Bagging?")]

    assert duplicate_of(_open("x", question="Explain what distinguishes bagging from random forests."), mock)


def test_two_open_questions_that_award_points_for_the_same_things_are_the_same():
    """"Vectorization in plaats van een Python-lus", twee keer, met een ander scenario."""
    eerder = _card("You have a Python loop over a large NumPy array and it is very slow. What can you do?")
    eerder.spec = {"rubric": [
        {"criterion": "Names vectorization, a vectorized NumPy operation or a ufunc as the technique.", "points": 2},
        {"criterion": "Explains that the loop is pushed into compiled NumPy code and becomes much faster.", "points": 2},
    ]}
    anders = _open("x", question="Applying arithmetic to every element with a loop is too slow. Which technique helps?", points=4.0)
    anders.rubric = [
        RubricDraft(criterion="Names vectorization or NumPy ufuncs as the technique instead of a loop.", points=2, source_quote=""),
        RubricDraft(criterion="Explains that the work is pushed into compiled NumPy code, avoiding Python loop overhead.", points=2, source_quote=""),
    ]
    anders.model_answer = "Use ufuncs."

    assert "geeft punten voor hetzelfde" in duplicate_of(anders, [eerder])


def test_a_correct_answer_that_says_the_same_in_other_words_is_a_copy():
    eerder = [_card("What is true about Gaussian Naive Bayes?", kind="mc", template="definition_mc", correct=[0], options=[
        "It models the predictors separately within each class and then uses Bayes' theorem to compare the classes",
        "It fits a logistic function", "It averages the nearest neighbours", "It needs no assumptions"])]
    zelfde = _mc("x", question="What is true about generative classification models?", options=[
        "They model the predictors within each class and use Bayes' theorem to infer class probabilities",
        "They ignore the predictors", "They only do regression", "They need a linear boundary"])

    assert "hetzelfde zegt" in duplicate_of(zelfde, eerder)


def test_differ_is_the_same_question_as_distinguish():
    """Letterlijk uit een ronde: "Explain how random forests differ from bagging"."""
    mock = [_card("Decision trees often reveal low performance when compared with more sophisticated methods. We "
                  "discussed two approaches: Bagging and Random Forests. Please explain what distinguishes Random "
                  "Forests from Bagging?")]

    assert duplicate_of(_open("x", question="Explain how random forests differ from bagging."), mock)


def test_the_same_open_form_and_topic_with_an_overlapping_rubric_is_a_copy():
    """2e in andere woorden: voordeel en beperking van visualisatie tegenover statistiek."""
    mock = _card("List one advantage and one limitation of data visualization when compared with, e.g., statistical methods.")
    mock.spec = {"template": "advantage_limitation", "rubric": [
        {"criterion": "A valid advantage: visualisation reveals trends, structure or outliers that summary statistics can hide.", "points": 2},
        {"criterion": "A valid limitation: a plot is a subjective reading rather than a quantified, testable result.", "points": 2},
    ]}
    kopie = _open("x", question="Identify one advantage and one limitation of data visualization compared with statistical summaries.", points=4.0)
    kopie.template = "advantage_limitation"
    kopie.model_answer = "Plots show what numbers hide, but they are not a test."
    kopie.rubric = [
        RubricDraft(criterion="One valid advantage: visualization can reveal trends or outliers hidden by summary numbers.", points=2, source_quote=""),
        RubricDraft(criterion="One valid limitation: a graph is a subjective view without a quantified statistical conclusion.", points=2, source_quote=""),
    ]

    assert "hetzelfde onderwerp" in duplicate_of(kopie, [mock])


def test_an_answer_that_stands_in_the_question_is_given_away():
    weggegeven = _open("x", question="Gradient descent usually takes many steps. Name one numerical optimization method for logistic regression.", points=4.0)
    weggegeven.model_answer = "Gradient descent."
    eerlijk = _open("x", question="Name one numerical optimization method for fitting logistic regression coefficients.", points=4.0)
    eerlijk.model_answer = "Gradient descent."

    assert gives_away(weggegeven) == "Gradient descent."
    assert gives_away(eerlijk) is None


def test_empty_slots_go_to_the_least_asked_topics_that_have_material():
    """Zonder sturing kiest het model steeds dezelfde handvol begrippen."""
    plan = plan_sections(ExamBlueprint.model_validate(BLUEPRINT), {"3": {"topics": ["gradient descent", "model validation"]}})[0]
    stof = SectionMaterial(chunks=[], uncovered=[], covered_share=1.0, per_topic={
        "bagging and random forests": ["c1", "c2", "c3"], "regularization": ["c4"],
        "gradient descent": ["c5", "c6"], "model validation": [],
    })
    gebruik = {"bagging and random forests": 3, "regularization": 1, "gradient descent": 0}

    verdeling = assign_topics([Slot("mc", 1.5), Slot("mc", 1.5), Slot("open", 10.0)], plan, stof, gebruik)

    # De zware plek eerst, naar het minst gevraagde onderwerp met stof; model
    # validation heeft geen stof en krijgt dus niets.
    assert verdeling == [
        (Slot("open", 10.0), "gradient descent"),
        (Slot("mc", 1.5), "regularization"),
        (Slot("mc", 1.5), "gradient descent"),
    ]


def test_one_word_apart_with_a_different_answer_is_new():
    """"very high k" en "very low k": één woord verschil, een ander antwoord."""
    mock = [_card("What are the disadvantages of choosing a very low value of K in K-nearest neighbours?",
                  answer="A very low k overfits: high variance, the boundary follows noise.")]
    hoog = _open("x", question="What are the disadvantages of choosing a very high value of K in K-nearest neighbours?")
    hoog.model_answer = "A very high k underfits: the boundary becomes too smooth, which gives high bias."

    assert duplicate_of(hoog, mock) is None


def test_practice_exams_are_numbered_per_course(db_session):
    assert next_origin(db_session, "fundamentals-of-ds") == "oefententamen-1"
    db_session.add(PracticeCard(
        course_slug="fundamentals-of-ds", document_id="", chunk_id="", section_path="x", page_start=1, page_end=1,
        kind="mc", question="q", reference_answer="a", origin="oefententamen-3", position=1,
    ))
    db_session.commit()

    assert next_origin(db_session, "fundamentals-of-ds") == "oefententamen-4"


# --- de stof -----------------------------------------------------------------


def test_the_material_of_a_section_comes_from_its_weeks_and_topics(db_session, tmp_corpus):
    _course(db_session)
    boek = _book(db_session)
    _book(db_session, text=KMEANS, section="Unsupervised Learning › K-Means", path="fundamentals-of-ds/books/Other.pdf")
    plan = plan_sections(ExamBlueprint.model_validate(BLUEPRINT), {"3": {"topics": []}})[0]

    material = section_material(db_session, "fundamentals-of-ds", plan)

    assert [chunk.document_id for chunk in material.chunks] == [boek.id]
    assert material.uncovered == ["regularization"]
    assert material.covered_share == 11.5 / 13


def test_lecture_slides_come_before_the_book_within_a_topic(db_session, tmp_corpus):
    """Het tentamen vraagt naar wat in de colleges besproken is."""
    _course(db_session)
    _book(db_session)
    slides = _book(db_session, text="Bagging and random forests: each split looks at a random subset of predictors.",
                   section="Lecture05 › slide 12", path="fundamentals-of-ds/slides/week-03/lecture05.pdf",
                   kind="slides", week=3, pages=(12, 12))
    plan = plan_sections(ExamBlueprint.model_validate(BLUEPRINT), {})[0]

    material = section_material(db_session, "fundamentals-of-ds", plan)

    assert material.per_topic["bagging and random forests"][0].document_id == slides.id


def test_a_section_without_material_stays_empty_and_says_why(db_session, tmp_corpus):
    """De eerste versie herschreef dan het proeftentamen zelf, en leverde een
    kaart op die het nagelopen antwoord bij 5d tegensprak."""
    _course(db_session)
    _blueprint_file(tmp_corpus)
    _book(db_session)
    _book(db_session, text="5f What is the goal of the COMPAS algorithm? Assign a score that predicts recidivism.",
          section=None, path="fundamentals-of-ds/exams/MockExam.pdf", kind="exam", pages=(11, 11))
    client = _Client()

    result = generate_section(db_session, course_slug="fundamentals-of-ds", section_number=5, client=client)

    assert result.created == []
    assert client.calls == []
    assert [slot.label() for slot in result.missing] == ["open vraag van 4 punten"]
    assert "COMPAS case study" in result.source_note
    assert "oefen deze sectie met het proeftentamen" in result.source_note


# --- een sectie genereren --------------------------------------------------------


def test_a_section_is_filled_to_its_exact_structure(db_session, tmp_corpus):
    _course(db_session)
    _blueprint_file(tmp_corpus)
    chunk_id = _book(db_session).chunks[0].id
    tweede_mc = _mc(chunk_id, question="Which ensemble method grows trees sequentially? (one answer)",
                    options=["Boosting", "Bagging", "Pruning", "Cross-validation"],
                    source_quote="the trees are grown sequentially", explanation="Goed: a. Het is boosting, want daar worden de bomen na elkaar gebouwd.")
    te_veel = _mc(chunk_id, question="What does a random forest decorrelate? (one answer)",
                  options=["The trees", "The predictors", "The samples", "The residuals"],
                  source_quote="a small tweak that decorrelates the trees", explanation="Goed: a. Het zijn de bomen die minder op elkaar gaan lijken.")
    client = _Client([_mc(chunk_id), tweede_mc, te_veel, _open(chunk_id)])

    result = generate_section(db_session, course_slug="fundamentals-of-ds", section_number=3, client=client)

    assert (result.origin, result.title) == ("oefententamen-1", "Oefententamen 1")
    assert len(result.created) == 3
    assert result.points == 13
    assert result.missing == []
    assert result.rejected[0][1].startswith("past niet meer in de opbouw")
    kaart = db_session.query(PracticeCard).filter_by(origin="oefententamen-1", position=3).one()
    assert kaart.section_path == "Oefententamen 1 › 3 Supervised Learning"
    assert (kaart.spec["section_number"], kaart.spec["based_on"], kaart.week) == (3, "mock-exam-1", 3)


def test_topping_up_a_section_only_fills_what_is_still_empty(db_session, tmp_corpus):
    """Een halfvolle sectie aanvullen mag hem niet te vol maken."""
    _course(db_session)
    _blueprint_file(tmp_corpus)
    chunk_id = _book(db_session).chunks[0].id
    eerste = generate_section(db_session, course_slug="fundamentals-of-ds", section_number=3,
                              client=_Client([_open(chunk_id)], [], []))
    assert eerste.points == 10

    client = _Client([_mc(chunk_id), _open(chunk_id, question="Explain what distinguishes pruning from bagging.")])
    aanvulling = generate_section(db_session, course_slug="fundamentals-of-ds", section_number=3,
                                  origin=eerste.origin, client=client)

    assert "- 2× meerkeuzevraag van 1.5 punt" in client.calls[0]["input"]
    assert "open vraag van 10 punten" not in client.calls[0]["input"].split("Onderwerpen")[0]
    assert aanvulling.points == 1.5
    assert aanvulling.rejected[-1][1].startswith("past niet meer in de opbouw")


def test_a_full_section_asks_the_model_nothing(db_session, tmp_corpus):
    _course(db_session)
    _blueprint_file(tmp_corpus)
    chunk_id = _book(db_session).chunks[0].id
    tweede_mc = _mc(chunk_id, question="Which ensemble method grows trees sequentially? (one answer)",
                    options=["Boosting", "Bagging", "Pruning", "Cross-validation"],
                    source_quote="the trees are grown sequentially",
                    explanation="Goed: a. Het is boosting, want daar worden de bomen na elkaar gebouwd.")
    vol = generate_section(db_session, course_slug="fundamentals-of-ds", section_number=3,
                           client=_Client([_mc(chunk_id), tweede_mc, _open(chunk_id)]))
    assert vol.missing == []

    client = _Client()
    generate_section(db_session, course_slug="fundamentals-of-ds", section_number=3, origin=vol.origin, client=client)

    assert client.calls == []


def test_a_rephrasing_of_a_mock_question_is_rejected(db_session, tmp_corpus):
    _course(db_session)
    _blueprint_file(tmp_corpus)
    db_session.add(PracticeCard(
        course_slug="fundamentals-of-ds", document_id="", chunk_id="", section_path="Mock Exam 1 › 3", page_start=7,
        page_end=7, kind="open", question="Please explain what distinguishes Random Forests from Bagging?",
        reference_answer="x", origin="mock-exam-1", position=3, spec={"section_number": 3},
    ))
    db_session.commit()
    chunk_id = _book(db_session).chunks[0].id
    herhaling = _open(chunk_id, question="Explain what distinguishes random forests from bagging.")

    result = generate_section(db_session, course_slug="fundamentals-of-ds", section_number=3, client=_Client([herhaling]))

    assert result.created == []
    assert result.rejected[0][1].startswith("lijkt te veel op")


def test_what_stays_empty_is_reported_as_missing(db_session, tmp_corpus):
    _course(db_session)
    _blueprint_file(tmp_corpus)
    chunk_id = _book(db_session).chunks[0].id

    result = generate_section(
        db_session, course_slug="fundamentals-of-ds", section_number=3, client=_Client([_open(chunk_id)])
    )

    assert [slot.label() for slot in result.missing] == ["meerkeuzevraag van 1.5 punt", "meerkeuzevraag van 1.5 punt"]


def test_the_fill_round_asks_for_exactly_the_empty_slots(db_session, tmp_corpus):
    _course(db_session)
    _blueprint_file(tmp_corpus)
    chunk_id = _book(db_session).chunks[0].id
    client = _Client([_open(chunk_id)], [])

    generate_section(db_session, course_slug="fundamentals-of-ds", section_number=3, client=client)

    # De eerste ronde plus twee aanvulrondes die niets opleveren.
    assert len(client.calls) == 3
    aanvulling = client.calls[1]["input"]
    assert "- 2× meerkeuzevraag van 1.5 punt" in aanvulling
    assert "open vraag van 10 punten" not in aanvulling.split("Onderwerpen")[0]


def test_a_rejected_repetition_is_named_in_the_next_fill_round(db_session, tmp_corpus):
    """Anders maakt het model precies de vraag opnieuw die net werd afgekeurd."""
    _course(db_session)
    _blueprint_file(tmp_corpus)
    chunk_id = _book(db_session).chunks[0].id
    eerste = _mc(chunk_id)
    herhaling = _mc(chunk_id, question="In a random forest, what is sampled at each split? (again)")
    client = _Client([eerste, herhaling, _open(chunk_id)], [])

    generate_section(db_session, course_slug="fundamentals-of-ds", section_number=3, client=client)

    aanvulrondes = [call["input"] for call in client.calls[1:] if call["input"].startswith("Maak sectie")]
    assert aanvulrondes and "(again) (afgekeurd:" in aanvulrondes[0]


def test_a_heavy_question_gets_a_round_with_one_topic(db_session, tmp_corpus):
    """Vier criteria met elk een citaat lukken zelden uit een brede greep stof."""
    _course(db_session)
    _blueprint_file(tmp_corpus)
    chunk_id = _book(db_session).chunks[0].id
    twee_mc = [_mc(chunk_id), _mc(chunk_id, question="Which ensemble method grows trees sequentially? (one answer)",
                                 options=["Boosting", "Bagging", "Pruning", "Cross-validation"],
                                 source_quote="the trees are grown sequentially", explanation="Goed: a. Het is boosting, want daar worden de bomen na elkaar gebouwd.")]
    client = _Client(twee_mc, [_open(chunk_id)])

    result = generate_section(db_session, course_slug="fundamentals-of-ds", section_number=3, client=client)

    assert result.missing == []
    assert "Maak deze vraag over:" in client.calls[1]["input"]
    assert "- 1× open vraag van 10 punten" in client.calls[1]["input"]


def test_a_card_is_attributed_to_the_chunk_that_holds_its_quote(db_session, tmp_corpus):
    """Het model noemde een chunk_id en citeerde uit een ander fragment."""
    _course(db_session)
    _blueprint_file(tmp_corpus)
    boek = _book(db_session)
    ander = _book(db_session, text="Regularization shrinks the coefficient estimates towards zero, which reduces variance.",
                  section="Tree-Based Methods › Other", path="fundamentals-of-ds/books/Other.pdf", pages=(240, 240))
    db_session.get(Course, "fundamentals-of-ds").week_plans["3"]["reading"].append(
        {"document": "fundamentals-of-ds/books/Other.pdf"})
    mc = _mc(ander.chunks[0].id)  # noemt het verkeerde fragment, citeert uit het boek

    result = generate_section(db_session, course_slug="fundamentals-of-ds", section_number=3, client=_Client([mc]))

    assert result.created[0].chunk_id == boek.chunks[0].id


# --- via de API ------------------------------------------------------------------


def test_the_api_generates_one_section_and_lists_the_new_exam(db_session, tmp_corpus, monkeypatch):
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app
    from app.services.practice import practice_exams

    _course(db_session)
    _blueprint_file(tmp_corpus)
    chunk_id = _book(db_session).chunks[0].id
    monkeypatch.setattr(practice_exams, "_client", lambda: _Client([_mc(chunk_id), _open(chunk_id)]))
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as http:
            # Het opstarten bouwt BM25 uit de echte database; deze test hoort
            # alleen zijn eigen fragmenten te zien.
            reset_hybrid_index()
            body = http.post("/api/practice/exams/generate", json={"course_slug": "fundamentals-of-ds", "section": 3}).json()
            examens = http.get("/api/practice/exams", params={"course_slug": "fundamentals-of-ds"}).json()
            leeg = http.post(
                "/api/practice/exams/generate",
                json={"course_slug": "fundamentals-of-ds", "section": 5, "origin": body["origin"]},
            ).json()
    finally:
        app.dependency_overrides.clear()

    assert (body["origin"], body["title"], body["created"], body["points"]) == ("oefententamen-1", "Oefententamen 1", 2, 11.5)
    assert body["missing"] == ["meerkeuzevraag van 1.5 punt"]
    assert [(exam["title"], [s["number"] for s in exam["sections"]]) for exam in examens] == [("Oefententamen 1", [3])]
    # Sectie 5 heeft geen stof: niets gemaakt, en de reden staat erbij.
    assert leeg["created"] == 0 and "COMPAS case study" in leeg["source_note"]


# --- de opbouw van het echte tentamen -------------------------------------------

# Het proeftentamen is van vorig jaar: vijf secties, meerkeuze voor 1,5 punt,
# open vragen tot 10. College 13 gaf de opbouw van dit jaar: zes groepen,
# meerkeuze voor 1 punt, open vragen van 2 tot 6. De vragen van het proeftentamen
# blijven het voorbeeld voor de vorm.
LAYOUT = {
    "title": "Tentamen 2026",
    "source": "college 13, slide 9",
    "total_points": 12,
    "sections": [
        {"number": 1, "title": "Statistical Learning — Supervised Learning", "mc": 2, "open": [3, 4], "examples": ["3b", "3i"]},
        {"number": 2, "title": "Ethics and Data Science", "mc": 1, "open": [2], "examples": ["5f"]},
    ],
}


def test_a_layout_sets_the_slots_and_borrows_the_mock_questions_as_examples():
    blueprint = ExamBlueprint.model_validate(BLUEPRINT)
    layout = ExamLayout.model_validate(LAYOUT)

    supervised, ethiek = plan_sections(blueprint, {}, layout=layout)

    assert (supervised.number, supervised.title) == (1, "Statistical Learning — Supervised Learning")
    assert [(slot.kind, slot.points) for slot in supervised.slots] == [("mc", 1.0), ("mc", 1.0), ("open", 3.0), ("open", 4.0)]
    assert [question.id for question in supervised.original] == ["3b", "3i"]
    assert supervised.weeks == [3]
    assert [(slot.kind, slot.points) for slot in ethiek.slots] == [("mc", 1.0), ("open", 2.0)]
    assert ethiek.topic_points == {"COMPAS case study": 4.0}


def test_a_layout_must_add_up_and_point_at_real_mock_questions(tmp_path):
    blueprint = ExamBlueprint.model_validate(BLUEPRINT)
    wrong_total = tmp_path / "opbouw.yml"
    wrong_total.write_text(yaml.safe_dump({**LAYOUT, "total_points": 13}), encoding="utf-8")
    unknown = tmp_path / "opbouw-2.yml"
    unknown.write_text(yaml.safe_dump({**LAYOUT, "sections": [{**LAYOUT["sections"][0], "examples": ["9z"]}, LAYOUT["sections"][1]]}), encoding="utf-8")

    layout, problems = load_layout(wrong_total, blueprint)
    assert layout is None and any("12" in problem and "13" in problem for problem in problems)
    layout, problems = load_layout(unknown, blueprint)
    assert layout is None and any("9z" in problem for problem in problems)


def test_the_generator_follows_the_layout_when_there_is_one(db_session, tmp_corpus):
    _blueprint_file(tmp_corpus)
    _course(db_session)
    (tmp_corpus / "fundamentals-of-ds" / "exams" / "opbouw.yml").write_text(yaml.safe_dump(LAYOUT), encoding="utf-8")

    plans = exam_plans(db_session, "fundamentals-of-ds")

    assert [(plan.number, plan.title) for plan in plans] == [
        (1, "Statistical Learning — Supervised Learning"),
        (2, "Ethics and Data Science"),
    ]


def test_the_largest_transcription_is_the_blueprint(db_session, tmp_corpus):
    """De zes voorbeeldvragen van college 13 staan als transcriptie naast het
    proeftentamen, en sorteren er op naam vóór ("college-13" < "mock-exam-1").
    Zonder deze regel werden die zes het model voor elk nieuw oefententamen."""
    _blueprint_file(tmp_corpus)
    klein = {**BLUEPRINT, "id": "college-13", "title": "College 13", "total_points": 1.5,
             "sections": [{**BLUEPRINT["sections"][0], "questions": BLUEPRINT["sections"][0]["questions"][:1]}]}
    (tmp_corpus / "fundamentals-of-ds" / "exams" / "college-13.yml").write_text(yaml.safe_dump(klein), encoding="utf-8")

    assert course_blueprint("fundamentals-of-ds").id == "mock-exam-1"


def test_without_a_layout_the_generator_keeps_the_mock_sections(db_session, tmp_corpus):
    _blueprint_file(tmp_corpus)
    _course(db_session)

    plans = exam_plans(db_session, "fundamentals-of-ds")

    assert [plan.number for plan in plans] == [3, 5]
    assert [slot.points for slot in plans[0].slots] == [1.5, 1.5, 10.0]


def test_a_section_made_from_the_layout_follows_its_points(db_session, tmp_corpus):
    """Meerkeuze is dit jaar 1 punt en een open vraag 2 tot 6. De regels van
    vorig jaar (1,5 punt; 4, 6 of 10) keurden elke vraag van 3 punten af."""
    _blueprint_file(tmp_corpus)
    _course(db_session)
    (tmp_corpus / "fundamentals-of-ds" / "exams" / "opbouw.yml").write_text(yaml.safe_dump(LAYOUT), encoding="utf-8")
    chunk_id = _book(db_session).chunks[0].id
    tweede_mc = _mc(chunk_id, question="Which ensemble method grows trees sequentially? (one answer)",
                    options=["Boosting", "Bagging", "Pruning", "Cross-validation"],
                    source_quote="the trees are grown sequentially", explanation="Goed: a. Het is boosting, want daar worden de bomen na elkaar gebouwd.")
    drie = _open(chunk_id, points=3.0)
    vier = ExamDraft(
        chunk_id=chunk_id, kind="open", template="mechanism", topic="random forests",
        question="Explain how a random forest makes its trees less alike than bagged trees.",
        options=[], correct=[], multi=False, compute="", points=4.0, max_items=0,
        rubric=[
            RubricDraft(criterion="At each split only a random sample of m predictors is considered.", points=2.0,
                        source_quote="a random sample of m predictors is chosen as split candidates"),
            RubricDraft(criterion="This decorrelates the trees.", points=2.0,
                        source_quote="a small tweak that decorrelates the trees"),
        ],
        model_answer="Each split may only use a random subset of m predictors, which decorrelates the trees.",
        source_quote="a small tweak that decorrelates the trees",
        explanation="Noem zowel de willekeurige deelverzameling predictoren als het effect: minder gecorreleerde bomen.",
    )
    client = _Client([_mc(chunk_id, points=1.0), tweede_mc, drie, vier])

    result = generate_section(db_session, course_slug="fundamentals-of-ds", section_number=1, client=client)

    assert result.section_title == "Statistical Learning — Supervised Learning"
    assert result.planned_points == 9
    assert sorted(card.points for card in result.created) == [1.0, 1.0, 3.0, 4.0], result.rejected
    assert result.missing == []


def test_a_layout_group_can_name_extra_topics_from_the_study_guide():
    """Link prediction hoort bij netwerken, maar deelt geen woord met de titel
    "Network Science"; dan valt het onderwerp tussen twee groepen in."""
    blueprint = ExamBlueprint.model_validate(BLUEPRINT)
    layout = ExamLayout.model_validate({
        **LAYOUT,
        "sections": [{**LAYOUT["sections"][0], "topics": ["bias-variance tradeoff"]}, LAYOUT["sections"][1]],
    })

    supervised, _ = plan_sections(blueprint, {}, layout=layout)

    assert "bias-variance tradeoff" in supervised.topics
    assert {"bias", "variance", "tradeoff"} & supervised.theme_words


def test_a_layout_brings_the_style_of_its_course(db_session, tmp_corpus):
    """SSO stelt rekenvragen in eigen vormen; de opbouw geeft inleiding, vormen
    en welke vormen een narekening nodig hebben, en de generator gebruikt ze."""
    _blueprint_file(tmp_corpus)
    _course(db_session)
    stijl = {
        **LAYOUT,
        "intro": "Je maakt oefenvragen voor het tentamen Statistics, Simulation and Optimization.",
        "templates": {"ensemble_count": "Open: reken iets uit over een ensemble.", "definition_mc": "Meerkeuze."},
        "numeric_templates": ["ensemble_count"],
    }
    (tmp_corpus / "fundamentals-of-ds" / "exams" / "opbouw.yml").write_text(yaml.safe_dump(stijl), encoding="utf-8")
    chunk_id = _book(db_session).chunks[0].id
    reken = ExamDraft(
        chunk_id=chunk_id, kind="open", template="ensemble_count", topic="random forests",
        question="A random forest considers m = sqrt(p) predictors per split. With p = 16, how many is that?",
        options=[], correct=[], multi=False, compute="", points=3.0, max_items=0,
        rubric=[RubricDraft(criterion="Uses a random sample of m predictors.", points=3.0,
                            source_quote="a random sample of m predictors is chosen as split candidates")],
        model_answer="Taking the square root of the number of predictors gives m = 4 candidates at every split of every tree.",
        source_quote="a random sample of m predictors is chosen as split candidates",
        explanation="Een random forest kijkt per split naar een deel van de predictoren.",
        checks=[NumberCheck(label="m", setup="p = 16", expression="np.sqrt(p)")],
    )
    zonder = reken.model_copy(update={
        "question": "With p = 25 predictors, how many are considered per split of a random forest tree?",
        "model_answer": "Taking the square root of the number of predictors gives m = 5 candidates at every split.",
        "points": 4.0,
        "rubric": [RubricDraft(criterion="Uses a random sample of m predictors.", points=4.0,
                               source_quote="a random sample of m predictors is chosen as split candidates")],
        "checks": [],
    })
    client = _Client([reken, zonder])

    result = generate_section(db_session, course_slug="fundamentals-of-ds", section_number=1, client=client)

    assert "Statistics, Simulation and Optimization" in client.calls[0]["instructions"]
    assert [card.question for card in result.created] == [reken.question], result.rejected
    assert any("narekening" in reden for _, reden in result.rejected)


def test_a_layout_group_can_widen_its_weeks():
    """De voorbeeldvragen van SSO-vraag 1 gaan allemaal over week 1, maar de
    rangtoetsen en de kruistabellen van week 2 horen bij dezelfde vraag. Zonder
    extra weken vond de generator daar nooit stof voor."""
    blueprint = ExamBlueprint.model_validate(BLUEPRINT)
    layout = ExamLayout.model_validate({
        **LAYOUT,
        "sections": [{**LAYOUT["sections"][0], "weeks": [2, 3, 4]}, LAYOUT["sections"][1]],
    })

    supervised, ethiek = plan_sections(blueprint, {}, layout=layout)

    assert supervised.weeks == [2, 3, 4]
    # Het zwaartepunt blijft waar de voorbeelden liggen: dat is de week op de kaart.
    assert supervised.main_weeks == [3]
    assert ethiek.weeks == [6]


def test_a_group_with_forms_asks_for_one_scenario_with_parts_in_order():
    """Een SSO-vraag is één situatie met deelvragen die erop voortbouwen. Met een
    onderwerp per plek kwamen er losse vragen over vier onderwerpen uit, en vraag
    1 had geen enkele rekenvraag."""
    blueprint = ExamBlueprint.model_validate(BLUEPRINT)
    layout = ExamLayout.model_validate({
        **LAYOUT,
        "sections": [{**LAYOUT["sections"][0], "forms": ["advantage_limitation", "distinguish"]}, LAYOUT["sections"][1]],
    })
    supervised, _ = plan_sections(blueprint, {}, layout=layout)

    prompt = _section_prompt(supervised, ["1 Supervised", "2 Ethics"], [], [], supervised.slots,
                             assignment=[(slot, "bagging and random forests") for slot in supervised.slots])

    assert supervised.forms == ["advantage_limitation", "distinguish"]
    assert "één situatie" in prompt
    assert prompt.index("advantage_limitation") < prompt.index("distinguish")
    assert "bagging and random forests" in prompt


def test_the_forms_of_a_group_must_fit_its_parts(tmp_path):
    blueprint = ExamBlueprint.model_validate(BLUEPRINT)
    path = tmp_path / "opbouw.yml"
    path.write_text(yaml.safe_dump({**LAYOUT, "sections": [
        {**LAYOUT["sections"][0], "forms": ["distinguish"]},
        {**LAYOUT["sections"][1], "forms": ["bestaat_niet"]},
    ]}), encoding="utf-8")

    layout, problems = load_layout(path, blueprint)

    assert layout is None
    assert any("1 vormen voor 2 open" in problem for problem in problems)
    assert any("bestaat_niet" in problem for problem in problems)
