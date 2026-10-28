"""Keuzekaarten: welke toets hoort bij dit verhaal, en wat moet je controleren.

Dit is de kaartsoort die het dichtst bij het tentamen van SSO ligt — dat vraagt
geen R-code maar de keuze van de juiste procedure. Rohrer e.a. (2020) lieten
zien dat juist die keuze het is die je mist als je per college oefent.

De keuring is mechanisch, zoals overal: een kaart waarvan de uitleg de eigen
sleutel tegenspreekt, of waarvan de vraag het antwoord al noemt, gaat weg
voordat je hem ziet.
"""
import pytest

from app.models import Chunk, Document, PracticeCard
from app.services.practice.choice_generation import ChoiceDraft, check_choice_draft
from app.services.practice.exam_generation import squash
from app.services.practice.generation import generate_cards


SECTION = "Lecture 3"
TEKST = (
    "The Wilcoxon signed-rank test is a nonparametric test for matched pairs. "
    "It replaces the paired t-test when the differences are not normally distributed."
)
# Zoals de generator het aanlevert: zonder spaties en leestekens, want
# PDF-tekst breekt woorden af.
STOF = [squash(TEKST)]


def _document(db, *, course="sso", texts=(TEKST,)):
    document = Document(
        title="Lecture 3", source_path=f"{course}/slides/week-02/lecture3.pdf", checksum="1" * 64,
        course_slug=course, doc_kind="slides", week=2, ingestion_status="indexed",
    )
    for index, text in enumerate(texts):
        document.chunks.append(
            Chunk(
                chunk_index=index, section_path=SECTION, page_start=10 + index, page_end=10 + index,
                token_count=20, text=text, normalized_text=text.lower(), chunk_metadata={},
            )
        )
    db.add(document)
    db.commit()
    return document


class _FakeClient:
    def __init__(self, drafts):
        self._drafts = drafts
        self.calls = []
        outer = self

        class _Responses:
            def parse(self, *, model, instructions, input, text_format):
                outer.calls.append({"instructions": instructions, "input": input})
                return type("Parsed", (), {"output_parsed": text_format(cards=outer._drafts)})()

        self.responses = _Responses()


def _draft(chunk_id, **overrides):
    velden = dict(
        chunk_id=chunk_id,
        question=(
            "Bij twaalf proefpersonen wordt de reactietijd vóór en na een training gemeten. "
            "De verschillen zijn duidelijk scheef verdeeld. Welke toets past hier?"
        ),
        options=[
            "Wilcoxon signed-rank test",
            "Tweesteekproeven t-toets",
            "Chi-kwadraattoets voor onafhankelijkheid",
            "Eensteekproefs z-toets voor een proportie",
        ],
        correct="a",
        procedure="Wilcoxon signed-rank test",
        checks=["de paren horen bij elkaar", "de verschillen hoeven niet normaal te zijn"],
        explanation=(
            "Goed: a. Het zijn gepaarde metingen, dus je werkt met de verschillen; die zijn scheef, "
            "dus de gepaarde t-toets valt af en je gebruikt de Wilcoxon signed-rank test."
        ),
        source_quote="nonparametric test for matched pairs",
    )
    velden.update(overrides)
    return ChoiceDraft(**velden)


def test_a_good_draft_becomes_a_multiple_choice_card(db_session):
    document = _document(db_session)
    chunk = document.chunks[0]

    report = generate_cards(
        db_session, course_slug="sso", section_path=SECTION, kind="keuze", client=_FakeClient([_draft(chunk.id)])
    )

    assert report.rejected == []
    card = report.created[0]
    assert card.kind == "mc"
    assert card.spec["answer"] == [0]
    assert card.spec["multi"] is False
    assert card.spec["procedure"] == "Wilcoxon signed-rank test"
    assert card.spec["checks"] == ["de paren horen bij elkaar", "de verschillen hoeven niet normaal te zijn"]
    assert card.origin is None  # geen tentamenkaart: hij mag meteen in de herhaling
    assert card.week == 2  # van het document, zodat het weekoverzicht hem ziet
    assert db_session.query(PracticeCard).count() == 1


def test_the_question_may_not_name_the_answer(db_session):
    """Anders lees je het antwoord op uit de vraag; dat is overtypen."""
    reden = check_choice_draft(
        _draft("c", question="Welke toets hoort bij de Wilcoxon signed-rank test-situatie?"),
        material=STOF,
        seen=set(),
    )

    assert reden is not None and "noemt" in reden


def test_the_explanation_must_agree_with_the_key(db_session):
    reden = check_choice_draft(
        _draft("c", explanation="Goed: c. De chi-kwadraattoets past bij een kruistabel."),
        material=STOF,
        seen=set(),
    )

    assert reden is not None and "uitleg" in reden


def test_the_named_procedure_must_be_the_correct_option(db_session):
    """De procedure is het label waarop de ronde afwisselt. Klopt hij niet met
    de sleutel, dan zet hij twee kaarten over dezelfde toets alsnog naast
    elkaar — precies wat we willen voorkomen."""
    reden = check_choice_draft(
        _draft("c", procedure="Tweesteekproeven t-toets"),
        material=STOF,
        seen=set(),
    )

    assert reden is not None and "procedure" in reden


