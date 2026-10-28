"""De tab Tentamen. Getest wordt wat mechanisch is: het bestand met de analyse
wordt nagelopen, elke bron wordt teruggezocht in de geïndexeerde tekst, en de
punten per groep komen uit je eigen pogingen."""
from datetime import datetime

import pytest
import yaml
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import CanvasAnnouncement, Chunk, Course, Document, PracticeAttempt, PracticeCard
from app.services.study.exam_prep import (
    Source,
    build_exam_prep,
    check_sources,
    load_prep,
    standings,
)
from app.services.practice.practice_exams import ExamLayout


NOW = datetime(2026, 10, 16, 9, 0)
COURSE = "fundamentals-of-ds"

LAYOUT = {
    "title": "Tentamen 2026",
    "total_points": 12,
    "sections": [
        {"number": 1, "title": "Statistical Learning — Supervised Learning", "mc": 2, "mc_points": 1, "open": [4],
         "examples": ["3c"]},
        {"number": 2, "title": "Ethics and Data Science", "mc": 2, "mc_points": 1, "open": [2, 2]},
    ],
}

BLUEPRINT = {
    "id": "mock-exam-1",
    "title": "Mock Exam 1",
    "course": COURSE,
    "total_points": 1.5,
    "sections": [
        {"number": 3, "title": "Supervised Learning", "questions": [
            {"id": "3c", "page": 6, "type": "mc_single", "points": 1.5, "week": 3,
             "question": "Which is a supervised method?", "options": ["k-means", "logistic regression", "PCA", "DBSCAN"],
             "answer": ["b"]},
        ]},
    ],
}

SLIDE = (
    "Exam Combination of multiple choice and open questions — check Mock Exam (solutions available) "
    "Open questions: be direct and concise No access to extra materials"
)


def _source(**fields) -> dict:
    return {"path": "fundamentals-of-ds/slides/week-07/lecture13.pdf", "page": 8,
            "quote": "Open questions: be direct and concise", **fields}


def _prep(**overrides) -> dict:
    base = {
        "exam": {"duration_minutes": 120, "aids": [], "notes": ["Vakjes: meer dan één antwoord goed."]},
        "patterns": [{"id": "p1", "title": "Een maat uit een confusion matrix", "detail": "Elk jaar.",
                      "group": 1, "seen": 2, "of": 2, "sources": [_source()]}],
        "predictions": [{"id": "v1", "group": 2, "points": 2, "question": "Define demographic parity.",
                         "answer": "Equal positive rates across groups.", "why": "College 11.",
                         "sources": [_source()]}],
        "tactics": [{"id": "t1", "title": "Direct en beknopt", "detail": "Zo staat het in college 13.",
                     "sources": [_source()]}],
    }
    base.update(overrides)
    return base


def _write(tmp_corpus, name: str, data: dict) -> None:
    folder = tmp_corpus / COURSE / "exams"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _slides(db, text: str = SLIDE, pages=(8, 8)) -> Document:
    document = Document(
        title="Lecture13 exam preparation", source_path="fundamentals-of-ds/slides/week-07/lecture13.pdf",
        checksum="a" * 64, course_slug=COURSE, doc_kind="slides", week=7, ingestion_status="indexed",
    )
    document.chunks.append(Chunk(chunk_index=0, section_path="Lecture 13", page_start=pages[0], page_end=pages[1],
                                 token_count=30, text=text, normalized_text=text.lower(), chunk_metadata={}))
    db.add(document)
    db.commit()
    return document


def _card(db, *, origin: str, section: str, points: float, question_id: str | None = None) -> PracticeCard:
    spec = {"section": section, "section_number": int(section.split(" ", 1)[0])}
    if question_id:
        spec["question_id"] = question_id
    card = PracticeCard(
        course_slug=COURSE, document_id="d", chunk_id="c", section_path=f"{origin} › {section}",
        page_start=1, page_end=1, kind="open", question="?", reference_answer="!", spec=spec,
        points=points, origin=origin, position=0,
    )
    db.add(card)
    db.commit()
    return card


