"""Tentamenvragen uit het materiaal. Het model wordt nagebootst; getest wordt
wat ná het model gebeurt: citaten opzoeken, de rekenvraag narekenen, vorm en
punten afdwingen, en één herstelronde."""
import pytest
import yaml

from app.models import Chunk, Document, PracticeCard
from app.services.practice.exam_generation import ExamBatch, ExamDraft, RubricDraft, grounded, squash
from app.services.practice.generation import generate_cards


SECTION = "Tree-Based Methods › Bagging, Random Forests, Boosting"
TEKST = (
    "Random forests provide an improvement over bagged trees by way of a small tweak that "
    "decorrelates the trees. As in bagging, we build a number of decision trees on bootstrapped "
    "training samples. But when building these decision trees, each time a split in a tree is "
    "considered, a random sample of m predictors is chosen as split candidates from the full set "
    "of p predictors. Typically we choose m ≈ √p. This makes the average of the resulting trees "
    "less variable and hence more reliable. Using a small value of m in building a random forest "
    "will typically be helpful when we have a large number of correlated predictors."
)


def _document(db, *, text=TEKST, week=None, course_slug="fundamentals-of-ds"):
    document = Document(
        title="ISLRv2", source_path=f"{course_slug}/books/ISLRv2.pdf", checksum="0" * 64,
        course_slug=course_slug, doc_kind="book", week=week, ingestion_status="indexed",
    )
    document.chunks.append(Chunk(
        chunk_index=0, section_path=SECTION, page_start=354, page_end=355, token_count=90,
        text=text, normalized_text=text.lower(), chunk_metadata={},
    ))
    db.add(document)
    db.commit()
    return document


class _Client:
    """Levert per aanroep de volgende batch en onthoudt de prompts."""

    def __init__(self, *batches):
        self._batches = list(batches)
        self.calls = []
        outer = self

        class _Responses:
            def parse(self, *, model, instructions, input, text_format):
                outer.calls.append({"instructions": instructions, "input": input})
                return type("Parsed", (), {"output_parsed": ExamBatch(cards=outer._batches.pop(0))})()

        self.responses = _Responses()


def _mc(chunk_id, **overrides):
    values = dict(
        chunk_id=chunk_id, kind="mc", template="definition_mc", topic="random forests",
        question="What distinguishes a random forest from bagged trees?",
        options=[
            "Each split considers only a random sample of the predictors",
            "Each tree is trained on the full training set without resampling",
            "The trees are pruned more aggressively",
            "The trees are combined by a weighted vote on their accuracy",
        ],
        correct=["a"], multi=False, compute="", points=1.5, max_items=0, rubric=[], model_answer="",
        source_quote="a random sample of m predictors is chosen as split candidates",
        explanation="Goed: a. Een random forest kijkt bij elke split naar een deel van de predictoren, niet naar alle.",
    )
    values.update(overrides)
    return ExamDraft(**values)


def _open(chunk_id, **overrides):
    values = dict(
        chunk_id=chunk_id, kind="open", template="distinguish", topic="random forests",
        question="Explain what distinguishes random forests from bagging.",
        options=[], correct=[], multi=False, compute="", points=4.0, max_items=0,
        rubric=[
            RubricDraft(criterion="Both use bootstrapped training samples.", points=2,
                        source_quote="we build a number of decision trees on bootstrapped training samples"),
            RubricDraft(criterion="Random forests sample m predictors at each split.", points=2,
                        source_quote="a random sample of m predictors is chosen as split candidates"),
        ],
        model_answer="Both bag bootstrapped trees; a random forest considers m random predictors per split.",
        source_quote="Random forests provide an improvement over bagged trees",
        explanation="Noem wat de twee gemeen hebben en wat het verschil is, anders krijg je niet de volle punten.",
    )
    values.update(overrides)
    return ExamDraft(**values)


def _generate(db, client, count=4, course_slug="fundamentals-of-ds"):
    return generate_cards(
        db, course_slug=course_slug, section_path=SECTION, count=count, kind="exam", client=client
    )


def test_a_course_without_a_mock_exam_gets_questions_for_its_own_assessment(db_session):
    """AFCS heeft geen proeftentamen. De vragen kregen dan de inleiding van FDS:
    'het schriftelijke tentamen Fundamentals of Data Science', met een
    proeftentamen 'onderaan' dat er niet stond."""
    from app.models import Course

    db_session.add(Course(slug="vak-zonder-proeftentamen", name="AFCS", study={"assessment": "vijf quizzen over de slides"}))
    document = _document(db_session, course_slug="vak-zonder-proeftentamen")
    client = _Client([_mc(document.chunks[0].id)])

    _generate(db_session, client, course_slug="vak-zonder-proeftentamen")

    instructions = client.calls[0]["instructions"]
    assert "vijf quizzen over de slides" in instructions
    assert "Fundamentals of Data Science" not in instructions
    assert "proeftentamen" not in instructions


