"""Scenario's: per patroon uit "Wat zeker terugkomt" de varianten die je op het
tentamen kunt verwachten, als oefenkaarten.

Ze staan in `exams/scenarios.yml`, in het formaat van een transcriptie, en gaan
door dezelfde controles. Daarbovenop: elk getal van een open rekenvraag wordt
nagerekend en moet in het modelantwoord staan, want deze vragen zijn niet van
een docent overgenomen maar bedacht.
"""
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from app.models import PracticeAttempt, PracticeCard
from app.services.practice import exams
from app.services.practice.exams import (
    SCENARIOS_FILE,
    exam_progress,
    import_course_exams,
    import_exam,
    transcription_paths,
)
from app.services.practice.practice_exams import ExamLayout
from app.services.study.exam_prep import scenarios_by_pattern, standings


COURSE = "sso"


def _scenarios(**overrides) -> dict:
    base = {
        "id": "scenarios-sso",
        "title": "Scenario's SSO",
        "course": COURSE,
        "total_points": 1.0,
        "sections": [
            {
                "number": 1,
                "title": "Proportie: z-toets, interval en steekproefgrootte",
                "pattern": "p1",
                "questions": [
                    {
                        "id": "p1-a",
                        "page": 1,
                        "type": "open",
                        "points": 0.5,
                        "week": 1,
                        "topic": "linkszijdig toetsen: de claim is 'minstens'",
                        "question": "A company claims at least 90% ... 215 of n = 252. Compute T.",
                        "model_answer": "H0: p >= 0.9 against H1: p < 0.9. T = -2.48.",
                        "rubric": [
                            {"criterion": "Hypotheses.", "points": 0.3},
                            {"criterion": "T = -2.48.", "points": 0.2},
                        ],
                        "checks": [
                            {"label": "T", "setup": "n = 252\nx = 215", "expression": "(x / n - 0.9) / (0.9 * 0.1 / n) ** 0.5"},
                        ],
                    },
                    {
                        "id": "p1-b",
                        "page": 1,
                        "type": "open",
                        "points": 0.5,
                        "week": 1,
                        "topic": "steekproefgrootte: naar boven afronden",
                        "question": "How large should n be for a margin of 0.02 at 95%? Use 1.96.",
                        "model_answer": "n >= 1.96^2 * 0.88 * 0.12 / 0.02^2 = 1014.18, so n = 1015.",
                        "rubric": [{"criterion": "n = 1015.", "points": 0.5}],
                    },
                ],
            }
        ],
    }
    base.update(overrides)
    return base


def _write(folder: Path, data: dict, name: str = SCENARIOS_FILE) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _first_question(data: dict) -> dict:
    return data["sections"][0]["questions"][0]


# --- het bestand ----------------------------------------------------------------


def test_scenarios_worden_kaarten_met_hun_patroon(db_session, tmp_path):
    report = import_exam(db_session, _write(tmp_path, _scenarios()))

    assert (report.created, report.problems) == (2, [])
    kaarten = db_session.query(PracticeCard).order_by(PracticeCard.position).all()
    assert [card.spec["pattern"] for card in kaarten] == ["p1", "p1"]
    assert {card.origin for card in kaarten} == {"scenarios-sso"}
    assert kaarten[0].spec["section_number"] == 1


def test_een_scenario_hoort_bij_een_patroon(db_session, tmp_path):
    data = _scenarios()
    del data["sections"][0]["pattern"]

    report = import_exam(db_session, _write(tmp_path, data))

    assert any("patroon" in problem for problem in report.problems)
    assert db_session.query(PracticeCard).count() == 0


def test_een_narekening_moet_in_het_modelantwoord_staan(db_session, tmp_path):
    """Bedachte vragen hebben geen uitwerking van een docent: een rekenfout in
    het modelantwoord leer je anders gewoon aan."""
    data = _scenarios()
    _first_question(data)["model_answer"] = "H0: p >= 0.9 against H1: p < 0.9. T = -2.84."

    report = import_exam(db_session, _write(tmp_path, data))

    assert any("'T'" in problem and "-2.478" in problem for problem in report.problems)
    assert db_session.query(PracticeCard).count() == 0


def test_een_narekening_zonder_getal_wordt_geweigerd(db_session, tmp_path):
    data = _scenarios()
    _first_question(data)["checks"] = [{"label": "T", "setup": "", "expression": "'geen getal'"}]

    report = import_exam(db_session, _write(tmp_path, data))

    assert any("'T'" in problem for problem in report.problems)


def test_ongewijzigd_opnieuw_importeren_rekent_niets_na(db_session, tmp_path, monkeypatch):
    """Een narekening met scipy kost een seconde; honderd per vak bij elke sync
    zou de sync een halve minuut langer maken voor niets."""
    path = _write(tmp_path, _scenarios())
    import_exam(db_session, path)

    aanroepen: list[str] = []
    echte = exams.evaluate
    monkeypatch.setattr(exams, "evaluate", lambda setup, expression: aanroepen.append(expression) or echte(setup, expression))
    report = import_exam(db_session, path)

    assert (report.unchanged, aanroepen) == (2, [])


def test_een_veranderde_narekening_wordt_opnieuw_nagerekend(db_session, tmp_path, monkeypatch):
    data = _scenarios()
    import_exam(db_session, _write(tmp_path, data))
    _first_question(data)["checks"][0]["setup"] = "n = 252\nx = 215.0"

    aanroepen: list[str] = []
    echte = exams.evaluate
    monkeypatch.setattr(exams, "evaluate", lambda setup, expression: aanroepen.append(expression) or echte(setup, expression))
    report = import_exam(db_session, _write(tmp_path, data))

    assert (report.updated, len(aanroepen)) == (1, 1)


