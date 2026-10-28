"""Materiaal van Canvas ophalen: door hetzelfde ingestpad als uploaden, op de
voorgestelde plek of op de plek die de gebruiker kiest."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes import agenda as agenda_route
from app.db import get_db
from app.main import app
from app.models import CanvasCourse, CanvasFile, CanvasItem, CanvasPage, Course, Document
from app.services import corpus_sync
from app.services import documents as documents_service
from app.services.canvas.client import CanvasClient
from app.services.parsing import ParsedDocument, ParsedPage
from tests.canvas_stub import canvas_opener

FDS = 59831
PDF = b"%PDF-1.4 inhoud van het college"


class _FakeBatch:
    provider = "local-hash"
    model = "local"
    dimensions = 3

    def __init__(self, count: int) -> None:
        self.vectors = [[0.1, 0.2, 0.3] for _ in range(count)]


class _FakeEmbeddings:
    def embed_many(self, texts: list[str]) -> _FakeBatch:
        return _FakeBatch(len(texts))


@pytest.fixture()
def client(db_session, tmp_corpus, fake_qdrant, monkeypatch):
    def fake_parse(path: Path) -> ParsedDocument:
        return ParsedDocument(
            title=path.stem, page_count=1,
            pages=[ParsedPage(page_number=1, text="1 Kop\n\n" + " ".join(["woord"] * 60))], metadata={},
        )

    monkeypatch.setattr(documents_service, "parse_document", fake_parse)
    monkeypatch.setattr(documents_service, "EmbeddingService", lambda: _FakeEmbeddings())
    monkeypatch.setattr(documents_service, "refresh_hybrid_index", lambda db: 0)
    monkeypatch.setattr(agenda_route, "_now", lambda: datetime(2026, 9, 17, 8, 0))

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _canvas(monkeypatch, routes: dict | None = None):
    stub = canvas_opener(
        routes
        if routes is not None
        else {
            "files/9003": {"id": 9003, "filename": "20260915_lecture05_classification.pdf", "url": "https://canvas.test/files/9003/download?verifier=x"},
            "/files/9003/download": PDF,
            "files/9002": {"id": 9002, "filename": "Lab3.zip", "url": "https://canvas.test/files/9002/download"},
            "files/9010": {"id": 9010, "filename": "Statistical_Tables_V2.pdf", "url": "https://canvas.test/files/9010/download"},
            "/files/9010/download": PDF,
        }
    )
    monkeypatch.setattr(agenda_route, "_client", lambda: CanvasClient(base_url="https://canvas.test", token="t", opener=stub))
    return stub


def _setup(db, tmp_corpus):
    (tmp_corpus / "fundamentals-of-ds").mkdir()
    (tmp_corpus / "fundamentals-of-ds" / "course.yml").write_text("name: FDS\ncanvas_id: 59831\n", encoding="utf-8")
    db.add(Course(slug="fundamentals-of-ds", name="FDS", canvas_id=FDS, week_plans={"3": {"lectures": [5, 6], "topics": [], "reading": []}}))
    db.add(CanvasCourse(id=FDS, name="Fundamentals of Data Science", fetched_at=datetime(2026, 9, 17, 8, 0)))
    db.add_all(
        [
            CanvasFile(id=9003, canvas_course_id=FDS, filename="20260915_lecture05_classification.pdf", display_name="lecture05", module_name="Week 3", source="module:Week 3"),
            CanvasFile(id=9002, canvas_course_id=FDS, filename="Lab3.zip", display_name="Lab3.zip", module_name="Week 3", source="module:Week 3"),
            CanvasFile(id=9010, canvas_course_id=FDS, filename="Statistical_Tables_V2.pdf", display_name="tabellen", folder="statistics", source="page:x"),
        ]
    )
    db.commit()


def test_materials_are_listed_with_their_proposal(client, db_session, tmp_corpus):
    _setup(db_session, tmp_corpus)

    course = next(entry for entry in client.get("/api/agenda").json()["courses"] if entry["canvas_id"] == FDS)

    by_id = {material["id"]: material for material in course["materials"]}
    assert by_id[9003]["state"] == "new"
    assert by_id[9003]["placement"] == {"doc_kind": "slides", "week": 3, "relative_path": "fundamentals-of-ds/slides/week-03/20260915_lecture05_classification.pdf"}
    assert by_id[9002]["state"] == "unsupported" and by_id[9002]["placement"] is None
    assert by_id[9010]["state"] == "unplaced" and "kies" in by_id[9010]["reason"]


def test_fetching_puts_the_file_in_the_corpus_and_indexes_it(client, db_session, tmp_corpus, monkeypatch):
    _setup(db_session, tmp_corpus)
    _canvas(monkeypatch)

    response = client.post("/api/agenda/materials/9003/fetch", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document"]["source_path"] == "fundamentals-of-ds/slides/week-03/20260915_lecture05_classification.pdf"
    assert body["document"]["ingestion_status"] == "indexed"
    assert body["material"]["state"] == "downloaded"
    assert (tmp_corpus / "fundamentals-of-ds" / "slides" / "week-03" / "20260915_lecture05_classification.pdf").read_bytes() == PDF
    assert db_session.get(CanvasFile, 9003).document_id == body["document"]["id"]


def test_the_users_choice_of_kind_and_week_wins(client, db_session, tmp_corpus, monkeypatch):
    _setup(db_session, tmp_corpus)
    _canvas(monkeypatch)

    response = client.post("/api/agenda/materials/9010/fetch", json={"doc_kind": "note", "week": 2})

    assert response.status_code == 200, response.text
    assert response.json()["document"]["source_path"] == "fundamentals-of-ds/notes/week-02/Statistical_Tables_V2.pdf"


def test_slides_or_an_assignment_without_a_week_are_refused(client, db_session, tmp_corpus, monkeypatch):
    """Slides zonder week vallen buiten elke weekkaart en weekfilter; een
    opgavenblad zonder week heeft geen status. Zo belandde lecture5.pdf van
    SSO los in slides/."""
    _setup(db_session, tmp_corpus)
    _canvas(monkeypatch)

    for kind in ("slides", "assignment"):
        response = client.post("/api/agenda/materials/9010/fetch", json={"doc_kind": kind})
        assert response.status_code == 400
        assert "week" in response.json()["detail"]
    assert not list((tmp_corpus / "fundamentals-of-ds").rglob("*.pdf"))


def test_a_deleted_download_can_be_fetched_again(client, db_session, tmp_corpus, monkeypatch):
    _setup(db_session, tmp_corpus)
    _canvas(monkeypatch)
    document_id = client.post("/api/agenda/materials/9003/fetch", json={}).json()["document"]["id"]

    assert client.delete(f"/api/documents/{document_id}").status_code == 200

    course = next(entry for entry in client.get("/api/agenda").json()["courses"] if entry["canvas_id"] == FDS)
    assert next(m for m in course["materials"] if m["id"] == 9003)["state"] == "new"
    assert client.post("/api/agenda/materials/9003/fetch", json={}).status_code == 200


def test_without_a_proposal_or_a_choice_nothing_is_guessed(client, db_session, tmp_corpus, monkeypatch):
    _setup(db_session, tmp_corpus)
    _canvas(monkeypatch)

    response = client.post("/api/agenda/materials/9010/fetch", json={})

    assert response.status_code == 400
    assert "kies" in response.json()["detail"]
    assert not list((tmp_corpus / "fundamentals-of-ds").rglob("*.pdf"))


def test_an_unsupported_file_is_refused(client, db_session, tmp_corpus, monkeypatch):
    _setup(db_session, tmp_corpus)
    _canvas(monkeypatch)

    response = client.post("/api/agenda/materials/9002/fetch", json={"doc_kind": "exercise", "week": 3})

    assert response.status_code == 400
    assert ".zip" in response.json()["detail"]


def test_a_file_that_is_already_there_needs_overwrite(client, db_session, tmp_corpus, monkeypatch):
    _setup(db_session, tmp_corpus)
    _canvas(monkeypatch)
    assert client.post("/api/agenda/materials/9003/fetch", json={}).status_code == 200

    again = client.post("/api/agenda/materials/9003/fetch", json={})
    assert again.status_code == 409

    forced = client.post("/api/agenda/materials/9003/fetch", json={"overwrite": True})
    assert forced.status_code == 200
    assert len(db_session.query(Document).all()) == 1


def test_canvas_trouble_is_a_502(client, db_session, tmp_corpus, monkeypatch):
    _setup(db_session, tmp_corpus)
    _canvas(monkeypatch, {"files/9003": 404})

    response = client.post("/api/agenda/materials/9003/fetch", json={})

    assert response.status_code == 502


def test_unknown_material_is_a_404(client, db_session, tmp_corpus, monkeypatch):
    _setup(db_session, tmp_corpus)
    _canvas(monkeypatch)

    assert client.post("/api/agenda/materials/1/fetch", json={}).status_code == 404


def test_a_course_without_corpus_cannot_receive_files(client, db_session, tmp_corpus, monkeypatch):
    db_session.add(CanvasCourse(id=59837, name="DSP"))
    db_session.add(CanvasFile(id=77, canvas_course_id=59837, filename="x.pdf", display_name="x.pdf"))
    db_session.commit()
    _canvas(monkeypatch, {"files/77": {"id": 77, "filename": "x.pdf", "url": "https://canvas.test/files/77/download"}, "/files/77/download": PDF})

    response = client.post("/api/agenda/materials/77/fetch", json={"doc_kind": "paper"})

    assert response.status_code == 400
    assert "canvas_id" in response.json()["detail"]


def test_ignoring_hides_a_file_until_you_change_your_mind(client, db_session, tmp_corpus):
    _setup(db_session, tmp_corpus)

    ignored = client.post("/api/agenda/materials/9010/ignore", json={"ignored": True})
    assert ignored.status_code == 200 and ignored.json()["state"] == "ignored"

    back = client.post("/api/agenda/materials/9010/ignore", json={"ignored": False})
    assert back.json()["state"] == "unplaced"
    assert client.post("/api/agenda/materials/1/ignore", json={"ignored": True}).status_code == 404


def test_a_file_already_in_the_corpus_is_recognised_by_name(client, db_session, tmp_corpus):
    _setup(db_session, tmp_corpus)
    db_session.add(Document(title="Lecture05", source_path="fundamentals-of-ds/slides/week-03/20260915_lecture05_classification.pdf",
                            checksum="x", course_slug="fundamentals-of-ds", doc_kind="slides", week=3, ingestion_status="indexed"))
    db_session.commit()

    course = next(entry for entry in client.get("/api/agenda").json()["courses"] if entry["canvas_id"] == FDS)

    assert next(m for m in course["materials"] if m["id"] == 9003)["state"] == "in_corpus"


# --- de opgave als tekst ---------------------------------------------------------

ASSIGNMENT_HTML = (
    "<h2>Part 1</h2><p>Analyse the UN General Debate corpus.</p>"
    "<h3>Question 1.1</h3><p>How many speeches are there?</p>"
)


def _sheet_setup(db, tmp_corpus, *, description: str = "Analyse the UN General Debate corpus."):
    _setup(db, tmp_corpus)
    # In course.yml en niet alleen op de rij: ingest leest course.yml opnieuw,
    # en die is de bron.
    (tmp_corpus / "fundamentals-of-ds" / "course.yml").write_text(
        "name: FDS\ncanvas_id: 59831\n"
        "assignments:\n  - name: Assignment 1\n    week: 4\n    due_date: 2026-09-28\n    points: 100\n"
        "weeks:\n  - week: 3\n    lectures: [5, 6]\n",
        encoding="utf-8",
    )
    corpus_sync.upsert_course_from_yaml(db, "fundamentals-of-ds", tmp_corpus)
    db.add_all(
        [
            CanvasItem(
                id="assignment:714239", canvas_course_id=FDS, kind="assignment", title="Assignment 1", submission={},
                submission_types=["online_upload"], description=description, due_at=datetime(2026, 9, 28, 21, 59),
                points_possible=100.0, html_url="https://canvas.test/courses/59831/assignments/714239",
            ),
            CanvasItem(id="assignment:9", canvas_course_id=FDS, kind="assignment", title="Assignment 9", submission={},
                       submission_types=["online_upload"], description="iets"),
            CanvasItem(id="quiz:1", canvas_course_id=FDS, kind="quiz", title="Quiz 1", submission={}, submission_types=[]),
        ]
    )
    db.commit()


def _assignment_route(html: str = ASSIGNMENT_HTML) -> dict:
    return {
        "courses/59831/assignments/714239": {
            "id": 714239, "name": "Assignment 1", "description": html, "due_at": "2026-09-28T21:59:00Z",
            "points_possible": 100.0, "html_url": "https://canvas.test/courses/59831/assignments/714239",
        }
    }


def test_an_assignment_without_a_pdf_is_fetched_as_text(client, db_session, tmp_corpus, monkeypatch):
    """Bij FDS is de opdracht de beschrijving in Canvas; er is geen pdf. Zonder
    dit ziet de coach de opgave niet."""
    _sheet_setup(db_session, tmp_corpus)
    _canvas(monkeypatch, _assignment_route())

    response = client.post("/api/agenda/items/assignment:714239/sheet", json={})

    assert response.status_code == 200, response.text
    document = response.json()["document"]
    assert document["source_path"] == "fundamentals-of-ds/assignments/week-04/Assignment-1.md"
    assert document["doc_kind"] == "assignment" and document["week"] == 4
    text = (tmp_corpus / "fundamentals-of-ds" / "assignments" / "week-04" / "Assignment-1.md").read_text(encoding="utf-8")
    assert text.startswith("# Assignment 1\n")
    assert "2026-09-28" in text and "Fundamentals of Data Science" in text
    assert "## Part 1" in text and "### Question 1.1" in text

    course = next(entry for entry in client.get("/api/agenda").json()["courses"] if entry["canvas_id"] == FDS)
    assert not [diff for diff in course["diffs"] if diff["kind"] == "assignment_sheet_missing" and diff["week"] == 4]


def test_the_missing_sheet_warning_says_whether_the_text_can_be_fetched(client, db_session, tmp_corpus):
    _sheet_setup(db_session, tmp_corpus)

    course = next(entry for entry in client.get("/api/agenda").json()["courses"] if entry["canvas_id"] == FDS)

    missing = next(diff for diff in course["diffs"] if diff["kind"] == "assignment_sheet_missing")
    assert missing["item_id"] == "assignment:714239"
    assert missing["can_fetch_text"] is True


def test_fetching_the_text_twice_needs_overwrite(client, db_session, tmp_corpus, monkeypatch):
    _sheet_setup(db_session, tmp_corpus)
    _canvas(monkeypatch, _assignment_route())
    assert client.post("/api/agenda/items/assignment:714239/sheet", json={}).status_code == 200

    assert client.post("/api/agenda/items/assignment:714239/sheet", json={}).status_code == 409
    assert client.post("/api/agenda/items/assignment:714239/sheet", json={"overwrite": True}).status_code == 200


@pytest.mark.parametrize(
    "item_id, status, hint",
    [
        ("quiz:1", 400, "opdracht"),
        ("assignment:9", 400, "course.yml"),
        ("assignment:404", 404, "item"),
    ],
)
def test_the_text_is_only_fetched_for_a_known_assignment(client, db_session, tmp_corpus, monkeypatch, item_id, status, hint):
    _sheet_setup(db_session, tmp_corpus)
    _canvas(monkeypatch, _assignment_route())

    response = client.post(f"/api/agenda/items/{item_id}/sheet", json={})

    assert response.status_code == status
    assert hint in response.json()["detail"].lower()


def test_an_empty_description_is_refused(client, db_session, tmp_corpus, monkeypatch):
    _sheet_setup(db_session, tmp_corpus)
    _canvas(monkeypatch, _assignment_route(html=""))

    response = client.post("/api/agenda/items/assignment:714239/sheet", json={})

    assert response.status_code == 400
    assert "beschrijving" in response.json()["detail"]


# --- pagina's -----------------------------------------------------------------

PAGE_HTML = "<p>Neem de afgeleide naar beta en stel die gelijk aan nul.</p><p><strong>Matrixvorm</strong></p><p>Met X'X beta = X'y.</p>"


def _page_setup(db, tmp_corpus):
    _setup(db, tmp_corpus)
    db.add(CanvasPage(id="59831:details-on-deriving", canvas_course_id=FDS, page_url="details-on-deriving",
                      title="Details on deriving least squares coefficients (Lecture 4)", module_name="Week 3"))
    db.add(CanvasCourse(id=59837, name="DSP"))
    db.add(CanvasPage(id="59837:intro", canvas_course_id=59837, page_url="intro", title="Intro", module_name=None))
    db.commit()


def _page_route(body: str = PAGE_HTML) -> dict:
    return {
        "courses/59831/pages/details-on-deriving": {
            "title": "Details on deriving least squares coefficients (Lecture 4)", "body": body,
            "html_url": "https://canvas.test/courses/59831/pages/details-on-deriving",
        }
    }


def test_pages_are_listed_with_their_proposal(client, db_session, tmp_corpus):
    _page_setup(db_session, tmp_corpus)

    course = next(entry for entry in client.get("/api/agenda").json()["courses"] if entry["canvas_id"] == FDS)

    page = course["pages"][0]
    assert page["id"] == "59831:details-on-deriving"
    assert page["state"] == "new"
    assert page["placement"]["relative_path"] == "fundamentals-of-ds/notes/week-03/Details-on-deriving-least-squares-coefficients-Lecture-4.md"


def test_fetching_a_page_puts_its_text_in_the_corpus(client, db_session, tmp_corpus, monkeypatch):
    _page_setup(db_session, tmp_corpus)
    _canvas(monkeypatch, _page_route())

    response = client.post("/api/agenda/pages/59831:details-on-deriving/fetch", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document"]["source_path"] == "fundamentals-of-ds/notes/week-03/Details-on-deriving-least-squares-coefficients-Lecture-4.md"
    assert body["page"]["state"] == "downloaded"
    text = (tmp_corpus / body["document"]["source_path"]).read_text(encoding="utf-8")
    assert text.startswith("# Details on deriving least squares coefficients (Lecture 4)\n")
    assert "## Matrixvorm" in text and "https://canvas.test/courses/59831/pages/details-on-deriving" in text
    assert db_session.get(CanvasPage, "59831:details-on-deriving").document_id == body["document"]["id"]


def test_an_empty_page_is_refused(client, db_session, tmp_corpus, monkeypatch):
    _page_setup(db_session, tmp_corpus)
    _canvas(monkeypatch, _page_route(body=""))

    response = client.post("/api/agenda/pages/59831:details-on-deriving/fetch", json={})

    assert response.status_code == 400
    assert "tekst" in response.json()["detail"]


def test_a_page_of_a_course_without_corpus_cannot_be_fetched(client, db_session, tmp_corpus, monkeypatch):
    _page_setup(db_session, tmp_corpus)
    _canvas(monkeypatch, {})

    assert client.post("/api/agenda/pages/59837:intro/fetch", json={}).status_code == 400
    assert client.post("/api/agenda/pages/1:onbekend/fetch", json={}).status_code == 404


def test_a_page_can_be_ignored(client, db_session, tmp_corpus):
    _page_setup(db_session, tmp_corpus)

    response = client.post("/api/agenda/pages/59831:details-on-deriving/ignore", json={"ignored": True})

    assert response.status_code == 200 and response.json()["state"] == "ignored"
    assert client.post("/api/agenda/pages/1:onbekend/ignore", json={"ignored": True}).status_code == 404
