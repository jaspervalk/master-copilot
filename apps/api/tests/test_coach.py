import pytest

from app.models import Chunk, Document
from app.schemas import CoachOptions
from app.services.coach import MAX_PINNED, CoachError, load_coach_context, policy_instruction


def _doc(db, *, kind, course="sso", week=4, status=None, chunks=3):
    folder = f"{kind}s/week-{week:02d}" if week is not None else f"{kind}s"
    document = Document(
        title=f"{kind} {week}", source_path=f"{course}/{folder}/x.pdf", checksum="0" * 64,
        course_slug=course, doc_kind=kind, week=week, assignment_status=status, ingestion_status="indexed",
    )
    for index in range(chunks):
        document.chunks.append(Chunk(
            chunk_index=index, section_path=f"Opgave {index + 1}", page_start=1, page_end=1,
            token_count=3, text=f"tekst {index}", normalized_text=f"tekst {index}", chunk_metadata={},
        ))
    db.add(document)
    db.commit()
    return document


def test_open_assignment_is_hints_with_pinned_chunks_in_order(db_session):
    document = _doc(db_session, kind="assignment", status="open")

    context = load_coach_context(db_session, CoachOptions(document_id=document.id), course_slug="sso")

    assert context.policy == "hints"
    assert [c.section_path for c in context.pinned] == ["Opgave 1", "Opgave 2", "Opgave 3"]
    assert context.echo.document_title == "assignment 4"


def test_pinned_chunks_are_capped(db_session):
    document = _doc(db_session, kind="exercise", chunks=MAX_PINNED + 5)

    context = load_coach_context(db_session, CoachOptions(document_id=document.id), course_slug="sso")

    assert len(context.pinned) == MAX_PINNED


def test_exercise_with_reveal_is_reveal(db_session):
    document = _doc(db_session, kind="exercise")

    context = load_coach_context(
        db_session, CoachOptions(document_id=document.id, reveal=True), course_slug="sso"
    )

    assert context.policy == "reveal"


def test_reveal_never_applies_to_a_graded_assignment(db_session):
    document = _doc(db_session, kind="assignment", status="open")

    context = load_coach_context(
        db_session, CoachOptions(document_id=document.id, reveal=True), course_slug="sso"
    )

    assert context.policy == "hints"


@pytest.mark.parametrize("status", ["closed", "submitted"])
def test_closed_or_submitted_assignment_is_refused(db_session, status):
    document = _doc(db_session, kind="assignment", status=status)

    with pytest.raises(CoachError, match=status):
        load_coach_context(db_session, CoachOptions(document_id=document.id), course_slug="sso")


def test_other_kinds_and_other_courses_are_refused(db_session):
    book = _doc(db_session, kind="book", week=None)
    other = _doc(db_session, kind="assignment", course="fds", status="open")

    with pytest.raises(CoachError, match="book"):
        load_coach_context(db_session, CoachOptions(document_id=book.id), course_slug="sso")
    with pytest.raises(CoachError, match="fds"):
        load_coach_context(db_session, CoachOptions(document_id=other.id), course_slug="sso")


def test_unknown_document_is_refused(db_session):
    with pytest.raises(CoachError, match="niet gevonden"):
        load_coach_context(db_session, CoachOptions(document_id="nope"), course_slug="sso")


def test_policy_instruction_texts():
    assert "nooit het eindantwoord" in policy_instruction("hints", "assignment")
    assert "volledige uitwerking vragen" in policy_instruction("hints", "exercise")
    assert "volledige uitwerking" in policy_instruction("reveal", "exercise")
