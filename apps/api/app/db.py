from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


connect_args: dict[str, bool] = {}
if settings.use_sqlite:
    connect_args["check_same_thread"] = False

engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from sqlalchemy import inspect, text

    from app import models  # noqa: F401  — registreert de tabellen

    Base.metadata.create_all(bind=engine)

    # Nieuwe kolommen op bestaande tabellen komen hier als (tabel, kolom, DDL).
    additive_columns: list[tuple[str, str, str]] = [
        ("courses", "deadlines", "ALTER TABLE courses ADD COLUMN deadlines JSON DEFAULT '{}'"),
        ("courses", "week_plans", "ALTER TABLE courses ADD COLUMN week_plans JSON DEFAULT '{}'"),
        ("practice_cards", "explanation", "ALTER TABLE practice_cards ADD COLUMN explanation TEXT DEFAULT ''"),
        ("practice_cards", "spec", "ALTER TABLE practice_cards ADD COLUMN spec JSON DEFAULT '{}'"),
        ("practice_cards", "points", "ALTER TABLE practice_cards ADD COLUMN points FLOAT"),
        ("practice_cards", "origin", "ALTER TABLE practice_cards ADD COLUMN origin VARCHAR(64)"),
        ("practice_cards", "position", "ALTER TABLE practice_cards ADD COLUMN position INTEGER"),
        ("practice_cards", "week", "ALTER TABLE practice_cards ADD COLUMN week INTEGER"),
        ("practice_attempts", "score", "ALTER TABLE practice_attempts ADD COLUMN score FLOAT"),
        ("practice_attempts", "max_score", "ALTER TABLE practice_attempts ADD COLUMN max_score FLOAT"),
        ("practice_attempts", "feedback", "ALTER TABLE practice_attempts ADD COLUMN feedback JSON DEFAULT '{}'"),
        ("courses", "canvas_id", "ALTER TABLE courses ADD COLUMN canvas_id INTEGER"),
        ("courses", "assignments", "ALTER TABLE courses ADD COLUMN assignments JSON DEFAULT '[]'"),
        ("courses", "exams", "ALTER TABLE courses ADD COLUMN exams JSON DEFAULT '[]'"),
        ("courses", "study", "ALTER TABLE courses ADD COLUMN study JSON DEFAULT '{}'"),
        ("canvas_items", "unmarked_at", "ALTER TABLE canvas_items ADD COLUMN unmarked_at DATETIME"),
        ("tasks", "deleted_at", "ALTER TABLE tasks ADD COLUMN deleted_at DATETIME"),
        ("tasks", "links", "ALTER TABLE tasks ADD COLUMN links JSON DEFAULT '[]'"),
    ]

    if not additive_columns:
        return

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in additive_columns:
            if not inspector.has_table(table):
                continue
            existing = {col["name"] for col in inspector.get_columns(table)}
            if column not in existing:
                conn.execute(text(ddl))
