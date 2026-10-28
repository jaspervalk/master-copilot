import pytest
from fastapi.testclient import TestClient

from app.api.routes import practice as practice_route
from app.db import get_db
from app.main import app
from app.models import Chunk, Document, PracticeAttempt, PracticeCard


SECTION = "Chapter 2 › Array Slicing"


@pytest.fixture()
def client(db_session, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _document(db, *, course="fundamentals-of-ds", section=SECTION, chunks=2):
    document = Document(
        title="PDSH", source_path=f"{course}/books/pdsh.pdf", checksum="0" * 64,
        course_slug=course, doc_kind="book", ingestion_status="indexed",
    )
    for index in range(chunks):
        document.chunks.append(Chunk(
            chunk_index=index, section_path=section, page_start=60 + index, page_end=60 + index,
            token_count=3, text=f"stuk {index}", normalized_text=f"stuk {index}", chunk_metadata={},
        ))
    db.add(document)
    db.commit()
    return document


def _card(db, *, setup="x2 = np.arange(12).reshape(3, 4)", answer="x2.mean(axis=0)", disabled=False):
    card = PracticeCard(
        course_slug="fundamentals-of-ds", document_id="doc", chunk_id="chunk", section_path=SECTION,
        page_start=64, page_end=64, kind="code", setup=setup,
        question="Het gemiddelde per kolom?", reference_answer=answer, disabled=disabled,
    )
    db.add(card)
    db.commit()
    return card


def test_decks_are_listed_for_a_course(client, db_session):
    _document(db_session)

    response = client.get("/api/practice/decks", params={"course_slug": "fundamentals-of-ds"})

    assert response.status_code == 200
    body = response.json()
    assert body[0]["section_path"] == SECTION
    assert body[0]["chunk_count"] == 2


def test_thin_sections_are_hidden_by_default(client, db_session):
    """Van één alinea valt weinig te oefenen, en het scheelt honderden regels."""
    _document(db_session, section="Ch 2 › Dun", chunks=1)

    assert client.get("/api/practice/decks", params={"course_slug": "fundamentals-of-ds"}).json() == []
    ruim = client.get(
        "/api/practice/decks", params={"course_slug": "fundamentals-of-ds", "min_chunks": 1}
    ).json()
    assert len(ruim) == 1


def test_a_correct_attempt_is_judged_and_logged(client, db_session):
    card = _card(db_session)

    response = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "np.mean(x2, axis=0)"})

    body = response.json()
    assert body["correct"] is True
    assert body["reference_answer"] == "x2.mean(axis=0)"
    assert body["page_start"] == 64
    assert db_session.query(PracticeAttempt).one().correct is True


def test_a_wrong_attempt_shows_both_values(client, db_session):
    card = _card(db_session)

    body = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "x2.mean(axis=1)"}).json()

    assert body["correct"] is False
    assert body["expected_repr"] != body["given_repr"]
    assert body["error"] is None


def test_a_broken_answer_returns_the_error_not_a_crash(client, db_session):
    card = _card(db_session)

    body = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "x2.mean(axis="}).json()

    assert body["correct"] is False
    assert "Syntax" in body["error"]


def test_a_card_whose_reference_is_broken_is_a_server_error(client, db_session):
    """Dat is een kapotte kaart, geen fout antwoord — het hoort niet als
    mislukte poging in je geschiedenis te belanden."""
    card = _card(db_session, answer="x2.bestaatniet()")

    response = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "x2.mean(axis=0)"})

    assert response.status_code == 500
    assert "deugt niet" in response.json()["detail"]
    assert db_session.query(PracticeAttempt).count() == 0


def test_an_unknown_card_is_404(client):
    assert client.post("/api/practice/cards/nope/attempt", json={"answer": "1"}).status_code == 404


def test_discarding_a_card_removes_it_from_the_deck(client, db_session):
    card = _card(db_session)

    assert client.delete(f"/api/practice/cards/{card.id}").status_code == 200

    cards = client.get(
        "/api/practice/cards",
        params={"course_slug": "fundamentals-of-ds", "section_path": SECTION},
    ).json()
    assert cards == []
    # Niet gewist: pogingen houden hun verwijzing.
    assert db_session.query(PracticeCard).count() == 1