def _attempt(db, card: PracticeCard, score: float, when: datetime) -> None:
    db.add(PracticeAttempt(card_id=card.id, given_answer="x", correct=score > 0, score=score,
                           max_score=card.points, created_at=when))
    db.commit()


# --- het bestand ----------------------------------------------------------------


def test_a_valid_preparation_file_loads_without_problems(tmp_path):
    path = tmp_path / "voorbereiding.yml"
    path.write_text(yaml.safe_dump(_prep()), encoding="utf-8")

    prep, problems = load_prep(path, groups={1, 2})

    assert problems == []
    assert prep.exam.duration_minutes == 120
    assert [item.id for item in prep.patterns] == ["p1"]
    assert prep.predictions[0].answer.startswith("Equal")


def test_the_file_reports_what_does_not_add_up(tmp_path):
    """Een groep die niet in de opbouw staat, een dubbele id, meer keren gezien
    dan bekeken, en een bewering zonder bron: alle vier gemeld, niet stil
    weggelaten — de rest van het bestand blijft bruikbaar."""
    path = tmp_path / "voorbereiding.yml"
    path.write_text(yaml.safe_dump(_prep(
        patterns=[
            {"id": "p1", "title": "A", "group": 7, "seen": 3, "of": 2, "sources": [_source()]},
            {"id": "p1", "title": "B", "sources": []},
        ],
    )), encoding="utf-8")

    prep, problems = load_prep(path, groups={1, 2})

    assert prep is not None
    joined = " | ".join(problems)
    assert "groep 7" in joined
    assert "p1" in joined and "twee keer" in joined
    assert "3 van 2" in joined
    assert "zonder bron" in joined


def test_unknown_keys_make_the_file_invalid(tmp_path):
    """Een tikfout in een sleutel (`sourcse`) zou anders een bewering zonder
    bron opleveren die er mét bron uitziet in het bestand."""
    path = tmp_path / "voorbereiding.yml"
    path.write_text(yaml.safe_dump(_prep(tactics=[{"id": "t1", "title": "x", "sourcse": []}])), encoding="utf-8")

    prep, problems = load_prep(path, groups=None)

    assert prep is None
    assert problems and "voorbereiding.yml" in problems[0]


def test_a_source_names_a_document_or_an_announcement():
    with pytest.raises(ValueError):
        Source(quote="iets")
    with pytest.raises(ValueError):
        Source(path="a.pdf", announcement="b", quote="iets")


def _plan(**overrides) -> list[dict]:
    step = {"id": "s1", "day": "dinsdag 20 oktober", "title": "Oefententamen 4 op tijd", "minutes": 90,
            "detail": "Op papier, 88 minuten.", "exam": "oefententamen-4",
            "links": [{"label": "Maak het", "href": "/oefenen?course=fundamentals-of-ds&exam=oefententamen-4"},
                      {"label": "Lab 7", "href": "https://canvas.uva.nl/courses/59831/files/15868362"}]}
    step.update(overrides)
    return [step]


def test_a_plan_says_what_to_do_in_which_order(tmp_path):
    path = tmp_path / "voorbereiding.yml"
    path.write_text(yaml.safe_dump(_prep(plan=_plan())), encoding="utf-8")

    prep, problems = load_prep(path, groups={1, 2})

    assert problems == []
    (step,) = prep.plan
    assert (step.day, step.minutes, step.exam) == ("dinsdag 20 oktober", 90, "oefententamen-4")
    assert [link.label for link in step.links] == ["Maak het", "Lab 7"]


def test_plan_ids_share_the_namespace_of_the_analysis(tmp_path):
    path = tmp_path / "voorbereiding.yml"
    path.write_text(yaml.safe_dump(_prep(plan=_plan(id="p1"))), encoding="utf-8")

    _, problems = load_prep(path, groups=None)

    assert any("p1" in problem and "twee keer" in problem for problem in problems)


