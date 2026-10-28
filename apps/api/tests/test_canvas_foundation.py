"""Het fundament onder de agenda: instellingen, tabellen en de kolommen die
een bestaande database erbij krijgt."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app import db as app_db
from app.core.config import Settings, settings


def test_canvas_settings_default_to_unconfigured(monkeypatch):
    monkeypatch.delenv("CANVAS_BASE_URL", raising=False)
    monkeypatch.delenv("CANVAS_ACCESS_TOKEN", raising=False)

    fresh = Settings(_env_file=None)

    assert fresh.canvas_base_url is None
    assert fresh.canvas_access_token is None
    assert fresh.canvas_stale_after_minutes == 30


def test_no_test_can_reach_canvas():
    """De echte .env heeft een token. Een test die per ongeluk naar Canvas gaat
    is traag, breekbaar en lekt wat de gebruiker daar doet; de autouse-fixture
    in conftest.py haalt de configuratie weg."""
    assert settings.canvas_access_token is None
    assert settings.canvas_base_url is None


def test_agenda_tables_are_created(db_session):
    names = set(inspect(db_session.get_bind()).get_table_names())

    assert {"canvas_courses", "canvas_items", "canvas_announcements", "canvas_files", "tasks"} <= names


def test_init_db_adds_the_new_course_columns_to_an_old_database(tmp_path, monkeypatch):
    """Geen Alembic: een database van vóór de agenda krijgt de kolommen via
    ALTER TABLE, net als bij `deadlines` en `week_plans` destijds."""
    engine = create_engine(f"sqlite:///{tmp_path / 'oud.db'}", future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE courses (slug VARCHAR(64) PRIMARY KEY, name VARCHAR(255), "
                "deadlines JSON, week_plans JSON, created_at DATETIME)"
            )
        )
    monkeypatch.setattr(app_db, "engine", engine)

    app_db.init_db()

    columns = {column["name"] for column in inspect(engine).get_columns("courses")}
    assert {"canvas_id", "assignments", "exams"} <= columns
