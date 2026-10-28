from app.models import Chunk, Document, PracticeCard
from app.services.practice.decks import (
    MAX_SOURCE_CHARS,
    MAX_SOURCE_CHUNKS,
    deck_cards,
    list_decks,
    section_chunks,
)


def _document(db, *, course="fundamentals-of-ds", title="PDSH", status="indexed", sections=(), text=""):
    document = Document(
        title=title, source_path=f"{course}/books/{title}.pdf", checksum=title.ljust(64, "0"),
        course_slug=course, doc_kind="book", ingestion_status=status,
    )
    for index, (section, page) in enumerate(sections):
        document.chunks.append(Chunk(
            chunk_index=index, section_path=section, page_start=page, page_end=page,
            token_count=3, text=text or f"tekst {index}", normalized_text=f"tekst {index}",
            chunk_metadata={},
        ))
    db.add(document)
    db.commit()
    return document


def _card(db, *, course="fundamentals-of-ds", section, disabled=False, document_id="d", chunk_id="c"):
    card = PracticeCard(
        course_slug=course, document_id=document_id, chunk_id=chunk_id, section_path=section,
        page_start=1, page_end=1, kind="code", setup="", question="v", reference_answer="1",
        disabled=disabled,
    )
    db.add(card)
    db.commit()
    return card


def test_decks_are_section_paths_with_their_page_range(db_session):
    _document(db_session, sections=[("Ch 2 › Slicing", 64), ("Ch 2 › Slicing", 65), ("Ch 2 › Ufuncs", 70)])

    decks = list_decks(db_session, "fundamentals-of-ds")

    # "Ch 2" telt mee als deck: het bundelt twee secties, en zonder zo'n
    # bovenliggend pad valt een heel hoofdstuk (of college) niet te oefenen.
    assert [d.section_path for d in decks] == ["Ch 2", "Ch 2 › Slicing", "Ch 2 › Ufuncs"]
    hoofdstuk, slicing = decks[0], decks[1]
    assert (hoofdstuk.page_start, hoofdstuk.page_end, hoofdstuk.chunk_count) == (64, 70, 3)
    assert (slicing.page_start, slicing.page_end, slicing.chunk_count) == (64, 65, 2)
    assert slicing.document_title == "PDSH"


def test_decks_count_only_enabled_cards(db_session):
    _document(db_session, sections=[("Ch 2 › Slicing", 64)])
    _card(db_session, section="Ch 2 › Slicing")
    _card(db_session, section="Ch 2 › Slicing")
    _card(db_session, section="Ch 2 › Slicing", disabled=True)

    assert list_decks(db_session, "fundamentals-of-ds")[0].card_count == 2


def test_chunks_without_a_section_are_no_deck(db_session):
    _document(db_session, sections=[(None, 1), ("Ch 2 › Slicing", 64)])

    assert [d.section_path for d in list_decks(db_session, "fundamentals-of-ds")] == ["Ch 2 › Slicing"]


def test_only_indexed_documents_count(db_session):
    _document(db_session, title="mislukt", status="failed", sections=[("Ch 9 › Iets", 1)])

    assert list_decks(db_session, "fundamentals-of-ds") == []


def test_another_course_is_not_included(db_session):
    _document(db_session, course="sso", title="ISLR", sections=[("Ch 5 › CV", 214)])

    assert list_decks(db_session, "fundamentals-of-ds") == []
    assert [d.section_path for d in list_decks(db_session, "sso")] == ["Ch 5 › CV"]


def test_min_chunks_filters_thin_sections(db_session):
    _document(db_session, sections=[("Ch 2 › Dun", 1), ("Ch 2 › Dik", 2), ("Ch 2 › Dik", 3)])

    decks = list_decks(db_session, "fundamentals-of-ds", min_chunks=2)

    assert [d.section_path for d in decks] == ["Ch 2", "Ch 2 › Dik"]


def test_section_chunks_are_in_reading_order_and_capped(db_session):
    sections = [("Ch 2 › Slicing", page) for page in range(1, MAX_SOURCE_CHUNKS + 4)]
    _document(db_session, sections=sections)

    chunks = section_chunks(db_session, "fundamentals-of-ds", "Ch 2 › Slicing")

    assert len(chunks) == MAX_SOURCE_CHUNKS
    assert [c.chunk_index for c in chunks] == list(range(MAX_SOURCE_CHUNKS))


def test_deck_cards_skip_the_disabled_ones(db_session):
    _card(db_session, section="Ch 2 › Slicing")
    weggegooid = _card(db_session, section="Ch 2 › Slicing", disabled=True)

    cards = deck_cards(db_session, "fundamentals-of-ds", "Ch 2 › Slicing")

    assert len(cards) == 1
    assert weggegooid.id not in {c.id for c in cards}


def test_a_parent_with_one_child_is_not_a_second_deck(db_session):
    """Anders staat elke sectie er twee keer in, met precies dezelfde inhoud."""
    _document(db_session, sections=[("Ch 2 › Slicing", 64), ("Ch 2 › Slicing", 65)])

    assert [d.section_path for d in list_decks(db_session, "fundamentals-of-ds")] == ["Ch 2 › Slicing"]


def test_a_deck_gathers_the_sections_under_it(db_session):
    _document(db_session, sections=[("Lecture 3 › slide 1", 1), ("Lecture 3 › slide 2", 2)])

    chunks = section_chunks(db_session, "fundamentals-of-ds", "Lecture 3")

    assert [c.section_path for c in chunks] == ["Lecture 3 › slide 1", "Lecture 3 › slide 2"]


def test_a_prefix_does_not_reach_across_a_name(db_session):
    """"Lecture 3" mag "Lecture 30" niet opslokken."""
    _document(db_session, sections=[("Lecture 3 › slide 1", 1), ("Lecture 30 › slide 1", 2)])

    chunks = section_chunks(db_session, "fundamentals-of-ds", "Lecture 3")

    assert [c.section_path for c in chunks] == ["Lecture 3 › slide 1"]


def test_source_text_stops_at_the_character_budget(db_session):
    lang = "w" * (MAX_SOURCE_CHARS // 3 + 1)
    _document(db_session, sections=[("Ch 2 › Slicing", page) for page in range(1, 5)], text=lang)

    chunks = section_chunks(db_session, "fundamentals-of-ds", "Ch 2 › Slicing")

    assert len(chunks) == 2  # de derde past niet meer in het budget