def test_a_course_without_an_assessment_gets_a_neutral_intro(db_session, tmp_corpus):
    """Zonder `study.assessment` en zonder eigen stijl viel de generator terug
    op FDS: applied-ml kreeg vragen voor 'het schriftelijke tentamen
    Fundamentals of Data Science', en zo elk vak van wie de app met eigen
    vakken gebruikt."""
    from app.models import Course

    db_session.add(Course(slug="eigen-vak", name="Eigen vak"))
    document = _document(db_session, course_slug="eigen-vak")
    client = _Client([_mc(document.chunks[0].id)])

    _generate(db_session, client, course_slug="eigen-vak")

    instructions = client.calls[0]["instructions"]
    assert "het tentamen van dit vak" in instructions
    assert "Fundamentals of Data Science" not in instructions
    assert "proeftentamen" not in instructions


def test_a_grounded_choice_question_is_stored_as_an_exam_card(db_session):
    document = _document(db_session, week=3)
    client = _Client([_mc(document.chunks[0].id)])

    report = _generate(db_session, client)

    (card,) = report.created
    assert (card.kind, card.points, card.reference_answer, card.week) == ("mc", 1.5, "a", 3)
    assert card.spec["answer"] == [0]
    assert card.spec["material"] == "ISLRv2, p. 354"
    assert db_session.query(PracticeCard).count() == 1


def test_an_open_question_keeps_its_rubric(db_session):
    document = _document(db_session)
    client = _Client([_open(document.chunks[0].id)])

    (card,) = _generate(db_session, client).created

    assert card.kind == "open"
    assert [item["points"] for item in card.spec["rubric"]] == [2, 2]
    assert card.reference_answer.startswith("Both bag")


def test_a_wrong_chunk_id_with_a_real_quote_is_kept_and_reattributed(db_session):
    """Een verkeerde verwijzing is geen verzonnen vraag; de vindplaats volgt het citaat."""
    document = _document(db_session)
    draft = _mc("bestaat-niet")

    (card,) = _generate(db_session, _Client([draft])).created

    assert card.chunk_id == document.chunks[0].id


def test_a_quote_that_is_not_in_the_material_is_rejected(db_session):
    document = _document(db_session)
    verzonnen = _mc(document.chunks[0].id, source_quote="random forests always outperform boosting on tabular data")
    client = _Client([verzonnen], [])

    report = _generate(db_session, client)

    assert report.created == []
    assert report.rejected == [(verzonnen.question, "de source_quote staat niet letterlijk in het materiaal")]


def test_every_rubric_criterion_needs_its_own_quote(db_session):
    """Een schema dat punten geeft voor iets wat nergens in je stof staat,
    traint je op een antwoord dat de nakijker niet zoekt."""
    document = _document(db_session)
    draft = _open(document.chunks[0].id)
    draft.rubric[1].source_quote = "boosting grows trees sequentially using information from previous trees"

    report = _generate(db_session, _Client([draft], []))

    assert report.created == []
    assert "criterium 2" in report.rejected[0][1]


def test_the_rubric_must_add_up_to_the_points(db_session):
    document = _document(db_session)
    draft = _open(document.chunks[0].id, points=10.0)

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1] == "het schema telt op tot 4, de vraag is 10 punten"


def test_an_open_question_has_exam_points(db_session):
    document = _document(db_session)
    draft = _open(document.chunks[0].id, points=5.0)
    draft.rubric[0].points = 3

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1] == "een open vraag is 4, 6 of 10 punten, niet 5"


def test_a_computed_answer_must_land_on_the_marked_option(db_session):
    """Zoals in de conceptuitwerking: recall aangekruist waar de false negative rate gevraagd werd."""
    document = _document(db_session, text=TEKST + " The false negative rate is FN divided by FN plus TP.")
    draft = _mc(
        document.chunks[0].id, template="metric_compute_mc",
        question="TN = 2, FP = 6, FN = 1, TP = 5. What is the false negative rate?",
        options=["6/11", "5/6", "1/6", "5/11"], correct=["b"], compute="1 / (1 + 5)",
        explanation="Goed: b. Dit is de recall, want de noemer is het aantal echte positieven.",
        source_quote="The false negative rate is FN divided by FN plus TP",
    )

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1] == "compute geeft 0.166667; dat is c, maar als goed staat b"


def test_a_known_error_in_the_material_does_not_become_a_card(db_session):
    """PDSH schrijft [bottom, left, width, height]; matplotlib wil [left, bottom, …]."""
    tekst = TEKST + " These numbers represent [bottom, left, width, height] in the figure coordinate system."
    document = _document(db_session, text=tekst)
    draft = _mc(document.chunks[0].id, question="Which order does plt.axes expect for its rectangle? (one answer)",
                options=["[bottom, left, width, height]", "[left, right, top, bottom]", "[x, y]", "[width, height]"],
                source_quote="These numbers represent [bottom, left, width, height] in the figure coordinate system")

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1].startswith("neemt een bekende fout uit de stof over")


