from app.models import Conversation, Message
from app.schemas import AnswerResponse
from app.services import conversations


def _answer(**overrides) -> AnswerResponse:
    values = dict(
        question="Wat is backprop?",
        rewritten_query=None,
        answer="Uitleg [1]",
        abstained=False,
        confidence="high",
        confidence_reasons=[],
        citations=[],
        retrieved_chunks=[],
        embedding_provider="local-hash",
        answer_model="local-extractive",
        answer_style="explain",
    )
    values.update(overrides)
    return AnswerResponse(**values)


def test_creates_a_conversation_when_none_is_given(db_session):
    conversation = conversations.get_or_create(db_session, None, course_slug="dl")

    assert conversation.id
    assert conversation.course_slug == "dl"
    assert db_session.query(Conversation).count() == 1


def test_returns_the_existing_conversation(db_session):
    first = conversations.get_or_create(db_session, None, course_slug="dl")

    again = conversations.get_or_create(db_session, first.id, course_slug="dl")

    assert again.id == first.id
    assert db_session.query(Conversation).count() == 1


def test_unknown_conversation_id_starts_a_new_one(db_session):
    conversation = conversations.get_or_create(db_session, "bestaat-niet", course_slug=None)

    assert conversation.id != "bestaat-niet"


def test_history_returns_the_last_turns_in_order(db_session):
    conversation = conversations.get_or_create(db_session, None, course_slug="dl")
    for index in range(5):
        db_session.add(Message(conversation_id=conversation.id, role="user", content=f"vraag {index}"))
        db_session.commit()

    recent = conversations.history(db_session, conversation.id, limit=3)

    assert [message.content for message in recent] == ["vraag 2", "vraag 3", "vraag 4"]


def test_first_turn_is_not_rewritten(db_session):
    assert conversations.rewrite_followup(history=[], question="Wat is de ELBO?", client=None) is None


def test_without_a_client_the_followup_is_not_rewritten(db_session):
    history = [Message(role="user", content="Wat is backprop?")]

    assert conversations.rewrite_followup(history=history, question="En waarom werkt dat?", client=None) is None


def test_rewrite_uses_the_model_output(db_session):
    class FakeResponses:
        def create(self, **kwargs):
            class _Response:
                output_text = "  waarom werkt backpropagation  "

            return _Response()

    class FakeClient:
        responses = FakeResponses()

    history = [Message(role="user", content="Wat is backprop?")]

    result = conversations.rewrite_followup(
        history=history, question="En waarom werkt dat?", client=FakeClient(), model="test"
    )

    assert result == "waarom werkt backpropagation"


def test_rewrite_failure_falls_back_to_no_rewrite(db_session):
    class FakeClient:
        class responses:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("model down")

    history = [Message(role="user", content="Wat is backprop?")]

    assert conversations.rewrite_followup(history=history, question="En waarom?", client=FakeClient()) is None


def test_record_turn_stores_both_messages(db_session):
    conversation = conversations.get_or_create(db_session, None, course_slug="dl")

    user_message, assistant_message = conversations.record_turn(
        db_session, conversation, question="Wat is backprop?", answer=_answer()
    )

    assert user_message.role == "user"
    assert assistant_message.role == "assistant"
    assert assistant_message.confidence == "high"
    assert db_session.query(Message).count() == 2
    assert conversation.title == "Wat is backprop?"
