"""De generator raakt OpenAI niet, maar draait de sandbox wél echt: dat de
referentie-antwoorden uitvoerbaar zijn is de hele reden dat kaarten te
vertrouwen zijn."""
import pytest

from app.models import Chunk, Document, PracticeCard
from app.services.practice.generation import (
    CardDraft,
    numbers_in,
    NoSourceMaterial,
    StatsDraft,
    UnknownKind,
    generate_cards,
)


SECTION = "Chapter 2 › Array Slicing"


def _document(db, *, course="fundamentals-of-ds", section=SECTION, texts=("x2 is een 3x4 array",)):
    document = Document(
        title="PDSH", source_path=f"{course}/books/pdsh.pdf", checksum="0" * 64,
        course_slug=course, doc_kind="book", ingestion_status="indexed",
    )
    for index, text in enumerate(texts):
        document.chunks.append(Chunk(
            chunk_index=index, section_path=section, page_start=60 + index, page_end=60 + index,
            token_count=5, text=text, normalized_text=text.lower(), chunk_metadata={},
        ))
    db.add(document)
    db.commit()
    return document


class _FakeClient:
    """Bootst client.responses.parse na en registreert de prompt."""

    def __init__(self, drafts):
        self._drafts = drafts
        self.calls = []
        outer = self

        class _Responses:
            def parse(self, *, model, instructions, input, text_format):
                outer.calls.append({"model": model, "instructions": instructions, "input": input})
                # De soort bepaalt het schema; de nepclient volgt wat er gevraagd wordt.
                return type("Parsed", (), {"output_parsed": text_format(cards=outer._drafts)})()

        self.responses = _Responses()


def _draft(chunk_id, *, setup="x2 = np.arange(12).reshape(3, 4)",
           question="Wat is het gemiddelde per kolom?", answer="x2.mean(axis=0)"):
    return CardDraft(chunk_id=chunk_id, setup=setup, question=question, reference_answer=answer)


def test_a_working_card_is_stored_with_its_source(db_session):
    document = _document(db_session)
    chunk = document.chunks[0]
    client = _FakeClient([_draft(chunk.id)])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=client)

    assert len(report.created) == 1
    card = report.created[0]
    assert card.document_id == document.id
    assert card.chunk_id == chunk.id
    assert (card.page_start, card.page_end) == (60, 60)
    assert card.kind == "code"
    assert db_session.query(PracticeCard).count() == 1


def test_a_reference_answer_that_does_not_run_is_rejected(db_session):
    """Het model stelt voor, de interpreter beslist."""
    document = _document(db_session)
    client = _FakeClient([_draft(document.chunks[0].id, answer="x2.zzz()")])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=client)

    assert report.created == []
    assert "draait niet" in report.rejected[0][1]
    assert db_session.query(PracticeCard).count() == 0


def test_a_setup_that_does_more_than_build_a_fixture_is_rejected(db_session):
    document = _document(db_session)
    client = _FakeClient([_draft(document.chunks[0].id, setup="import os\nx2 = np.arange(4)")])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=client)

    assert report.created == []
    assert "opzet geweigerd" in report.rejected[0][1]


def test_a_card_citing_an_unoffered_chunk_is_rejected(db_session):
    _document(db_session)
    client = _FakeClient([_draft("verzonnen-id")])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=client)

    assert report.created == []
    assert "niet is aangeboden" in report.rejected[0][1]


def test_good_and_bad_cards_in_one_batch_are_separated(db_session):
    document = _document(db_session)
    chunk_id = document.chunks[0].id
    client = _FakeClient([
        _draft(chunk_id, question="Gemiddelde per kolom?", answer="x2.mean(axis=0)"),
        _draft(chunk_id, question="Onzin?", answer="x2.bestaatniet()"),
        _draft(chunk_id, question="Vorm?", answer="x2.shape"),
    ])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=client)

    assert [c.question for c in report.created] == ["Gemiddelde per kolom?", "Vorm?"]
    assert len(report.rejected) == 1


def test_a_duplicate_question_is_skipped(db_session):
    document = _document(db_session)
    chunk_id = document.chunks[0].id
    client = _FakeClient([_draft(chunk_id, question="Gemiddelde per kolom?")])
    generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=client)

    again = _FakeClient([_draft(chunk_id, question="gemiddelde per kolom?")])
    report = generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=again)

    assert report.created == []
    assert "bestaat al" in report.rejected[0][1]


