from app.schemas import QueryChunkResult
from app.services.answering import (
    AnsweringService,
    combine_confidence,
    ensure_inline_citation_markers,
    evidence_confidence,
)


def _chunk(
    chunk_id: str,
    score: float = 0.8,
    text: str = "Backpropagation past de kettingregel toe.",
    document_id: str = "doc-1",
) -> QueryChunkResult:
    return QueryChunkResult(
        chunk_id=chunk_id,
        document_id=document_id,
        document_title="Bishop PRML",
        source_path="dl/books/bishop.pdf",
        course_slug="dl",
        doc_kind="book",
        week=None,
        assignment_status=None,
        section_path="5 Neural Networks › 5.3 Error Backpropagation",
        page_start=241,
        page_end=242,
        score=score,
        text=text,
        chunk_metadata={},
    )


def test_no_evidence_gives_low_confidence():
    bucket, reasons = evidence_confidence([], provider="openai", min_score=0.2)

    assert bucket == "low"
    assert reasons


def test_strong_agreeing_evidence_gives_high_confidence():
    chunks = [
        _chunk("a", 0.85, document_id="doc-1"),
        _chunk("b", 0.82, document_id="doc-2"),
        _chunk("c", 0.80, document_id="doc-2"),
    ]

    bucket, _reasons = evidence_confidence(chunks, provider="openai", min_score=0.2)

    assert bucket == "high"


def test_weak_evidence_gives_low_confidence():
    bucket, _reasons = evidence_confidence([_chunk("a", 0.05)], provider="openai", min_score=0.2)

    assert bucket == "low"


def test_scores_are_ignored_for_the_local_hash_provider():
    """Hash-embeddings leveren scores die niet met de drempel te vergelijken zijn."""
    chunks = [_chunk("a", 0.01), _chunk("b", 0.01)]

    bucket, reasons = evidence_confidence(chunks, provider="local-hash", min_score=0.2)

    assert bucket != "low"
    assert any("local-hash" in reason for reason in reasons)


def test_combine_takes_the_lower_bucket():
    assert combine_confidence("high", "low") == "low"
    assert combine_confidence("medium", "high") == "medium"


def test_inline_markers_are_appended_when_the_model_forgot_them():
    result = ensure_inline_citation_markers("Backprop werkt via de kettingregel.", 2)

    assert "[1]" in result


def test_existing_markers_are_left_alone():
    original = "Backprop werkt via de kettingregel [1]."

    assert ensure_inline_citation_markers(original, 1) == original


def test_no_citations_means_no_markers():
    assert ensure_inline_citation_markers("Geen bewijs.", 0) == "Geen bewijs."


class _FakeRetrieval:
    def __init__(self, results):
        self._results = results
        self.calls = []

    def search(self, question, top_k, filters=None, mode="hybrid"):
        self.calls.append((question, top_k, filters, mode))
        return "local-hash", list(self._results)


def _service(results, client=None) -> AnsweringService:
    service = AnsweringService.__new__(AnsweringService)
    service.retrieval_service = _FakeRetrieval(results)
    service.client = client
    service.model = "test-model"
    return service


def test_empty_retrieval_abstains():
    service = _service([])

    response = service.compose(
        question="Wat is de ELBO?",
        retrieval_query=None,
        top_k=5,
        filters=None,
        mode="hybrid",
        style="explain",
    )

    assert response.abstained is True
    assert response.confidence == "low"
    assert response.citations == []
    assert "materiaal" in response.answer.lower()


def test_fallback_answer_without_a_model_cites_retrieved_chunks():
    service = _service([_chunk("a"), _chunk("b")])

    response = service.compose(
        question="Wat is backprop?",
        retrieval_query=None,
        top_k=5,
        filters=None,
        mode="hybrid",
        style="short",
    )

    assert response.abstained is False
    assert response.answer_model == "local-extractive"
    assert [citation.chunk_id for citation in response.citations] == ["a", "b"]
    assert response.citations[0].section_path.endswith("5.3 Error Backpropagation")


def test_retrieval_uses_the_rewritten_query_when_given():
    service = _service([_chunk("a")])

    service.compose(
        question="En waarom werkt dat?",
        retrieval_query="waarom werkt backpropagation",
        top_k=5,
        filters=None,
        mode="hybrid",
        style="explain",
    )

    assert service.retrieval_service.calls[0][0] == "waarom werkt backpropagation"


def test_citations_pointing_at_unknown_chunks_are_dropped():
    """De invariant die niet mag sneuvelen: nooit een bron verzinnen."""
    service = _service([_chunk("a")])

    kept = service._citation_records(
        draft_citations=[("a", "kettingregel"), ("verzonnen-id", "iets")],
        retrieved={"a": _chunk("a")},
    )

    assert [citation.chunk_id for citation in kept] == ["a"]