def test_a_plan_step_names_the_slides_to_read(tmp_path):
    """Naast de stof (opgaven, uitwerking) de slides die erbij horen, als eigen
    rij: "College 3 · p. 12–23" zegt waar je moet kijken."""
    slides = [{"label": "College 3 · p. 12–23 (Welch)", "href": "https://canvas.uva.nl/courses/59863/files/15925147"}]
    path = tmp_path / "voorbereiding.yml"
    path.write_text(yaml.safe_dump(_prep(plan=_plan(slides=slides))), encoding="utf-8")

    prep, problems = load_prep(path, groups=None)

    assert problems == []
    assert [link.label for link in prep.plan[0].slides] == ["College 3 · p. 12–23 (Welch)"]


def test_an_unsafe_slide_link_makes_the_file_invalid(tmp_path):
    path = tmp_path / "voorbereiding.yml"
    path.write_text(yaml.safe_dump(_prep(plan=_plan(slides=[{"label": "x", "href": "//elders.example/slides"}]))),
                    encoding="utf-8")

    prep, problems = load_prep(path, groups=None)

    assert prep is None and problems


def test_an_unsafe_link_in_the_plan_makes_the_file_invalid(tmp_path):
    """Dezelfde regel als bij de knoppen van een agendataak: een link wordt een
    href, dus geen `javascript:` en geen ander domein via `//`."""
    path = tmp_path / "voorbereiding.yml"
    path.write_text(yaml.safe_dump(_prep(plan=_plan(links=[{"label": "x", "href": "javascript:alert(1)"}]))), encoding="utf-8")

    prep, problems = load_prep(path, groups=None)

    assert prep is None and problems


def _rule(**overrides) -> dict:
    rule = {"id": "r1", "group": 1, "new": False,
            "see": "Een claim over een percentage: 'at most 8%'.",
            "do": "One-sample proportion test, H0 met de gelijkheid.",
            "points": "2022 1a: 0,2 hypothesen, 0,2 toets, 0,1 T.",
            "trap": "p0 in de toetsingsgrootheid, p-hoed in het interval.",
            "sources": [_source()]}
    rule.update(overrides)
    return rule


def test_recognition_rules_load_with_their_parts(tmp_path):
    """Een regel zegt wat je in de vraag ziet, wat je dan doet, waar de punten
    zitten en wat de valkuil is; dezelfde bronregels als de rest van de analyse."""
    path = tmp_path / "voorbereiding.yml"
    path.write_text(yaml.safe_dump(_prep(rules=[_rule(), _rule(id="r2", new=True, points="", trap="", group=2)])),
                    encoding="utf-8")

    prep, problems = load_prep(path, groups={1, 2})

    assert problems == []
    first, second = prep.rules
    assert first.see.startswith("Een claim") and first.do and first.points and first.trap
    assert second.new is True and second.points == ""


def test_a_rule_without_a_source_or_with_an_unknown_group_is_reported(tmp_path):
    path = tmp_path / "voorbereiding.yml"
    path.write_text(yaml.safe_dump(_prep(rules=[_rule(sources=[]), _rule(id="r2", group=9)])), encoding="utf-8")

    _, problems = load_prep(path, groups={1, 2})

    assert any("r1" in problem and "zonder bron" in problem for problem in problems)
    assert any("groep 9" in problem for problem in problems)


# --- bronnen ----------------------------------------------------------------------


def test_a_quote_that_is_in_the_indexed_text_is_found(db_session):
    _slides(db_session)

    (check,) = check_sources(db_session, COURSE, [Source(**_source())])

    assert check.found
    assert check.label == "Lecture13 exam preparation, p. 8"


def test_a_quote_is_found_through_hyphenation_and_spacing(db_session):
    _slides(db_session, text="Open ques- tions:   be DIRECT and concise.")

    (check,) = check_sources(db_session, COURSE, [Source(**_source())])

    assert check.found