def test_scenarios_zijn_geen_transcriptie_maar_worden_wel_geimporteerd(db_session, tmp_corpus):
    """Als transcriptie gelezen zou het grootste bestand het model voor elk
    oefententamen worden, en zouden bedachte vragen als stijlvoorbeeld dienen."""
    folder = tmp_corpus / COURSE / "exams"
    _write(folder, _scenarios())

    assert transcription_paths(folder) == []
    reports = import_course_exams(db_session, COURSE, tmp_corpus)
    assert [report.exam_id for report in reports] == ["scenarios-sso"]
    assert db_session.query(PracticeCard).count() == 2


# --- waar ze wel en niet meetellen ----------------------------------------------------


def _attempt(db, card: PracticeCard, score: float, when: datetime) -> None:
    db.add(PracticeAttempt(card_id=card.id, given_answer="x", correct=score > 0, score=score,
                           max_score=card.points, created_at=when))
    db.commit()


def test_scenarios_staan_niet_tussen_de_oefententamens(db_session, tmp_path):
    import_exam(db_session, _write(tmp_path, _scenarios()))

    assert exam_progress(db_session, COURSE) == []


def test_scenarios_tellen_niet_mee_bij_waar_je_punten_liggen(db_session, tmp_path):
    """Die tabel schat je score op het tentamen uit echte tentamenvragen; een
    scenario dat je net drie keer oefende zou hem rooskleuriger maken."""
    data = _scenarios()
    data["sections"][0]["title"] = "Statistical testing and estimation"
    import_exam(db_session, _write(tmp_path, data))
    kaart = db_session.query(PracticeCard).first()
    _attempt(db_session, kaart, 0.5, datetime(2026, 10, 17))
    layout = ExamLayout.model_validate({
        "title": "SSO 2026", "total_points": 2,
        "sections": [{"number": 1, "title": "Statistical testing and estimation", "mc": 0, "open": [0.5, 0.5, 0.5, 0.5]}],
    })

    groups = standings(db_session, COURSE, layout, blueprint_id=None)

    assert groups[0].answered == 0


def test_per_patroon_de_scenarios_met_je_laatste_poging(db_session, tmp_path):
    import_exam(db_session, _write(tmp_path, _scenarios()))
    eerste, tweede = db_session.query(PracticeCard).order_by(PracticeCard.position).all()
    _attempt(db_session, eerste, 0.2, datetime(2026, 10, 16))
    _attempt(db_session, eerste, 0.5, datetime(2026, 10, 17))

    per_patroon = scenarios_by_pattern(db_session, COURSE)

    rijen = per_patroon["p1"]
    assert [rij.question_id for rij in rijen] == ["p1-a", "p1-b"]
    assert rijen[0].topic == "linkszijdig toetsen: de claim is 'minstens'"
    assert (rijen[0].last_score, rijen[0].points) == (0.5, 0.5)
    assert rijen[1].last_score is None
    assert (rijen[0].origin, rijen[0].section_number) == ("scenarios-sso", 1)
    assert tweede.id == rijen[1].card_id


def test_de_route_geeft_per_patroon_de_scenarios_en_waar_je_ze_oefent(db_session, tmp_corpus):
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app
    from app.models import Course

    db_session.add(Course(slug=COURSE, name="SSO"))
    db_session.commit()
    folder = tmp_corpus / COURSE / "exams"
    _write(folder, {
        "exam": {"duration_minutes": 120},
        "patterns": [{"id": "p1", "title": "Proportie", "sources": [{"path": "sso/x.pdf", "quote": "een citaat van twintig tekens"}]}],
        "predictions": [], "tactics": [],
    }, name="voorbereiding.yml")
    import_exam(db_session, _write(folder, _scenarios()))

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            body = client.get("/api/exam-prep", params={"course_slug": COURSE}).json()
    finally:
        app.dependency_overrides.clear()

    patroon = body["patterns"][0]
    assert [rij["question_id"] for rij in patroon["scenarios"]] == ["p1-a", "p1-b"]
    assert patroon["practice"] == {"origin": "scenarios-sso", "section": 1}


def test_een_ingevoegd_scenario_laat_je_pogingen_bij_hun_vraag(db_session, tmp_path):
    """Een tentamen ligt vast, scenario's groeien. Herkend aan hun plek zou een
    nieuw scenario in het midden alles erna een plek opschuiven, en hingen je
    pogingen aan een andere vraag. Daarom de vraag-id als sleutel."""
    data = _scenarios()
    import_exam(db_session, _write(tmp_path, data))
    tweede = db_session.query(PracticeCard).filter(PracticeCard.position == 2).one()
    _attempt(db_session, tweede, 0.5, datetime(2026, 10, 17))

    nieuw = dict(_first_question(data), id="p1-n", topic="nieuw scenario in het midden")
    data["sections"][0]["questions"].insert(1, nieuw)
    data["total_points"] = 1.5
    report = import_exam(db_session, _write(tmp_path, data))

    assert report.created == 1
    poging = db_session.query(PracticeAttempt).one()
    kaart = db_session.get(PracticeCard, poging.card_id)
    assert kaart.spec["question_id"] == "p1-b"
    assert kaart.position == 3