def test_generating_from_an_empty_section_is_400(client, db_session, monkeypatch):
    def boom(*args, **kwargs):
        from app.services.practice.generation import NoSourceMaterial

        raise NoSourceMaterial("'niets' heeft geen tekst")

    monkeypatch.setattr(practice_route, "generate_cards", boom)

    response = client.post(
        "/api/practice/decks/generate",
        json={"course_slug": "fundamentals-of-ds", "section_path": "niets"},
    )

    assert response.status_code == 400
    assert "geen tekst" in response.json()["detail"]


def test_generate_returns_created_and_rejected(client, db_session, monkeypatch):
    document = _document(db_session)
    from app.services.practice.generation import GenerationReport

    def fake(db, *, course_slug, section_path, count, kind):
        card = PracticeCard(
            course_slug=course_slug, document_id=document.id, chunk_id=document.chunks[0].id,
            section_path=section_path, page_start=60, page_end=60, kind="code",
            setup="x = np.arange(3)", question="Som?", reference_answer="x.sum()",
        )
        db.add(card)
        db.commit()
        return GenerationReport(created=[card], rejected=[("Onzin?", "draait niet")])

    monkeypatch.setattr(practice_route, "generate_cards", fake)

    body = client.post(
        "/api/practice/decks/generate",
        json={"course_slug": "fundamentals-of-ds", "section_path": SECTION, "count": 2},
    ).json()

    assert [c["question"] for c in body["created"]] == ["Som?"]
    assert body["rejected"] == [{"label": "Onzin?", "reason": "draait niet"}]


# --- toetskaarten -----------------------------------------------------------


def _stats_card(db, *, answer="(xbar - mu) / (s / np.sqrt(n))", explanation="H0: mu = 11,0. $t = 3{,}92$."):
    card = PracticeCard(
        course_slug="sso", document_id="doc", chunk_id="chunk", section_path="Lecture 3",
        page_start=7, page_end=7, kind="stats", setup="n = 40\nxbar = 12.3\nmu = 11.0\ns = 2.1",
        question="Geef de toetsingsgrootheid.", reference_answer=answer, explanation=explanation,
    )
    db.add(card)
    db.commit()
    return card


def test_a_rounded_answer_to_a_stats_card_is_correct(client, db_session):
    """Op papier reken je met twee decimalen; dat mag geen fout opleveren."""
    card = _stats_card(db_session)

    body = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "3.92"}).json()

    assert body["correct"] is True
    assert body["kind"] == "stats"


def test_the_worked_solution_only_appears_after_an_attempt(client, db_session):
    card = _stats_card(db_session)

    listed = client.get(
        "/api/practice/cards", params={"course_slug": "sso", "section_path": "Lecture 3"}
    ).json()
    assert "explanation" not in listed[0]

    body = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "3.92"}).json()
    assert "$t = 3{,}92$" in body["explanation"]


def test_a_code_card_is_still_judged_exactly(client, db_session):
    card = _card(db_session, setup="x = 3.0", answer="x / 7")

    body = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "0.43"}).json()

    assert body["correct"] is False
    assert body["explanation"] == ""


def test_an_unknown_card_kind_is_a_clear_error(client, db_session):
    _document(db_session)

    response = client.post(
        "/api/practice/decks/generate",
        json={"course_slug": "fundamentals-of-ds", "section_path": SECTION, "kind": "onzin"},
    )

    assert response.status_code == 422


def test_the_review_round_crosses_the_decks(client, db_session):
    """Herkennen wélke toets je moet doen oefen je niet als ze per college
    op een rij staan."""
    _stats_card(db_session)
    ander = PracticeCard(
        course_slug="sso", document_id="doc", chunk_id="chunk", section_path="Lecture 1",
        page_start=3, page_end=3, kind="stats", setup="n = 25",
        question="Iets anders?", reference_answer="n / 5", explanation="Vijf.",
    )
    db_session.add(ander)
    db_session.commit()

    body = client.get("/api/practice/due", params={"course_slug": "sso"}).json()

    assert {card["section_path"] for card in body} == {"Lecture 1", "Lecture 3"}