def test_a_quote_on_another_page_or_not_in_the_text_is_not_found(db_session):
    _slides(db_session)

    andere_pagina, verzonnen, kort, onbekend = check_sources(db_session, COURSE, [
        Source(**_source(page=3)),
        Source(**_source(quote="The exam is open book and you may bring notes")),
        Source(**_source(quote="exam")),
        Source(**_source(path="fundamentals-of-ds/slides/week-07/bestaat-niet.pdf")),
    ])

    assert not andere_pagina.found and "pagina" in andere_pagina.reason
    assert not verzonnen.found and "niet gevonden" in verzonnen.reason
    assert not kort.found and "te kort" in kort.reason
    assert not onbekend.found and "niet in de index" in onbekend.reason


def test_an_announcement_is_a_source_too(db_session):
    db_session.add(Course(slug="sso", name="SSO", canvas_id=59863))
    db_session.add(CanvasAnnouncement(
        id=1, canvas_course_id=59863, title="Question hour and exam preparation", posted_at=NOW,
        body="<p>The <b>question hour</b> is on Monday 19 October from 13:00 to 14:45 via Zoom.</p>",
        html_url="https://canvas.uva.nl/courses/59863/discussion_topics/1", fetched_at=NOW,
    ))
    db_session.commit()

    (check,) = check_sources(db_session, "sso", [
        Source(announcement="question hour", quote="is on Monday 19 October from 13:00 to 14:45"),
    ])

    assert check.found
    assert check.label == "Aankondiging: Question hour and exam preparation"
    assert check.href.startswith("https://canvas.uva.nl/")


# --- waar liggen je punten ---------------------------------------------------------


def test_points_per_group_come_from_your_last_attempts(db_session):
    """De mock-vraag 3c hoort via `examples` bij groep 1, al heet zijn sectie
    anders; een oefententamen in de opbouw van 2026 via zijn titel. De laatste
    poging telt, net als in het overzicht van de oefententamens."""
    layout = ExamLayout.model_validate(LAYOUT)
    mock = _card(db_session, origin="mock-exam-1", section="3 Supervised Learning", points=1.5, question_id="3c")
    open_vraag = _card(db_session, origin="oefententamen-3", section="1 Statistical Learning — Supervised Learning", points=4)
    ethiek = _card(db_session, origin="oefententamen-3", section="2 Ethics and Data Science", points=2)
    _attempt(db_session, mock, 0.0, datetime(2026, 10, 10))
    _attempt(db_session, mock, 1.5, datetime(2026, 10, 12))
    _attempt(db_session, open_vraag, 1.0, datetime(2026, 10, 12))

    groups = standings(db_session, COURSE, layout, blueprint_id="mock-exam-1")

    by_number = {group.number: group for group in groups}
    supervised = by_number[1]
    assert supervised.points == 6
    assert (supervised.mc_points, supervised.open_points) == (1, [4.0])
    assert supervised.answered == 2
    assert supervised.answered_points == 5.5
    assert supervised.scored == 2.5
    assert supervised.to_gain == pytest.approx(6 * (1 - 2.5 / 5.5))
    # Ethiek heeft een kaart maar geen poging: nog niet geoefend, met zijn
    # volle waarde te winnen — en dus bovenaan.
    assert by_number[2].answered == 0 and by_number[2].share is None
    assert by_number[2].to_gain == 6
    assert [group.number for group in groups] == [2, 1]
    assert ethiek.id  # de kaart bestaat, maar telt pas na een poging


def test_question_ids_only_map_through_examples_for_the_blueprint(db_session):
    """`examples` noemt vragen van het proeftentamen. Een andere transcriptie
    met toevallig dezelfde id ("3c") hoort er niet bij te worden geteld."""
    layout = ExamLayout.model_validate(LAYOUT)
    andere = _card(db_session, origin="college-13", section="9 Iets anders", points=1, question_id="3c")
    _attempt(db_session, andere, 1.0, datetime(2026, 10, 12))

    groups = standings(db_session, COURSE, layout, blueprint_id="mock-exam-1")

    assert all(group.answered == 0 for group in groups)


