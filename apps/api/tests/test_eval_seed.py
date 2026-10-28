from datetime import datetime, timedelta

import yaml

from app.eval.seed import render_seed_yaml, seed_entries
from app.models import QueryLog


def _log(db, question, *, course="sso", citations=None, status="ok", age_minutes=0):
    db.add(
        QueryLog(
            endpoint="stream", question=question, filters={"course_slug": course} if course else {},
            top_k=8, status=status,
            citations=citations if citations is not None else [
                {"source_path": "sso/books/islr.pdf", "page_start": 214, "page_end": 215}
            ],
            created_at=datetime(2026, 9, 2, 12, 0) - timedelta(minutes=age_minutes),
        )
    )
    db.commit()


def test_seed_uses_first_citation_as_unverified_candidate(db_session):
    _log(db_session, "hoe werkt k-fold cross-validation?")

    entries = seed_entries(db_session, limit=10)

    assert entries[0]["question"] == "hoe werkt k-fold cross-validation?"
    assert entries[0]["course_slug"] == "sso"
    assert entries[0]["unverified"] is True
    assert entries[0]["expected"] == [{"source_path": "sso/books/islr.pdf", "pages": [214, 215]}]


def test_seed_skips_failed_and_uncited_queries(db_session):
    _log(db_session, "mislukt", status="error", citations=[])
    _log(db_session, "zonder bron", citations=[])
    _log(db_session, "goed")

    assert [e["question"] for e in seed_entries(db_session, limit=10)] == ["goed"]


def test_seed_deduplicates_questions_keeping_the_newest(db_session):
    _log(db_session, "Wat is ridge?", age_minutes=10)
    _log(db_session, "wat is ridge?", age_minutes=0)

    entries = seed_entries(db_session, limit=10)

    assert len(entries) == 1


def test_seed_respects_limit_newest_first(db_session):
    for index in range(5):
        _log(db_session, f"vraag {index}", age_minutes=index)

    entries = seed_entries(db_session, limit=2)

    assert [e["question"] for e in entries] == ["vraag 0", "vraag 1"]


def test_seed_ids_are_stable_and_unique(db_session):
    _log(db_session, "hoe werkt k-fold cross-validation?")
    _log(db_session, "hoe werkt de bootstrap?")

    ids = [e["id"] for e in seed_entries(db_session, limit=10)]

    assert len(set(ids)) == 2
    assert all(id_.startswith("seed-") for id_ in ids)


def test_rendered_yaml_loads_as_a_case_file(db_session):
    _log(db_session, "hoe werkt k-fold cross-validation?")

    text = render_seed_yaml(seed_entries(db_session, limit=10))
    parsed = yaml.safe_load(text)

    assert parsed["cases"][0]["unverified"] is True
    assert "nagekeken" in text  # de instructie bovenaan