def test_the_prompt_offers_the_section_text_with_chunk_ids(db_session):
    document = _document(db_session, texts=["eerste stuk", "tweede stuk"])
    client = _FakeClient([])

    generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, count=5, client=client)

    prompt = client.calls[0]["input"]
    assert "eerste stuk" in prompt and "tweede stuk" in prompt
    for chunk in document.chunks:
        assert f"chunk_id={chunk.id}" in prompt
    assert "Maak 5 oefenkaarten" in prompt


def test_a_section_without_text_is_a_clear_error(db_session):
    with pytest.raises(NoSourceMaterial, match="geen tekst"):
        generate_cards(db_session, course_slug="fundamentals-of-ds", section_path="bestaat niet",
                       client=_FakeClient([]))


def test_a_question_that_names_the_answer_is_rejected(db_session):
    """Vijf van de zes kaarten in de eerste echte ronde deden dit."""
    document = _document(db_session)
    client = _FakeClient([_draft(
        document.chunks[0].id,
        setup="x = np.array([2, 1, 4, 3, 5])",
        question="Wat geeft `np.sort(x)` terug zonder x te wijzigen?",
        answer="np.sort(x)",
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=client)

    assert report.created == []
    assert "noemt het antwoord: sort" in report.rejected[0][1]


def test_a_question_describing_the_goal_is_accepted(db_session):
    document = _document(db_session)
    client = _FakeClient([_draft(
        document.chunks[0].id,
        setup="x = np.array([2, 1, 4, 3, 5])",
        question="Hoe krijg je x oplopend gesorteerd, zonder x zelf te wijzigen?",
        answer="np.sort(x)",
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=client)

    assert len(report.created) == 1


def test_the_fixture_name_in_the_question_is_fine(db_session):
    document = _document(db_session)
    client = _FakeClient([_draft(
        document.chunks[0].id,
        setup="x = np.arange(5)\ni = np.argsort(x)",
        question="Welke array krijg je als je i gebruikt om x te indexeren?",
        answer="x[i]",
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=client)

    assert len(report.created) == 1


def test_a_card_whose_answer_does_nothing_is_rejected(db_session):
    """`None` als antwoord zou elk None-opleverend antwoord goed rekenen."""
    document = _document(db_session)
    client = _FakeClient([_draft(
        document.chunks[0].id, setup="v = np.array([3, 1, 2])",
        question="Wat levert dit op?", answer="None",
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=client)

    assert report.created == []
    assert "levert niets op" in report.rejected[0][1]


def test_an_in_place_card_is_kept(db_session):
    """`v.sort()` geeft None terug maar verandert de fixture: dat is toetsbaar."""
    document = _document(db_session)
    client = _FakeClient([_draft(
        document.chunks[0].id, setup="v = np.array([3, 1, 2])",
        question="Hoe pas je v zelf aan zodat de waarden oplopend staan?", answer="v.sort()",
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=client)

    assert len(report.created) == 1


# --- toetskaarten -----------------------------------------------------------

STATS_SETUP = "n = 40\nxbar = 12.3\nmu = 11.0\ns = 2.1"
STATS_QUESTION = (
    "Een steekproef van 40 metingen heeft gemiddelde 12,3 en standaardafwijking 2,1. "
    "Toets tweezijdig op niveau 0,05 of het populatiegemiddelde afwijkt van 11,0. "
    "Geef de waarde van de toetsingsgrootheid."
)
STATS_EXPLANATION = "H0: mu = 11,0 tegen H1: mu != 11,0. $t = (12{,}3-11{,}0)/(2{,}1/\\sqrt{40}) = 3{,}92$."


def _stats_draft(chunk_id, *, setup=STATS_SETUP, question=STATS_QUESTION,
                 answer="(xbar - mu) / (s / np.sqrt(n))", explanation=STATS_EXPLANATION,
                 computed_value=3.92):
    return StatsDraft(chunk_id=chunk_id, setup=setup, question=question,
                      reference_answer=answer, explanation=explanation,
                      computed_value=computed_value)


def test_a_stats_card_keeps_its_worked_solution(db_session):
    document = _document(db_session, texts=("t-toets voor één steekproef",))
    client = _FakeClient([_stats_draft(document.chunks[0].id)])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert len(report.created) == 1
    card = report.created[0]
    assert card.kind == "stats"
    assert card.explanation == STATS_EXPLANATION


def test_a_stats_card_without_a_worked_solution_is_rejected(db_session):
    """Het getal alleen leert je niets; de uitwerking is de kaart."""
    document = _document(db_session, texts=("t-toets",))
    client = _FakeClient([_stats_draft(document.chunks[0].id, explanation="  ")])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert report.created == []
    assert "uitwerking" in report.rejected[0][1]


def test_a_stats_answer_that_is_not_a_number_is_rejected(db_session):
    """Op een tentamen schrijf je één getal op, geen array."""
    document = _document(db_session, texts=("t-toets",))
    client = _FakeClient([_stats_draft(
        document.chunks[0].id, answer="np.array([1.0, 2.0])",
        explanation="De uitkomst is $(1{,}0;\\,2{,}0)$.", computed_value=1.0,
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert report.created == []
    assert "geen getal" in report.rejected[0][1]


def test_scipy_is_available_to_a_stats_card(db_session):
    document = _document(db_session, texts=("kritieke waarde",))
    client = _FakeClient([_stats_draft(
        document.chunks[0].id,
        question="Wat is de bovengrens van het kritieke gebied bij 39 vrijheidsgraden en 0,025 in de staart?",
        answer="stats.t.ppf(0.975, df=39)",
        explanation="Bij 39 vrijheidsgraden is $t_{0{,}975}=2{,}023$.",
        computed_value=2.0227,
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert report.rejected == []
    assert len(report.created) == 1


def test_a_stats_question_may_say_p_waarde(db_session):
    """`stats.binomtest(k=.., n=.., p=..)` mag geen elke vraag met "p-waarde" afkeuren."""
    document = _document(db_session, texts=("binomiaaltoets",))
    client = _FakeClient([_stats_draft(
        document.chunks[0].id,
        setup="",
        question="Van 40 worpen vielen er 26 op kop. Geef de eenzijdige p-waarde bij een eerlijke munt.",
        answer="stats.binomtest(k=26, n=40, p=0.5, alternative='greater').pvalue",
        explanation="Onder $H_0$ is $K\\sim\\text{Bin}(40;0{,}5)$, dus $p=P(K\\ge 26)=0{,}0403$.",
        computed_value=0.0403,
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert report.rejected == []


def test_an_unknown_kind_is_refused(db_session):
    _document(db_session)

    with pytest.raises(UnknownKind):
        generate_cards(db_session, course_slug="fundamentals-of-ds",
                       section_path=SECTION, kind="onzin", client=_FakeClient([]))


def test_an_explanation_that_contradicts_the_marked_answer_is_rejected(db_session):
    """Vier van de negen uitwerkingen in de eerste echte ronde deden dit:
    2,36 opschrijven waar de uitdrukking 2,223 geeft."""
    document = _document(db_session, texts=("t-toets",))
    client = _FakeClient([_stats_draft(
        document.chunks[0].id,
        explanation="H0: mu = 11,0. $t = 2{,}36$.",
        computed_value=2.36,
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert report.created == []
    assert "komt uit op 2.36" in report.rejected[0][1]


def test_an_outcome_missing_from_the_worked_solution_is_rejected(db_session):
    """De uitkomst klopt, maar de uitwerking noemt hem nergens: dan kun je niet
    nagaan waar het getal vandaan komt."""
    document = _document(db_session, texts=("t-toets",))
    client = _FakeClient([_stats_draft(
        document.chunks[0].id,
        explanation="H0: mu = 11,0 tegen H1: mu != 11,0. Vul de formule in.",
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert report.created == []
    assert "staat nergens in de uitwerking" in report.rejected[0][1]


def test_an_answer_that_is_already_in_the_setup_is_rejected(db_session):
    """`x` als antwoord terwijl de opzet `x = 18` zegt, is geen opgave."""
    document = _document(db_session, texts=("tekentoets",))
    client = _FakeClient([_stats_draft(
        document.chunks[0].id, setup="x = 18\nn = 40", answer="x",
        explanation="De toetsingsgrootheid is $T=18$.", computed_value=18.0,
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert report.created == []
    assert "rekent niets uit" in report.rejected[0][1]


def test_numbers_are_read_with_both_a_comma_and_a_point():
    """LaTeX zet een decimaalkomma als `{,}`, de lopende tekst als `,`."""
    gevonden = numbers_in("$t = 2{,}36$ tegenover 2,36 en 2.36 en -0,30")

    assert 2.36 in gevonden
    assert gevonden.count(2.36) == 3
    assert -0.30 in gevonden


class _TwoRoundClient:
    """Eerste aanroep levert de kapotte kaart, de tweede de verbeterde."""

    def __init__(self, first, second):
        self._rounds = [first, second]
        self.calls = []
        outer = self

        class _Responses:
            def parse(self, *, model, instructions, input, text_format):
                outer.calls.append({"instructions": instructions, "input": input})
                return type("Parsed", (), {"output_parsed": text_format(cards=outer._rounds.pop(0))})()

        self.responses = _Responses()


def test_a_miscalculated_card_gets_one_repair_round(db_session):
    """De interpreter kent het goede getal; dat gaat terug naar het model in
    plaats van dat de kaart wordt weggegooid."""
    document = _document(db_session, texts=("t-toets",))
    kapot = _stats_draft(document.chunks[0].id, explanation="$t = 2{,}36$.", computed_value=2.36)
    goed = _stats_draft(document.chunks[0].id)
    client = _TwoRoundClient([kapot], [goed])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert [card.explanation for card in report.created] == [STATS_EXPLANATION]
    assert report.rejected == []
    # De herstelronde krijgt de uitgerekende waarde mee, niet alleen de kaart.
    assert "3.9152" in client.calls[1]["input"]


def test_a_card_that_stays_wrong_after_the_repair_round_is_dropped(db_session):
    document = _document(db_session, texts=("t-toets",))
    kapot = _stats_draft(document.chunks[0].id, explanation="$t = 2{,}36$.", computed_value=2.36)
    client = _TwoRoundClient([kapot], [kapot])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert report.created == []
    assert len(report.rejected) == 1


def test_a_healthy_batch_needs_no_second_call(db_session):
    document = _document(db_session, texts=("t-toets",))
    client = _FakeClient([_stats_draft(document.chunks[0].id)])

    generate_cards(db_session, course_slug="fundamentals-of-ds",
                   section_path=SECTION, kind="stats", client=client)

    assert len(client.calls) == 1


def test_an_explanation_that_quotes_the_code_is_rejected(db_session):
    """De herstelronde verleidde het model ertoe de uitkomst te citeren in plaats
    van hem af te leiden: "maar de gegeven uitdrukking geeft 75,5"."""
    document = _document(db_session, texts=("t-toets",))
    client = _FakeClient([_stats_draft(
        document.chunks[0].id,
        explanation="Met de hand kom ik op 3,5, maar de gegeven uitdrukking geeft $3{,}92$.",
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert report.created == []
    assert "wijst naar de code" in report.rejected[0][1]


def test_the_name_of_a_test_is_not_a_giveaway(db_session):
    """`.sum()` in het antwoord mocht "Wilcoxon rank-sum-toets" niet afkeuren:
    die toets moet je juist bij naam noemen."""
    document = _document(db_session, texts=("Wilcoxon rank-sum",))
    client = _FakeClient([_stats_draft(
        document.chunks[0].id,
        setup="x = np.array([3.1, 4.2, 5.5, 6.1])\ny = np.array([2.0, 2.8, 3.3, 4.9])",
        question=(
            "Twee onafhankelijke steekproeven van vier waarnemingen worden vergeleken. "
            "Toets tweezijdig op niveau 0,05 met de Wilcoxon rank-sum-toets en geef de rangsom "
            "van de eerste steekproef."
        ),
        answer="stats.rankdata(np.concatenate([x, y]))[:len(x)].sum()",
        explanation="De rangen van de eerste steekproef zijn $3,5,7,8$, dus de rangsom is $23$.",
        computed_value=23.0,
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert report.rejected == []
    assert len(report.created) == 1


def test_an_answer_equal_to_a_setup_value_is_rejected(db_session):
    """`np.sum([1]*T)` ontwijkt de controle op de vórm van de uitdrukking maar
    geeft nog steeds gewoon T terug."""
    document = _document(db_session, texts=("tekentoets",))
    client = _FakeClient([_stats_draft(
        document.chunks[0].id, setup="n = 15\nT = 11", answer="np.sum([1]*T)",
        explanation="Het aantal positieve verschillen is $11$.", computed_value=11.0,
    )])

    report = generate_cards(db_session, course_slug="fundamentals-of-ds",
                            section_path=SECTION, kind="stats", client=client)

    assert report.created == []
    assert "gelijk aan 'T' uit de opzet" in report.rejected[0][1]


def test_the_prompt_lists_the_questions_already_in_the_deck(db_session):
    """Anders levert "Meer kaarten" vooral dezelfde toets nog een keer."""
    document = _document(db_session)
    client = _FakeClient([_draft(document.chunks[0].id)])
    generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=client)

    tweede = _FakeClient([_draft(document.chunks[0].id, question="Iets anders?", answer="x2.sum()")])
    generate_cards(db_session, course_slug="fundamentals-of-ds", section_path=SECTION, client=tweede)

    assert "Wat is het gemiddelde per kolom?" in tweede.calls[0]["input"]