# --- alles samen, en de route ---------------------------------------------------------


def _course(db):
    db.add(Course(slug=COURSE, name="FDS", exams=[{"name": "Tentamen FDS", "date": "2026-10-21"}]))
    db.commit()


def test_the_page_works_without_a_preparation_file(db_session, tmp_corpus):
    _course(db_session)
    _write(tmp_corpus, "mock-exam-1.yml", BLUEPRINT)
    _write(tmp_corpus, "opbouw.yml", LAYOUT)

    prep = build_exam_prep(db_session, COURSE, now=NOW)

    assert prep.has_file is False
    assert prep.exam.days_left == 5
    assert prep.total_points == 12
    assert [group.number for group in prep.groups] == [1, 2]
    assert prep.patterns == [] and prep.problems == []


def test_minutes_per_point_follow_duration_and_total(db_session, tmp_corpus):
    _course(db_session)
    _slides(db_session)
    _write(tmp_corpus, "mock-exam-1.yml", BLUEPRINT)
    _write(tmp_corpus, "opbouw.yml", LAYOUT)
    _write(tmp_corpus, "voorbereiding.yml", _prep())

    prep = build_exam_prep(db_session, COURSE, now=NOW)

    assert prep.has_file is True
    assert prep.minutes_per_point == 10
    pattern, checks = prep.patterns[0]
    assert pattern.id == "p1" and checks[0].found


def test_a_plan_step_with_an_unknown_exam_is_reported(db_session, tmp_corpus):
    """Een stap die naar een oefententamen wijst dat er niet (meer) is, toont geen
    voortgang; dat moet je zien, niet raden."""
    _course(db_session)
    _write(tmp_corpus, "mock-exam-1.yml", BLUEPRINT)
    _write(tmp_corpus, "opbouw.yml", LAYOUT)
    _write(tmp_corpus, "voorbereiding.yml", _prep(plan=_plan()))

    prep = build_exam_prep(db_session, COURSE, now=NOW)

    assert [step.id for step in prep.plan] == ["s1"]
    assert any("oefententamen-4" in problem for problem in prep.problems)


def test_rules_come_back_with_checked_sources(db_session, tmp_corpus):
    _course(db_session)
    _slides(db_session)
    _write(tmp_corpus, "mock-exam-1.yml", BLUEPRINT)
    _write(tmp_corpus, "opbouw.yml", LAYOUT)
    _write(tmp_corpus, "voorbereiding.yml", _prep(rules=[_rule()]))

    prep = build_exam_prep(db_session, COURSE, now=NOW)

    ((rule, checks),) = prep.rules
    assert rule.id == "r1" and checks[0].found
    # Het nalopen gaat in één keer voor alle blokken; de regels mogen de
    # bronnen van de andere blokken niet verschuiven.
    assert prep.tactics[0][1][0].found


@pytest.fixture()
def client(db_session, tmp_corpus):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_the_route_returns_the_whole_page(client, db_session, tmp_corpus):
    _course(db_session)
    _slides(db_session)
    _write(tmp_corpus, "mock-exam-1.yml", BLUEPRINT)
    _write(tmp_corpus, "opbouw.yml", LAYOUT)
    _write(tmp_corpus, "voorbereiding.yml", _prep())

    response = client.get("/api/exam-prep", params={"course_slug": COURSE})

    assert response.status_code == 200
    body = response.json()
    assert body["facts"]["duration_minutes"] == 120
    assert body["groups"][0]["title"]
    assert body["patterns"][0]["sources"][0]["found"] is True
    assert body["predictions"][0]["answer"].startswith("Equal")
    assert body["tactics"][0]["title"] == "Direct en beknopt"
    assert body["exam_sets"] == []
    assert body["plan"] == []
    assert body["rules"] == []


def test_the_route_refuses_an_unknown_course(client):
    response = client.get("/api/exam-prep", params={"course_slug": "bestaat-niet"})

    assert response.status_code == 404
