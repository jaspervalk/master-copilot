import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Chunk, Conversation, Course, Document, Message


def _document(**overrides) -> Document:
    values = dict(
        title="Bishop PRML",
        source_path="statistical-learning/books/bishop.pdf",
        checksum="a" * 64,
        course_slug="statistical-learning",
        doc_kind="book",
        week=None,
    )
    values.update(overrides)
    return Document(**values)


def test_document_defaults(db_session):
    document = _document()
    db_session.add(document)
    db_session.commit()

    assert len(document.id) == 36
    assert document.ingestion_status == "pending"
    assert document.assignment_status is None
    assert document.chunk_count == 0


def test_source_path_is_unique(db_session):
    db_session.add(_document())
    db_session.commit()
    db_session.add(_document(checksum="b" * 64))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_deleting_document_cascades_to_chunks(db_session):
    document = _document()
    document.chunks.append(
        Chunk(
            chunk_index=0,
            section_path="1 Introduction",
            page_start=1,
            page_end=2,
            token_count=10,
            text="hello",
            normalized_text="hello",
            chunk_metadata={},
        )
    )
    db_session.add(document)
    db_session.commit()
    assert db_session.query(Chunk).count() == 1

    db_session.delete(document)
    db_session.commit()
    assert db_session.query(Chunk).count() == 0


def test_course_slug_is_primary_key(db_session):
    db_session.add(Course(slug="deep-learning", name="Deep Learning"))
    db_session.commit()
    assert db_session.get(Course, "deep-learning").name == "Deep Learning"


def test_conversation_orders_messages_by_creation(db_session):
    conversation = Conversation(course_slug="deep-learning", title="Backprop")
    conversation.messages.append(Message(role="user", content="Wat is backprop?"))
    conversation.messages.append(
        Message(role="assistant", content="…", rewritten_query="uitleg backpropagation")
    )
    db_session.add(conversation)
    db_session.commit()

    roles = [message.role for message in conversation.messages]
    assert roles == ["user", "assistant"]