def test_a_card_just_answered_drops_out_of_the_round(client, db_session):
    card = _stats_card(db_session)

    assert len(client.get("/api/practice/due", params={"course_slug": "sso"}).json()) == 1
    client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "3.92"})

    assert client.get("/api/practice/due", params={"course_slug": "sso"}).json() == []


def test_the_deck_list_says_how_many_are_waiting(client, db_session):
    _document(db_session)
    _card(db_session)

    body = client.get("/api/practice/decks", params={"course_slug": "fundamentals-of-ds"}).json()

    assert body[0]["due_count"] == 1


# --- tentamenkaarten ------------------------------------------------------------


def _exam_card(db, *, position, section=3, kind="mc", points=1.5, **spec_extra):
    spec = {"exam": "mock-exam-1", "section": f"{section} Supervised Learning", "section_number": section}
    if kind == "mc":
        spec |= {"options": ["6/11", "5/6", "1/6", "5/11"], "multi": False, "answer": [2], "material": "ISLR §4.4.2"}
        reference = "c"
    else:
        spec |= {"rubric": [{"criterion": "Overfitting.", "points": 2}, {"criterion": "High variance.", "points": 2}]}
        reference = "Overfitting and high variance."
    spec |= spec_extra
    card = PracticeCard(
        course_slug="fundamentals-of-ds", document_id="", chunk_id="",
        section_path=f"Mock Exam 1 › {section} Supervised Learning", page_start=6, page_end=6,
        kind=kind, question=f"Vraag {position}", reference_answer=reference, explanation="Waarom.",
        spec=spec, points=points, origin="mock-exam-1", position=position, week=3,
    )
    db.add(card)
    db.commit()
    return card


def test_an_exam_card_does_not_give_away_its_answer(client, db_session):
    _exam_card(db_session, position=1)

    body = client.get("/api/practice/exams/mock-exam-1/cards", params={"course_slug": "fundamentals-of-ds"}).json()

    assert body[0]["options"] == ["6/11", "5/6", "1/6", "5/11"]
    assert body[0]["points"] == 1.5
    assert "answer" not in body[0] and "spec" not in body[0] and "reference_answer" not in body[0]


def test_exam_cards_come_in_exam_order_and_per_section(client, db_session):
    _exam_card(db_session, position=2, section=4)
    _exam_card(db_session, position=1, section=3)

    alle = client.get("/api/practice/exams/mock-exam-1/cards", params={"course_slug": "fundamentals-of-ds"}).json()
    sectie = client.get(
        "/api/practice/exams/mock-exam-1/cards", params={"course_slug": "fundamentals-of-ds", "section": 4}
    ).json()

    assert [card["position"] for card in alle] == [1, 2]
    assert [card["position"] for card in sectie] == [2]


def test_a_multiple_choice_attempt_scores_points(client, db_session):
    card = _exam_card(db_session, position=1)

    goed = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "c"}).json()
    fout = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "b"}).json()

    assert (goed["correct"], goed["score"], goed["max_score"]) == (True, 1.5, 1.5)
    assert (fout["correct"], fout["score"], fout["selected"], fout["correct_options"]) == (False, 0.0, [1], [2])
    assert fout["material"] == "ISLR §4.4.2"
    assert [a.score for a in db_session.query(PracticeAttempt).order_by(PracticeAttempt.created_at)] == [1.5, 0.0]


def test_an_invalid_choice_is_not_logged_as_a_wrong_answer(client, db_session):
    card = _exam_card(db_session, position=1)

    response = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "e"})

    assert response.status_code == 400
    assert db_session.query(PracticeAttempt).count() == 0