def test_a_computation_that_is_a_bare_number_is_rejected(db_session):
    """"De som is 12; wat is de within-cluster variation? → compute: 12"."""
    document = _document(db_session, text=TEKST + " The within-cluster variation is the sum of squared distances.")
    draft = _mc(document.chunks[0].id, template="metric_compute_mc",
                question="The sum of squared distances is 12. What is the within-cluster variation?",
                options=["12", "1.5", "8", "20"], correct=["a"], compute="12",
                source_quote="The within-cluster variation is the sum of squared distances",
                explanation="Goed: a. De within-cluster variation is hier de som van de gekwadrateerde afstanden.")

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1].startswith("compute is een kaal getal")


def test_a_computation_explanation_may_not_judge_the_distractors(db_session):
    """De afleiders worden niet nagerekend: "d is recall" terwijl recall b was."""
    document = _document(db_session, text=TEKST + " Precision is TP divided by TP plus FP.")
    draft = _mc(document.chunks[0].id, template="metric_compute_mc",
                question="TN = 18, FP = 2, FN = 5, TP = 15. What is the precision?",
                options=["15/17", "15/20", "18/23", "5/7"], correct=["a"], compute="15 / (15 + 2)",
                source_quote="Precision is TP divided by TP plus FP",
                explanation="Goed: a. Precision is 15/(15+2). Een veelgemaakte fout is d, want d is de recall van de klasse.")

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1].startswith("de uitleg zegt iets over afleider d")


def test_numeric_options_need_a_computation(db_session):
    document = _document(db_session)
    draft = _mc(document.chunks[0].id, options=["1/2", "1/3", "1/4", "1/5"], template="metric_compute_mc")

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1] == "alle opties zijn getallen, maar compute ontbreekt"


def test_a_choice_question_has_four_options(db_session):
    document = _document(db_session)
    draft = _mc(document.chunks[0].id, options=["one", "two", "three"])

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1] == "een meerkeuzevraag heeft vier opties, niet 3"


def test_a_question_the_repair_round_drops_keeps_its_reason(db_session):
    """Anders meldt het rapport "niets afgekeurd" terwijl er een vraag verdween."""
    document = _document(db_session)
    kapot = _mc(document.chunks[0].id, options=["one", "two", "three"])

    report = _generate(db_session, _Client([kapot], []))

    assert report.rejected == [(kapot.question, "een meerkeuzevraag heeft vier opties, niet 3")]


def test_an_explanation_that_contradicts_the_key_is_rejected(db_session):
    """Letterlijk wat de eerste echte ronde opleverde: a en b gemarkeerd, en in
    de uitleg 'b is waar, maar geen beperking'."""
    document = _document(db_session)
    draft = _mc(document.chunks[0].id, correct=["a", "b"], multi=True,
                question="Which are limitations of bagging? (Mark all correct answers)",
                explanation="Goed: a. Optie b is waar, maar het is geen beperking van de methode.")

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1] == "de uitleg noemt a als goed, maar correct is a, b"


def test_mark_all_is_only_for_questions_with_several_answers(db_session):
    """Op het tentamen betekent die zin: meer dan één goed."""
    document = _document(db_session)
    enkel = _mc(document.chunks[0].id, question="What distinguishes a random forest? (Mark all correct answers)")
    meervoud = _mc(document.chunks[0].id, question="Which statements are true?", correct=["a", "b"], multi=True,
                   explanation="Goed: a, b. Het zijn allebei ware uitspraken over de methode.")

    report = _generate(db_session, _Client([enkel, meervoud], []))

    assert [reden for _, reden in report.rejected] == [
        "de vraag zegt 'mark all correct answers', maar er is maar één goed antwoord",
        "er zijn meerdere goede antwoorden, maar de vraag zegt niet 'Mark all correct answers'",
    ]


def test_a_category_that_is_not_in_the_material_is_rejected(db_session):
    """Letterlijk uit de tweede echte ronde: random forests ingedeeld als
    'in-processing', de indeling van fairnessmethoden."""
    document = _document(db_session)
    draft = _mc(
        document.chunks[0].id, template="taxonomy_mc",
        question="At each split only a random subset of predictors is considered. Which category describes this step?",
        options=["Pre-processing", "In-processing", "Post-processing", "Data cleaning"],
        correct=["b"], explanation="Goed: b. Het gebeurt tijdens het leren van de bomen.",
    )

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1] == "de categorie in optie b komt nergens in het materiaal voor"