def test_options_must_be_four_and_distinct(db_session):
    kort = check_choice_draft(_draft("c", options=["a", "b"]), material=STOF, seen=set())
    dubbel = check_choice_draft(
        _draft("c", options=["Wilcoxon signed-rank test", "Wilcoxon signed-rank test", "z-toets", "F-toets"]),
        material=STOF,
        seen=set(),
    )

    assert kort is not None and "vier" in kort
    assert dubbel is not None and "gelijk" in dubbel


def test_a_card_without_checks_is_refused(db_session):
    """'Wat moet je controleren' is de helft van de vraag op het tentamen."""
    reden = check_choice_draft(_draft("c", checks=[]), material=STOF, seen=set())

    assert reden is not None and "controle" in reden


def test_the_card_must_rest_on_the_material(db_session):
    reden = check_choice_draft(
        _draft("c", source_quote="een zin die nergens in de stof staat"),
        material=STOF,
        seen=set(),
    )

    assert reden is not None and "citaat" in reden


def test_a_question_that_already_exists_is_skipped(db_session):
    draft = _draft("c")
    reden = check_choice_draft(draft, material=STOF, seen={draft.question.lower()})

    assert reden is not None and "bestaat" in reden


def test_two_ways_of_asking_the_same_thing_is_one_card(db_session):
    """Vier kaarten per onderwerp over een smal onderwerp leverde twee keer
    'welke toets voor parallelle hellingen' op. Woordelijk verschillend, maar
    als oefening dezelfde kaart — en dan herhaal je één ding twee keer."""
    eerste = _draft(
        "c",
        question="In een model met een factor en een covariaat: zijn de regressielijnen per groep parallel?",
        procedure="ANCOVA: equal slopes",
        options=["ANCOVA: equal slopes", "ANCOVA: factor effect", "one-way ANOVA", "two-way ANOVA"],
        explanation="Goed: a. Het gaat om gelijke hellingen.",
    )
    tweede = _draft(
        "c",
        question="Een onderzoeker wil nagaan of de regressielijnen per groep parallel zijn in een model met een factor en een covariaat.",
        procedure="ANCOVA: equal slopes",
        options=["ANCOVA: equal slopes", "ANCOVA: factor effect", "one-way ANOVA", "two-way ANOVA"],
        explanation="Goed: a. Het gaat om gelijke hellingen.",
    )

    reden = check_choice_draft(
        tweede, material=STOF, seen=set(), earlier=[(eerste.question, eerste.procedure)]
    )

    assert reden is not None and "vraagt hetzelfde" in reden


def test_the_same_procedure_in_a_different_situation_is_allowed(db_session):
    """Dezelfde toets bij een ander verhaal is juist waardevol: dat is precies
    wat je moet herkennen."""
    eerste = _draft(
        "c",
        question="Zijn de regressielijnen per groep parallel in een model met factor en covariaat?",
        procedure="ANCOVA: equal slopes",
        options=["ANCOVA: equal slopes", "ANCOVA: factor effect", "one-way ANOVA", "two-way ANOVA"],
        explanation="Goed: a. Het gaat om gelijke hellingen.",
    )
    tweede = _draft(
        "c",
        question="Bij een proef met drie soorten kunstmest en de gemeten hoeveelheid neerslag als covariaat wil men weten of het effect van neerslag per soort verschilt.",
        procedure="ANCOVA: equal slopes",
        options=["ANCOVA: equal slopes", "ANCOVA: factor effect", "one-way ANOVA", "two-way ANOVA"],
        explanation="Goed: a. Het effect per groep mag verschillen.",
    )

    reden = check_choice_draft(
        tweede, material=STOF, seen=set(), earlier=[(eerste.question, eerste.procedure)]
    )

    assert reden is None


def test_the_procedure_may_be_written_a_little_differently(db_session):
    """Het model schreef 'generalized additive model met smoothing' bij de optie
    'GAM (generalized additive model)'. Dat wijst dezelfde toets aan; woordelijk
    gelijk eisen kostte een heel onderwerp aan kaarten."""
    reden = check_choice_draft(
        _draft(
            "c",
            options=["Wilcoxon signed-rank test voor gepaarde metingen", "t-toets", "chi-kwadraat", "F-toets"],
            procedure="Wilcoxon signed-rank test",
            correct="a",
            explanation="Goed: a. Gepaarde metingen met scheve verschillen.",
            question="Twaalf mensen worden twee keer gemeten; de verschillen zijn scheef. Wat doe je?",
        ),
        material=STOF,
        seen=set(),
    )

    assert reden is None


def test_a_procedure_that_points_at_another_option_is_still_refused(db_session):
    reden = check_choice_draft(_draft("c", procedure="Chi-kwadraattoets voor onafhankelijkheid"), material=STOF, seen=set())

    assert reden is not None and "procedure" in reden