def test_normalize_answer_text_turns_escaped_newlines_into_real_ones():
    """Het model schrijft `\\n` in plaats van een witregel; dat is zichtbare rommel."""
    from app.services.answering import normalize_answer_text

    tekst = r"dan geldt:\n\n\[\n\mathrm{Var} = 1.\n\]\n\nDit betekent"

    hersteld = normalize_answer_text(tekst)

    assert "\\n" not in hersteld
    assert hersteld.count("\n") == 6
    assert hersteld.startswith("dan geldt:\n\n\\[")
    assert "\\mathrm{Var}" in hersteld


def test_normalize_answer_text_leaves_latex_commands_intact():
    """`\\nabla`, `\\neq` en `\\times` beginnen met dezelfde tekens als een escape."""
    from app.services.answering import normalize_answer_text

    tekst = r"\nabla f \neq 0 en \nu \times \tau, \theta"

    assert normalize_answer_text(tekst) == tekst


def test_normalize_answer_text_is_a_noop_without_backslashes():
    from app.services.answering import normalize_answer_text

    assert normalize_answer_text("gewoon een zin") == "gewoon een zin"


def test_build_instructions_carries_style_and_math_notation():
    from app.services.answering import build_instructions

    kort = build_instructions("short")

    assert "hooguit vijf zinnen" in kort
    assert "$...$" in kort
    assert "[1], [2]" in kort


def test_build_instructions_falls_back_to_explain_for_unknown_style():
    from app.services.answering import build_instructions

    assert "voor het eerst ziet" in build_instructions("onbekend")


def test_build_instructions_names_no_programme():
    """Wie de app met eigen vakken gebruikt, studeert niet per se een master
    datascience."""
    from app.services.answering import build_instructions

    assert "datascience" not in build_instructions("explain").lower().replace(" ", "")


def test_json_parsing_mangles_single_escaped_latex_and_we_restore_it():
    """`\\beta` in een JSON-string wordt een backspace plus "eta".

    Het teken is onzichtbaar, dus in de UI stond er "$eta_j$" zonder dat er iets
    van een fout te zien was. Juist b, f, n, r en t zijn geldige JSON-escapes én
    de eerste letter van de commando's die in statistiek het meest voorkomen.
    """
    import json

    from app.services.answering import normalize_answer_text

    for latex in [r"\beta_j", r"\frac{a}{b}", r"\rho", r"\theta", r"\nabla"]:
        gesloopt = json.loads('"' + latex + '"')
        assert any(ord(char) < 32 for char in gesloopt), "test zelf klopt niet"
        assert normalize_answer_text(gesloopt) == latex


def test_a_real_newline_before_a_word_stays_a_newline():
    """"\\n" gevolgd door "ote that" is een regelovergang, geen `\\not`."""
    from app.services.answering import normalize_answer_text

    assert normalize_answer_text("regel een\note that dit doorloopt") == (
        "regel een\note that dit doorloopt"
    )


def test_stray_backspace_is_dropped():
    from app.services.answering import normalize_answer_text

    assert "\x08" not in normalize_answer_text("tekst met \x08 los teken")


def _evidence_chunk(chunk_id: str, text: str = "bewijstekst"):
    from app.schemas import QueryChunkResult

    return QueryChunkResult(
        chunk_id=chunk_id, document_id="doc", document_title="Boek", source_path="p.pdf",
        course_slug="sso", doc_kind="book", page_start=1, page_end=1, score=0.5, text=text,
    )


def test_inline_markers_are_renumbered_to_the_citation_list():
    """De prompt nummert al het bewijs; de citatielijst is een deelverzameling.

    Zonder hernummeren verwijst het antwoord naar een "[7]" die in het
    bronpaneel niet bestaat.
    """
    from app.services.answering import AnsweringService

    chunks = [_evidence_chunk(f"c{index}") for index in range(1, 9)]
    service = AnsweringService.__new__(AnsweringService)

    answer, citations = service.aligned_citations(
        answer="Eerst dit [2]. Daarna dat [7].",
        chunks=chunks,
        draft_citations=[("c2", "steun uit twee")],
    )

    assert [c.chunk_id for c in citations] == ["c2", "c7"]
    assert answer == "Eerst dit [1]. Daarna dat [2]."


def test_a_marker_the_model_invented_is_dropped():
    """Bewijs [9] bestaat niet als er drie fragmenten zijn aangeboden."""
    from app.services.answering import AnsweringService

    chunks = [_evidence_chunk(f"c{index}") for index in range(1, 4)]
    service = AnsweringService.__new__(AnsweringService)

    answer, citations = service.aligned_citations(
        answer="Een bewering [1], en een verzonnen bron [9].",
        chunks=chunks,
        draft_citations=[("c1", "steun")],
    )

    assert [c.chunk_id for c in citations] == ["c1"]
    assert "[9]" not in answer
    assert answer == "Een bewering [1], en een verzonnen bron."