def test_a_computation_question_has_numbers_as_options(db_session):
    document = _document(db_session)
    draft = _mc(document.chunks[0].id, template="metric_compute_mc", options=["A", "B", "18/24", "6/24"])

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1] == "een rekenvraag heeft vier getallen als opties, zodat het antwoord na te rekenen is"


def test_an_explanation_that_talks_about_its_own_rubric_is_rejected(db_session):
    """Letterlijk uit een herstelronde: "The original rubric item about…"."""
    document = _document(db_session)
    draft = _mc(document.chunks[0].id, explanation="Goed: a. Het oorspronkelijke criterium over de split is aangepast, zodat het citaat klopt.")

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1].startswith("de uitleg praat over het maakproces")


def test_an_english_explanation_is_kept(db_session):
    """Een taalcontrole gooide in één sectie vijf goede vragen weg; het model
    schrijft de uitleg Engels als de vraag Engels is, en herstelt dat niet."""
    document = _document(db_session)
    draft = _mc(document.chunks[0].id, explanation="Goed: a. A random forest samples a subset of the predictors at each split.")

    report = _generate(db_session, _Client([draft], []))

    assert len(report.created) == 1


def test_an_explanation_must_state_the_answer_first(db_session):
    document = _document(db_session)
    draft = _mc(document.chunks[0].id, explanation="Bij bagging mag elke split alle predictoren gebruiken, en dat is het verschil met de random forest.")

    report = _generate(db_session, _Client([draft], []))

    assert report.rejected[0][1] == "de uitleg begint niet met 'Goed: ' en de letters van de goede opties"


@pytest.mark.parametrize(
    ("uitleg", "letters"),
    [("Goed: b, d. Rest.", ["b", "d"]), ("goed: c.", ["c"]), ("Goed: a en d — want", ["a", "d"]), ("Goed: B & D", ["b", "d"])],
)
def test_the_stated_letters_are_read_in_several_spellings(uitleg, letters):
    from app.services.practice.exam_generation import stated_letters

    assert stated_letters(uitleg) == letters


def test_a_rejected_question_gets_one_repair_round(db_session):
    document = _document(db_session)
    kapot = _mc(document.chunks[0].id, source_quote="random forests are always better")
    hersteld = _mc(document.chunks[0].id)
    client = _Client([kapot], [hersteld])

    report = _generate(db_session, client)

    assert len(report.created) == 1
    assert report.rejected == []
    assert "random forests are always better" in client.calls[1]["input"]
    # Het materiaal gaat mee: een citaat repareren kan alleen met de tekst ernaast.
    assert "decorrelates the trees" in client.calls[1]["input"]


def test_the_generator_sees_the_mock_exam(db_session, tmp_corpus):
    folder = tmp_corpus / "fundamentals-of-ds" / "exams"
    folder.mkdir(parents=True)
    (folder / "mock-exam-1.yml").write_text(yaml.safe_dump({
        "id": "mock-exam-1", "title": "Mock Exam 1", "course": "fundamentals-of-ds", "total_points": 10,
        "sections": [{"number": 3, "title": "Supervised", "questions": [{
            "id": "3i", "page": 7, "type": "open", "points": 10, "template": "distinguish",
            "question": "Please explain what distinguishes Random Forests from Bagging?",
            "model_answer": "Random forests decorrelate the trees.",
            "rubric": [{"criterion": "Decorrelation.", "points": 10}],
        }]}],
    }), encoding="utf-8")
    document = _document(db_session)
    client = _Client([_mc(document.chunks[0].id)])

    _generate(db_session, client)

    instructions = client.calls[0]["instructions"]
    assert "Please explain what distinguishes Random Forests from Bagging?" in instructions
    assert "schema (10 p): Decorrelation." in instructions


@pytest.mark.parametrize(
    "citaat",
    ["decorrelates the trees", "DECORRELATES   the\ntrees.", "decorre- lates the trees"],
)
def test_a_quote_is_found_through_pdf_line_breaks(citaat):
    assert grounded(citaat + " as in bagging", [squash(TEKST)])


def test_a_quote_too_short_to_prove_anything_is_not_grounded():
    assert not grounded("the trees", [squash(TEKST)])


def test_a_quote_is_found_through_pdf_ligatures():
    """PDF-tekst zet "fl" en "fi" als één teken (ﬂ, ﬁ). Op slide 40 van AFCS
    staat "inﬂuenced"; een voorbeeld met het letterlijke citaat werd drie keer
    afgekeurd, want squash gooide de ligatuur weg en hield "inuenced" over."""
    slide = "Seasonal pattern exists when a series is inﬂuenced by seasonal factors (e.g., the quarter of the year)"

    assert grounded("a series is influenced by seasonal factors", [squash(slide)])
    assert grounded("the classiﬁer is deﬁned by", [squash("The classifier is defined by its split rule.")])
