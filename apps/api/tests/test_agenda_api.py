from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.routes import agenda as agenda_route
from app.db import get_db
from app.main import app
from app.models import CanvasCourse, CanvasItem, Task
from app.services.canvas.client import CanvasClient
from tests.canvas_fixtures import FDS, OLD, routes
from tests.canvas_stub import canvas_opener


NOW = datetime(2026, 9, 17, 8, 0)


@pytest.fixture()
def client(db_session, tmp_corpus, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db_session
    # Een vaste klok: "volgende week" mag niet afhangen van de dag waarop de
    # tests draaien.
    monkeypatch.setattr(agenda_route, "_now", lambda: NOW)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _stub_canvas(monkeypatch, fixture: dict | None = None):
    stub = canvas_opener(fixture or routes())
    monkeypatch.setattr(
        agenda_route, "_client", lambda: CanvasClient(base_url="https://canvas.test", token="t", opener=stub)
    )
    return stub


def test_agenda_works_without_canvas(client):
    response = client.get("/api/agenda")

    assert response.status_code == 200
    body = response.json()
    assert body["canvas"] == {"configured": False, "synced_at": None, "stale": True}
    assert body["items"] == [] and body["tasks"] == []


def test_sync_without_configuration_is_a_400_with_a_hint(client):
    response = client.post("/api/agenda/sync")

    assert response.status_code == 400
    assert "CANVAS_ACCESS_TOKEN" in response.json()["detail"]


def test_sync_fills_the_agenda(client, monkeypatch):
    _stub_canvas(monkeypatch)

    response = client.post("/api/agenda/sync")

    assert response.status_code == 200
    body = response.json()
    assert body["courses"] == 3 and body["items"] == 8
    assert body["synced_at"].endswith("Z")
    agenda = client.get("/api/agenda").json()
    assert agenda["canvas"]["configured"] is True
    assert agenda["canvas"]["stale"] is False
    assert {course["canvas_id"] for course in agenda["courses"]} == {FDS, 59863, OLD}
    assert any(item["id"] == "assignment:714239" for item in agenda["items"])


def test_a_canvas_failure_is_a_502_and_keeps_the_snapshot(client, monkeypatch, db_session):
    _stub_canvas(monkeypatch)
    client.post("/api/agenda/sync")
    fixture = routes()
    fixture["courses"] = 401
    _stub_canvas(monkeypatch, fixture)

    response = client.post("/api/agenda/sync")

    assert response.status_code == 502
    assert "401" in response.json()["detail"]
    assert "t" != response.json()["detail"]
    assert len(client.get("/api/agenda").json()["items"]) == 8


def test_a_course_can_be_hidden_and_shown_again(client, db_session):
    db_session.add(CanvasCourse(id=OLD, name="oud"))
    db_session.commit()

    response = client.patch(f"/api/agenda/courses/{OLD}", json={"hidden": True})

    assert response.status_code == 200
    assert response.json()["hidden"] is True
    assert client.patch(f"/api/agenda/courses/{OLD}", json={"hidden": False}).json()["hidden"] is False
    assert client.patch("/api/agenda/courses/1", json={"hidden": True}).status_code == 404


def test_an_item_can_be_ticked_off_locally(client, db_session):
    db_session.add(CanvasCourse(id=FDS, name="FDS"))
    db_session.add(
        CanvasItem(id="assignment:714241", canvas_course_id=FDS, kind="exam", title="Final Exam", submission={},
                   submission_types=["on_paper"])
    )
    db_session.commit()

    response = client.patch("/api/agenda/items/assignment:714241", json={"done": True})

    assert response.status_code == 200
    assert response.json()["status"] == "done" and response.json()["done_at"] is not None
    assert client.patch("/api/agenda/items/assignment:714241", json={"done": False}).json()["status"] != "done"
    assert client.patch("/api/agenda/items/assignment:1", json={"done": True}).status_code == 404


def test_an_item_ticked_in_canvas_can_be_untucked_here(client, db_session):
    """Zonder deze weg is zo'n item voorgoed uit de lijst: het token kan in
    Canvas niets uitvinken."""
    db_session.add(CanvasCourse(id=FDS, name="FDS"))
    db_session.add(
        CanvasItem(id="assignment:714242", canvas_course_id=FDS, kind="assignment", title="Assignment 1",
                   submission={}, submission_types=["online_upload"], marked_complete=True,
                   due_at=datetime(2026, 9, 28, 21, 59))
    )
    db_session.commit()

    back = client.patch("/api/agenda/items/assignment:714242", json={"done": False})

    assert back.status_code == 200
    assert back.json()["status"] == "open" and back.json()["done_at"] is None
    assert any(item["id"] == "assignment:714242" for item in client.get("/api/agenda").json()["items"])
    # Opnieuw afvinken laat Canvas weer gelden.
    again = client.patch("/api/agenda/items/assignment:714242", json={"done": True})
    assert again.json()["status"] == "done"
    assert db_session.get(CanvasItem, "assignment:714242").unmarked_at is None


def test_tasks_can_be_created_updated_and_deleted(client, db_session):
    created = client.post("/api/agenda/tasks", json={"title": "Sectie 3 maken", "due_on": "2026-09-24", "course_slug": "fundamentals-of-ds"})

    assert created.status_code == 201
    task = created.json()
    assert task["bucket"] == "next_week" and task["done_at"] is None

    done = client.patch(f"/api/agenda/tasks/{task['id']}", json={"done": True})
    assert done.json()["done_at"] is not None and done.json()["bucket"] == "done"

    # Een datum wissen is iets anders dan hem niet noemen.
    cleared = client.patch(f"/api/agenda/tasks/{task['id']}", json={"due_on": None, "done": False})
    assert cleared.json()["due_on"] is None and cleared.json()["bucket"] == "undated"
    untouched = client.patch(f"/api/agenda/tasks/{task['id']}", json={"title": "Sectie 3 en 4 maken"})
    assert untouched.json()["due_on"] is None and untouched.json()["title"] == "Sectie 3 en 4 maken"

    deleted = client.delete(f"/api/agenda/tasks/{task['id']}")
    assert deleted.status_code == 200
    assert db_session.get(Task, task["id"]).deleted_at is not None
    assert client.delete(f"/api/agenda/tasks/{task['id']}").status_code == 404


def test_a_deleted_task_can_be_restored(client, db_session):
    """Verwijderen is één klik zonder bevestiging; dan moet het terug kunnen,
    ook nog na een herlaadbeurt. Vandaar een kolom en geen harde delete."""
    task = client.post("/api/agenda/tasks", json={"title": "Sectie 3 maken", "due_on": "2026-09-24"}).json()

    client.delete(f"/api/agenda/tasks/{task['id']}")
    assert not any(row["id"] == task["id"] for row in client.get("/api/agenda").json()["tasks"])

    restored = client.post(f"/api/agenda/tasks/{task['id']}/restore")

    assert restored.status_code == 200
    assert restored.json()["id"] == task["id"] and restored.json()["created_at"] == task["created_at"]
    assert any(row["id"] == task["id"] for row in client.get("/api/agenda").json()["tasks"])
    # Terughalen van een taak die er gewoon staat verandert niets.
    assert client.post(f"/api/agenda/tasks/{task['id']}/restore").status_code == 200
    assert client.post("/api/agenda/tasks/onbekend/restore").status_code == 404


def test_a_deleted_task_is_gone_for_every_other_route(client, db_session):
    task = client.post("/api/agenda/tasks", json={"title": "Sectie 3 maken"}).json()
    client.delete(f"/api/agenda/tasks/{task['id']}")

    assert client.patch(f"/api/agenda/tasks/{task['id']}", json={"done": True}).status_code == 404
    assert client.delete(f"/api/agenda/tasks/{task['id']}").status_code == 404


def test_an_empty_task_title_is_refused(client):
    assert client.post("/api/agenda/tasks", json={"title": "   "}).status_code == 422


def test_a_ticked_task_stays_on_its_day(client):
    """Het vinkje zegt dat het af is (bucket "done", dus niet meer in de
    telling van de navigatiebalk), maar de rij blijft staan waar hij stond."""
    task = client.post("/api/agenda/tasks", json={"title": "Huiswerk college 8", "due_on": NOW.date().isoformat()}).json()
    assert task["place"] == "today"

    done = client.patch(f"/api/agenda/tasks/{task['id']}", json={"done": True}).json()

    assert done["bucket"] == "done"
    assert done["place"] == "today"
    listed = next(row for row in client.get("/api/agenda").json()["tasks"] if row["id"] == task["id"])
    assert listed["place"] == "today"


def test_yesterdays_task_ticked_today_stays_with_the_late_ones_for_today(client):
    yesterday = date(2026, 9, 16).isoformat()
    task = client.post("/api/agenda/tasks", json={"title": "Huiswerk college 8", "due_on": yesterday}).json()
    assert task["place"] == "overdue"

    done = client.patch(f"/api/agenda/tasks/{task['id']}", json={"done": True}).json()

    assert done["bucket"] == "done"
    assert done["place"] == "overdue"


def test_a_task_carries_named_links_to_what_you_need(client):
    """Een studietaak wijst naar meer dan één plek — de opgaven, de uitwerking,
    een hint — en elke knop moet zeggen waar hij heen gaat. De titel als
    enige link zag eruit als gewone tekst."""
    links = [
        {"label": "Opgaven college 8", "href": "https://uva-sso.github.io/simopt-lecture-notes/"},
        {"label": "Hint van de coach", "href": "/?course=sso&coach=abc"},
    ]
    task = client.post("/api/agenda/tasks", json={"title": "Huiswerk college 8", "links": links}).json()

    assert task["links"] == links
    listed = next(row for row in client.get("/api/agenda").json()["tasks"] if row["id"] == task["id"])
    assert listed["links"] == links

    # Alleen wat in het verzoek staat verandert: zonder `links` blijven ze staan.
    renamed = client.patch(f"/api/agenda/tasks/{task['id']}", json={"title": "Huiswerk college 8 (2 u)"}).json()
    assert renamed["links"] == links
    replaced = client.patch(f"/api/agenda/tasks/{task['id']}", json={"links": links[:1]}).json()
    assert replaced["links"] == links[:1]


def test_a_task_without_links_reads_as_an_empty_list(client):
    task = client.post("/api/agenda/tasks", json={"title": "Sectie 3 maken"}).json()

    assert task["links"] == []


@pytest.mark.parametrize("href", ["javascript:alert(1)", "http://example.com", "//example.com/pad", "oefenen", "data:text/html,x"])
def test_a_link_goes_into_the_app_or_to_an_https_page(client, href):
    """Een link wordt een href in de pagina: een pad binnen de app of een
    https-adres, en niets wat de browser als code of als ander domein leest."""
    bad_links = client.post("/api/agenda/tasks", json={"title": "x", "links": [{"label": "Open", "href": href}]})
    bad_link = client.post("/api/agenda/tasks", json={"title": "x", "link": href})

    assert bad_links.status_code == 422
    assert bad_link.status_code == 422


def test_a_link_needs_a_name_and_a_task_holds_a_handful(client):
    nameless = [{"label": "  ", "href": "/weken"}]
    seven = [{"label": f"Knop {i}", "href": "/weken"} for i in range(7)]

    assert client.post("/api/agenda/tasks", json={"title": "x", "links": nameless}).status_code == 422
    assert client.post("/api/agenda/tasks", json={"title": "x", "links": seven}).status_code == 422