def test_evidence_cited_only_inline_still_becomes_a_source():
    """Het model schrijft "[3]" zonder fragment 3 in zijn citatielijst te zetten."""
    from app.services.answering import AnsweringService

    chunks = [_evidence_chunk(f"c{index}") for index in range(1, 5)]
    service = AnsweringService.__new__(AnsweringService)

    _, citations = service.aligned_citations(
        answer="Zie hier [3].", chunks=chunks, draft_citations=[]
    )

    assert [c.chunk_id for c in citations] == ["c3"]


def test_instructions_ask_for_the_language_of_the_question():
    """Het materiaal is Engels; een Nederlandse vraag hoort een Nederlands antwoord."""
    from app.services.answering import build_instructions

    assert "taal van de vraag" in build_instructions("explain")


def test_instructions_carry_the_coach_policy():
    from app.services.answering import build_instructions

    plain = build_instructions("explain")
    coached = build_instructions("explain", coach_policy="Geef nooit het eindantwoord.")

    assert "Geef nooit het eindantwoord." not in plain
    assert "Geef nooit het eindantwoord." in coached


def test_prompt_pins_the_assignment_under_its_own_heading():
    from app.services.answering import AnsweringService

    service = AnsweringService.__new__(AnsweringService)
    pinned = [_evidence_chunk("p1", text="Opgave 1: bereken de variantie")]
    evidence = [_evidence_chunk("c1", text="De variantie is E[(X-mu)^2]")]

    prompt = service._build_prompt(question="hoe begin ik?", chunks=evidence, pinned=pinned)

    assert prompt.index("Opdracht") < prompt.index("[1]")
    assert "Opgave 1: bereken de variantie" in prompt
    # De opdracht is geen bron: hij krijgt geen [n] en geen chunk_id-regel.
    assert "chunk_id=p1" not in prompt
    assert "chunk_id=c1" in prompt


def test_compose_from_chunks_without_a_model_echoes_the_coach():
    from app.schemas import CoachEcho
    from app.services.answering import AnsweringService
    from app.services.coach import CoachContext

    service = AnsweringService.__new__(AnsweringService)
    service.client = None
    service.model = "none"
    echo = CoachEcho(document_id="d", document_title="Opdracht 1", policy="hints")
    coach = CoachContext("d", "Opdracht 1", "assignment", "hints", pinned=[], echo=echo)

    response = service.compose_from_chunks(
        question="v", retrieval_query=None, chunks=[_evidence_chunk("c1")], provider="local-hash", coach=coach
    )

    assert response.coach == echo


def test_auto_language_tells_the_model_to_ignore_the_instruction_language():
    """De oude tekst zei alleen "taal van de vraag"; het model volgde toch de
    Nederlandse instructie en antwoordde Nederlands op een Engelse vraag."""
    from app.services.answering import build_instructions

    auto = build_instructions("explain", language="auto")

    assert "taal van de vraag" in auto
    assert "niet in die van deze instructie" in auto


def test_language_can_be_pinned():
    from app.services.answering import build_instructions

    assert "in het Nederlands" in build_instructions("explain", language="nl")
    assert "in English" in build_instructions("explain", language="en")
    # Een onbekende waarde valt terug op automatisch in plaats van de regel weg te laten.
    assert "taal van de vraag" in build_instructions("explain", language="klingon")


def test_instructions_ask_to_keep_the_distinction_the_source_makes():
    """De slide zei "exact bij een normale populatie, anders bij benadering";
    het antwoord maakte daar één "ongeveer normaal" van."""
    from app.services.answering import build_instructions

    instructions = build_instructions("explain")

    assert "wanneer het geldt" in instructions
    assert "exact versus bij benadering" in instructions


def test_notation_stays_in_the_language_of_the_material_whatever_the_answer_language():
    from app.services.answering import build_instructions
    from app.services.terms import KEEP_TERMS

    for language in ("auto", "nl", "en"):
        instructions = build_instructions("explain", language=language)
        assert KEEP_TERMS in instructions
        assert "Notatie houd je zoals in het materiaal" in instructions


def test_a_del_character_where_a_backslash_belongs_is_restored():
    """Waargenomen op de streamende route: "$\x7fbar X$" in plaats van "$\\bar X$".

    Niet reproduceerbaar en de oorzaak is onbekend, maar DEL hoort in geen enkel
    antwoord thuis, dus vóór letters staat hij voor een backslash.
    """
    from app.services.answering import normalize_answer_text

    mangled = "$\x7fbar{X}$ met $\x7fmu$ en $\x7fsigma^2/40$"

    assert normalize_answer_text(mangled) == r"$\bar{X}$ met $\mu$ en $\sigma^2/40$"


def test_a_lone_del_is_dropped():
    from app.services.answering import normalize_answer_text

    assert "\x7f" not in normalize_answer_text("tekst met \x7f los teken")


def test_del_repair_leaves_ordinary_answers_alone():
    from app.services.answering import normalize_answer_text

    tekst = r"Ridge gebruikt $\lambda \sum \beta_j^2$; zie het boek."

    assert normalize_answer_text(tekst) == tekst