def test_an_open_attempt_is_graded_and_its_feedback_kept(client, db_session, monkeypatch):
    from app.services.practice import grading
    from app.services.practice.grading import CriterionVerdict, OpenVerdict

    card = _exam_card(db_session, position=2, kind="open", points=4.0)
    verdict = OpenVerdict(
        criteria=[
            CriterionVerdict(criterion=0, awarded=2, evidence="it overfits", comment="Goed."),
            CriterionVerdict(criterion=1, awarded=2, evidence="low bias", comment="Verzonnen."),
        ],
        feedback="Noem high variance.",
    )

    class _Grader:
        class responses:  # noqa: N801 — bootst de SDK na
            @staticmethod
            def parse(**_):
                return type("Parsed", (), {"output_parsed": verdict})()

    monkeypatch.setattr(grading, "_client", lambda: _Grader())

    body = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "With k = 1 it overfits."}).json()

    assert (body["score"], body["max_score"], body["correct"]) == (2.0, 4.0, False)
    assert body["criteria"][1]["withdrawn"] is True
    assert body["feedback"] == "Noem high variance."
    opgeslagen = db_session.query(PracticeAttempt).one()
    assert opgeslagen.feedback["criteria"][0]["evidence"] == "it overfits"


def test_the_exam_overview_shows_the_score_per_section(client, db_session):
    eerste = _exam_card(db_session, position=1, section=3)
    _exam_card(db_session, position=2, section=3)
    _exam_card(db_session, position=3, section=5, points=1.5)
    client.post(f"/api/practice/cards/{eerste.id}/attempt", json={"answer": "b"})
    client.post(f"/api/practice/cards/{eerste.id}/attempt", json={"answer": "c"})

    (tentamen,) = client.get("/api/practice/exams", params={"course_slug": "fundamentals-of-ds"}).json()

    assert (tentamen["title"], tentamen["question_count"], tentamen["points"]) == ("Mock Exam 1", 3, 4.5)
    drie, vijf = tentamen["sections"]
    # De laatste poging telt: eerst fout, daarna goed.
    assert (drie["number"], drie["answered"], drie["answered_points"], drie["last_score"]) == (3, 1, 1.5, 1.5)
    assert (vijf["number"], vijf["answered"]) == (5, 0)


def test_the_due_count_includes_exam_cards_once_you_did_them(client, db_session):
    card = _exam_card(db_session, position=1)
    assert client.get("/api/practice/due/count", params={"course_slug": "fundamentals-of-ds"}).json() == {"total": 0}

    client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "b"})

    assert client.get("/api/practice/due/count", params={"course_slug": "fundamentals-of-ds"}).json() == {"total": 1}


def _output_card(db):
    card = PracticeCard(
        course_slug="sso", document_id="doc", chunk_id="chunk", section_path="Lecture 8 › Knapsack",
        page_start=1, page_end=1, kind="output",
        setup="for i in range(3):\n    print(i * 1.5)",
        question="Wat print dit fragment?", reference_answer="0.0\n1.5\n3.0",
        explanation="De lus loopt 0, 1, 2; keer 1.5 geeft 0.0, 1.5 en 3.0.",
    )
    db.add(card)
    db.commit()
    return card


def test_a_predicted_output_is_graded_against_what_really_printed(client, db_session):
    """Mild waar de docent mild is: 0 voor 0.0 telt."""
    card = _output_card(db_session)

    goed = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "0\n1.5\n3"}).json()

    assert goed["correct"] is True
    assert goed["reference_answer"] == "0.0\n1.5\n3.0"
    assert "lus" in goed["explanation"]


def test_a_wrong_prediction_shows_the_real_output(client, db_session):
    card = _output_card(db_session)

    fout = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "0\n1\n2"}).json()

    assert fout["correct"] is False
    assert fout["reference_answer"] == "0.0\n1.5\n3.0"
    assert db_session.query(PracticeAttempt).filter_by(card_id=card.id, correct=False).count() == 1


def test_an_output_card_does_not_run_the_students_answer(client, db_session):
    """Het antwoord is een voorspelde uitvoer, geen code. Het mag dus nooit in
    de sandbox belanden — 'import os' is hier gewoon een fout antwoord."""
    card = _output_card(db_session)

    antwoord = client.post(f"/api/practice/cards/{card.id}/attempt", json={"answer": "import os"}).json()

    assert antwoord["correct"] is False
    assert antwoord.get("error") in (None, "")
