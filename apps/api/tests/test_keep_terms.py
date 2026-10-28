"""Nederlandse tekst, Engelse vaktermen.

De weekkaart van FDS week 4 sprak van "ongesuperviseerd leren" en
"ongecontroleerd leren", terwijl college, boek en tentamen "unsupervised
learning" zeggen. Elke instructie die het model Nederlands laat schrijven,
draagt daarom dezelfde regel; deze test houdt bij dat er geen tussenuit valt.
"""
import pytest

from app.services.answering import build_instructions
from app.services.practice import choice_generation, exam_generation, generation, grading, output_generation
from app.services.study import examples
from app.services.terms import KEEP_TERMS, keep_terms
from app.services.weeks_summary import INSTRUCTIONS as SUMMARY_INSTRUCTIONS


DUTCH_WRITERS = {
    "weekkaart": SUMMARY_INSTRUCTIONS,
    "uitgewerkt voorbeeld": examples.INSTRUCTIONS,
    "keuzekaart": choice_generation.INSTRUCTIONS,
    "codekaart": generation.CODE_INSTRUCTIONS,
    "toetskaart": generation.STATS_INSTRUCTIONS,
    "wat print dit": output_generation.INSTRUCTIONS,
    "nakijken van een open vraag": grading.GRADER_INSTRUCTIONS,
    "tentamenvraag": exam_generation.exam_instructions("vak-zonder-proeftentamen"),
    "tentamenvraag herstellen": exam_generation.repair_instructions(),
    "chat in het Nederlands": build_instructions("explain", language="nl"),
    "chat in de taal van de vraag": build_instructions("explain", language="auto"),
}


@pytest.mark.parametrize("name", DUTCH_WRITERS)
def test_elke_nederlandse_schrijver_vertaalt_geen_vaktermen(name):
    assert KEEP_TERMS in DUTCH_WRITERS[name]


def test_de_regel_noemt_de_vertaling_die_misging():
    # Een regel zonder voorbeeld volgt het model slecht; het voorbeeld is de
    # fout die het echt maakte.
    assert "unsupervised learning" in KEEP_TERMS
    assert "ongesuperviseerd leren" in KEEP_TERMS


# Wat het model ondanks de regel nog schreef: in de rode draad van FDS week 4
# stond na de regel nog "dezelfde ongesuperviseerde ideeën". Een vaste lijst
# zet de vertalingen die echt voorkwamen terug; de instructie dekt de rest.
@pytest.mark.parametrize(
    ("tekst", "verwacht"),
    [
        ("Eerst gaat het over ongesuperviseerd leren: hoe je", "Eerst gaat het over unsupervised learning: hoe je"),
        ("Ongecontroleerd leren: wat en waarom", "Unsupervised learning: wat en waarom"),
        ("dezelfde ongesuperviseerde ideeën", "dezelfde unsupervised ideeën"),
        ("andere niet-gesuperviseerde settings", "andere unsupervised settings"),
        ("afgezet tegen gesuperviseerd leren.", "afgezet tegen supervised learning."),
        ("PCA en dimensiereductie", "PCA en dimensionality reduction"),
        ("Dimensionaliteitsreductie met PCA", "Dimensionality reduction met PCA"),
    ],
)
def test_bekende_vertalingen_worden_teruggezet(tekst, verwacht):
    assert keep_terms(tekst) == verwacht


def test_gewoon_nederlands_blijft_staan():
    # "gecontroleerd" is pas een vertaling vóór "leren".
    tekst = "In een gecontroleerd experiment wordt de dosis gecontroleerd."
    assert keep_terms(tekst) == tekst


def test_een_weekkaart_wordt_bewaard_met_de_engelse_term(db_session):
    from app.models import Chunk, Document
    from app.services.weeks_summary import SummaryDraft, Topic, build_summary

    document = Document(
        title="Lecture 7", source_path="fds/slides/week-04/Lecture 7.pdf", checksum="7".ljust(64, "0"),
        course_slug="fds", doc_kind="slides", week=4, ingestion_status="indexed",
    )
    document.chunks.append(Chunk(
        chunk_index=0, section_path="Lecture 7 › slide 1", page_start=1, page_end=1,
        token_count=2, text="unsupervised learning", normalized_text="unsupervised learning", chunk_metadata={},
    ))
    db_session.add(document)
    db_session.commit()
    draft = SummaryDraft(
        thread="Dezelfde ongesuperviseerde ideeën op grafen.",
        topics=[Topic(label="Ongecontroleerd leren: wat en waarom", covers="Afgezet tegen gesuperviseerd leren.", where="slides 3-6")],
        skills=["dimensiereductie toepassen met PCA"],
    )

    class _Client:
        class responses:
            @staticmethod
            def parse(**_):
                return type("Parsed", (), {"output_parsed": draft})()

    summary = build_summary(db_session, course_slug="fds", week=4, client=_Client())

    assert summary.content["thread"] == "Dezelfde unsupervised ideeën op grafen."
    assert summary.content["topics"][0]["label"] == "Unsupervised learning: wat en waarom"
    assert summary.content["topics"][0]["covers"] == "Afgezet tegen supervised learning."
    assert summary.content["skills"] == ["dimensionality reduction toepassen met PCA"]
