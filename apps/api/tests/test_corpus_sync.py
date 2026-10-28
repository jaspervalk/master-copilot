from pathlib import Path

import pytest

from app.models import Course, Document
from app.services import corpus_sync
from app.services import documents as documents_service
from app.services.parsing import ParsedDocument, ParsedPage


class _FakeBatch:
    provider = "local-hash"
    model = "local"
    dimensions = 3

    def __init__(self, count: int) -> None:
        self.vectors = [[0.1, 0.2, 0.3] for _ in range(count)]


class _FakeEmbeddings:
    def embed_many(self, texts: list[str]) -> _FakeBatch:
        return _FakeBatch(len(texts))


@pytest.fixture(autouse=True)
def _stub_pipeline(monkeypatch):
    def fake_parse(path: Path) -> ParsedDocument:
        return ParsedDocument(
            title=path.stem,
            page_count=1,
            pages=[ParsedPage(page_number=1, text="1 Kop\n\n" + " ".join(["woord"] * 60))],
            metadata={},
        )

    monkeypatch.setattr(documents_service, "parse_document", fake_parse)
    monkeypatch.setattr(documents_service, "EmbeddingService", lambda: _FakeEmbeddings())
    monkeypatch.setattr(documents_service, "refresh_hybrid_index", lambda db: 0)


def _write(corpus: Path, relative: str, content: bytes = b"%PDF-1.4 x") -> Path:
    target = corpus / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def test_first_sync_adds_documents(tmp_corpus, db_session, fake_qdrant):
    _write(tmp_corpus, "dl/books/bishop.pdf")
    _write(tmp_corpus, "dl/slides/week-03/cnn.pdf")

    report = corpus_sync.sync_corpus(db_session)

    assert report.added == 2
    assert db_session.query(Document).count() == 2
    slides = db_session.query(Document).filter_by(doc_kind="slides").one()
    assert slides.week == 3
    assert slides.ingestion_status == "indexed"


def test_second_sync_changes_nothing(tmp_corpus, db_session, fake_qdrant):
    _write(tmp_corpus, "dl/books/bishop.pdf")
    corpus_sync.sync_corpus(db_session)

    report = corpus_sync.sync_corpus(db_session)

    assert (report.added, report.updated, report.skipped) == (0, 0, 1)


def test_changed_file_is_reindexed(tmp_corpus, db_session, fake_qdrant):
    target = _write(tmp_corpus, "dl/books/bishop.pdf")
    corpus_sync.sync_corpus(db_session)

    target.write_bytes(b"%PDF-1.4 andere inhoud")
    report = corpus_sync.sync_corpus(db_session)

    assert report.updated == 1


def test_removed_file_is_cleaned_up(tmp_corpus, db_session, fake_qdrant):
    target = _write(tmp_corpus, "dl/books/bishop.pdf")
    corpus_sync.sync_corpus(db_session)
    target.unlink()

    report = corpus_sync.sync_corpus(db_session)

    assert report.removed == 1
    assert db_session.query(Document).count() == 0


def test_bad_path_is_rejected_without_stopping_the_run(tmp_corpus, db_session, fake_qdrant):
    _write(tmp_corpus, "dl/books/bishop.pdf")
    _write(tmp_corpus, "dl/random/onbekend.pdf")

    report = corpus_sync.sync_corpus(db_session)

    assert report.added == 1
    assert len(report.rejected) == 1
    assert "random" in report.rejected[0][1]


def test_trash_folder_is_skipped(tmp_corpus, db_session, fake_qdrant):
    _write(tmp_corpus, ".trash/dl/books/oud.pdf")

    report = corpus_sync.sync_corpus(db_session)

    assert report.added == 0
    assert report.rejected == []


def test_a_readme_is_documentation_not_material(tmp_corpus, db_session, fake_qdrant):
    """corpus/README.md legt de mappen uit. Sinds .md stof kan zijn, zou hij
    anders bij elke sync als pad zonder vak geweigerd worden."""
    _write(tmp_corpus, "README.md", b"# De mapstructuur\n")
    _write(tmp_corpus, "sso/notes/README.md", b"# Wat hier staat\n")

    report = corpus_sync.sync_corpus(db_session)

    assert report.rejected == []
    assert report.added == 0


def test_dry_run_writes_nothing(tmp_corpus, db_session, fake_qdrant):
    _write(tmp_corpus, "dl/books/bishop.pdf")

    report = corpus_sync.sync_corpus(db_session, dry_run=True)

    assert report.added == 1
    assert db_session.query(Document).count() == 0


def test_assignment_status_follows_submissions(tmp_corpus, db_session, fake_qdrant):
    _write(tmp_corpus, "dl/assignments/week-01/opgaven.pdf")
    _write(tmp_corpus, "dl/assignments/week-02/opgaven.pdf")
    _write(tmp_corpus, "dl/submissions/week-02/mijn-uitwerking.pdf")

    corpus_sync.sync_corpus(db_session)

    statuses = {
        document.week: document.assignment_status
        for document in db_session.query(Document).filter_by(doc_kind="assignment")
    }
    assert statuses == {1: "open", 2: "submitted"}


def test_status_flips_when_a_submission_appears(tmp_corpus, db_session, fake_qdrant):
    _write(tmp_corpus, "dl/assignments/week-01/opgaven.pdf")
    corpus_sync.sync_corpus(db_session)

    _write(tmp_corpus, "dl/submissions/week-01/uitwerking.pdf")
    corpus_sync.sync_corpus(db_session)

    assignment = db_session.query(Document).filter_by(doc_kind="assignment").one()
    assert assignment.assignment_status == "submitted"


def test_course_yaml_is_read(tmp_corpus, db_session, fake_qdrant):
    _write(tmp_corpus, "dl/books/bishop.pdf")
    (tmp_corpus / "dl" / "course.yml").write_text(
        "name: Deep Learning\nperiod: 2026-1\nlecturer: Ergens Iemand\n", encoding="utf-8"
    )

    corpus_sync.sync_corpus(db_session)

    course = db_session.get(Course, "dl")
    assert course.name == "Deep Learning"
    assert course.period == "2026-1"


def test_course_without_yaml_gets_a_readable_name(tmp_corpus, db_session, fake_qdrant):
    _write(tmp_corpus, "statistical-learning/books/esl.pdf")

    corpus_sync.sync_corpus(db_session)

    assert db_session.get(Course, "statistical-learning").name == "Statistical Learning"


def test_parse_failure_marks_the_document_failed(tmp_corpus, db_session, fake_qdrant, monkeypatch):
    _write(tmp_corpus, "dl/books/kapot.pdf")

    def boom(path: Path):
        raise ValueError("geen tekstlaag")

    monkeypatch.setattr(documents_service, "parse_document", boom)

    report = corpus_sync.sync_corpus(db_session)

    assert len(report.failed) == 1
    document = db_session.query(Document).one()
    assert document.ingestion_status == "failed"
    assert "geen tekstlaag" in document.parse_error


from datetime import date


def _assignment(db, *, course="sso", week=4, status=None) -> Document:
    document = Document(
        title=f"opdracht {week}", source_path=f"{course}/assignments/week-{week:02d}/a.pdf",
        checksum="0" * 64, course_slug=course, doc_kind="assignment", week=week,
        assignment_status=status, ingestion_status="indexed",
    )
    db.add(document)
    db.commit()
    return document


def test_deadline_in_the_past_closes_an_assignment(db_session):
    db_session.add(Course(slug="sso", name="SSO", deadlines={"4": "2026-09-28"}))
    document = _assignment(db_session, week=4)

    corpus_sync.recompute_assignment_status(db_session, "sso", today=date(2026, 9, 29))

    assert document.assignment_status == "closed"


def test_on_the_deadline_day_the_assignment_is_still_open(db_session):
    db_session.add(Course(slug="sso", name="SSO", deadlines={"4": "2026-09-28"}))
    document = _assignment(db_session, week=4)

    corpus_sync.recompute_assignment_status(db_session, "sso", today=date(2026, 9, 28))

    assert document.assignment_status == "open"


def test_closed_wins_over_submitted(db_session):
    """Bij groepswerk levert een teamgenoot in; de deadline is het betrouwbare signaal."""
    db_session.add(Course(slug="sso", name="SSO", deadlines={"4": "2026-09-28"}))
    document = _assignment(db_session, week=4)
    db_session.add(Document(
        title="inzending", source_path="sso/submissions/week-04/s.pdf", checksum="1" * 64,
        course_slug="sso", doc_kind="submission", week=4, ingestion_status="indexed",
    ))
    db_session.commit()

    corpus_sync.recompute_assignment_status(db_session, "sso", today=date(2026, 10, 1))

    assert document.assignment_status == "closed"


def test_without_deadline_status_follows_submissions_as_before(db_session):
    db_session.add(Course(slug="sso", name="SSO"))
    document = _assignment(db_session, week=4)

    corpus_sync.recompute_assignment_status(db_session, "sso", today=date(2026, 10, 1))

    assert document.assignment_status == "open"


def test_course_yaml_deadlines_are_read_and_bad_ones_skipped(tmp_corpus, db_session, caplog):
    (tmp_corpus / "sso").mkdir()
    (tmp_corpus / "sso" / "course.yml").write_text(
        "name: SSO\nassignments:\n  - week: 4\n    deadline: 2026-09-28\n  - week: 6\n    deadline: morgen\n",
        encoding="utf-8",
    )

    course, problems = corpus_sync.upsert_course_from_yaml(db_session, "sso", tmp_corpus)

    assert course.deadlines == {"4": "2026-09-28"}
    assert any("morgen" in problem for problem in problems)


def test_due_date_is_accepted_as_a_synonym_for_deadline():
    """`due_date` is wat een mens schrijft; accepteren kost niets."""
    config = corpus_sync.parse_course_config(
        "name: SSO\nassignments:\n  - week: 3\n    due_date: 2026-09-21\n"
    )

    assert config.deadlines == {"3": "2026-09-21"}
    assert config.problems == []


def test_extra_fields_are_ignored():
    config = corpus_sync.parse_course_config(
        "name: FDS\n"
        "assignments:\n"
        "  - name: Assignment 1\n"
        "    description: groepswerk\n"
        "    available_date: 2026-09-11\n"
        "    week: 4\n"
        "    due_date: 2026-09-28\n"
        "    points: 100\n"
    )

    assert config.deadlines == {"4": "2026-09-28"}
    assert config.problems == []


def test_a_typo_in_the_assignments_key_is_reported():
    """De stilste fout die er is: het bestand klopt en er gebeurt niets."""
    config = corpus_sync.parse_course_config(
        "name: FDS\nassignmets:\n  - week: 4\n    due_date: 2026-09-28\n"
    )

    assert config.deadlines == {}
    assert "assignmets" in config.problems[0]
    assert "assignments" in config.problems[0]


def test_broken_yaml_is_reported_as_one_readable_line():
    config = corpus_sync.parse_course_config("name: FDS\nassignments:\n  - description: -\n")

    assert config.deadlines == {}
    assert len(config.problems) == 1
    assert "onleesbare YAML" in config.problems[0]
    assert "\n" not in config.problems[0]


def test_an_entry_without_a_week_cannot_be_linked():
    config = corpus_sync.parse_course_config(
        "assignments:\n  - name: Assignment 1\n    due_date: 2026-09-28\n"
    )

    assert config.deadlines == {}
    assert "Assignment 1" in config.problems[0]
    assert "week" in config.problems[0]


def test_an_impossible_date_is_reported_with_its_value():
    config = corpus_sync.parse_course_config(
        "assignments:\n  - name: Assignment 2\n    week: 6\n    due_date: 22026-10-12\n"
    )

    assert config.deadlines == {}
    assert "22026-10-12" in config.problems[0]


def test_a_row_with_neither_week_nor_deadline_is_a_note_not_an_error():
    """Een tentamenregel is documentatie voor jezelf, geen opdracht."""
    config = corpus_sync.parse_course_config(
        "assignments:\n"
        "  - name: Assignment 1\n    week: 4\n    due_date: 2026-09-28\n"
        "  - name: Final Exam\n    description: tentamen\n"
    )

    assert config.deadlines == {"4": "2026-09-28"}
    assert config.problems == []


def test_canvas_id_and_exams_are_read():
    """De agenda koppelt een vak aan Canvas via `canvas_id`, en SSO heeft zijn
    tentamen niet in Canvas: dat staat dan in `exams`."""
    config = corpus_sync.parse_course_config(
        "name: FDS\n"
        "canvas_id: 59831\n"
        "exams:\n"
        "  - name: Tentamen\n    date: 2026-10-21\n"
        "  - name: Herkansing\n    date: 2026-12-14\n"
    )

    assert config.canvas_id == 59831
    assert config.exams == [
        {"name": "Tentamen", "date": "2026-10-21"},
        {"name": "Herkansing", "date": "2026-12-14"},
    ]
    assert config.problems == []


def test_assignments_keep_their_names_next_to_the_deadlines():
    """De agenda vergelijkt per naam met Canvas en zoekt het opgavenblad per
    week; `deadlines` blijft precies wat het was, want daar draait de
    spoilerfilter op."""
    config = corpus_sync.parse_course_config(
        "assignments:\n"
        "  - name: Assignment 1\n"
        "    week: 4\n"
        "    available_date: 2026-09-11\n"
        "    due_date: 2026-09-28\n"
        "    points: 100\n"
        "  - week: 6\n"
        "    due_date: 2026-10-12\n"
    )

    assert config.deadlines == {"4": "2026-09-28", "6": "2026-10-12"}
    assert config.assignments == [
        {
            "name": "Assignment 1",
            "week": 4,
            "due_date": "2026-09-28",
            "available_date": "2026-09-11",
            "points": 100.0,
        },
        {"name": "opdracht 2", "week": 6, "due_date": "2026-10-12", "available_date": None, "points": None},
    ]


def test_an_exam_without_a_date_is_a_problem():
    config = corpus_sync.parse_course_config("exams:\n  - name: Tentamen\n")

    assert config.exams == []
    assert "Tentamen" in config.problems[0]
    assert "date" in config.problems[0]


def test_an_exam_with_an_unreadable_date_is_reported_with_its_value():
    config = corpus_sync.parse_course_config("exams:\n  - name: Tentamen\n    date: morgen\n")

    assert config.exams == []
    assert "morgen" in config.problems[0]


def test_a_non_numeric_canvas_id_is_a_problem():
    config = corpus_sync.parse_course_config("canvas_id: fds\n")

    assert config.canvas_id is None
    assert "canvas_id" in config.problems[0]


def test_canvas_id_exams_and_assignments_land_on_the_course(tmp_corpus, db_session):
    (tmp_corpus / "sso").mkdir()
    (tmp_corpus / "sso" / "course.yml").write_text(
        "name: SSO\n"
        "canvas_id: 59863\n"
        "exams:\n  - name: Tentamen\n    date: 2026-10-21\n"
        "assignments:\n  - name: Assignment 1\n    week: 3\n    due_date: 2026-09-21\n    points: 10\n",
        encoding="utf-8",
    )

    course, problems = corpus_sync.upsert_course_from_yaml(db_session, "sso", tmp_corpus)

    assert problems == []
    assert course.canvas_id == 59863
    assert course.exams == [{"name": "Tentamen", "date": "2026-10-21"}]
    assert course.assignments[0]["name"] == "Assignment 1"
    assert course.deadlines == {"3": "2026-09-21"}


def test_a_broken_course_yml_shows_up_in_the_sync_report(tmp_corpus, db_session, fake_qdrant):
    """Een kapotte course.yml was alleen een waarschuwing op stderr; nu werk."""
    _write(tmp_corpus, "sso/books/islr.pdf")
    (tmp_corpus / "sso" / "course.yml").write_text("name: SSO\nassignmets: []\n", encoding="utf-8")

    report = corpus_sync.sync_corpus(db_session)

    assert report.added == 1
    assert [slug for slug, _ in report.course_problems] == ["sso"]
    assert any(line.startswith("course.yml  sso:") for line in report.as_lines())


def test_a_good_course_yml_leaves_the_report_clean(tmp_corpus, db_session, fake_qdrant):
    _write(tmp_corpus, "sso/books/islr.pdf")
    (tmp_corpus / "sso" / "course.yml").write_text(
        "name: SSO\nassignments:\n  - week: 3\n    due_date: 2026-09-21\n", encoding="utf-8"
    )

    report = corpus_sync.sync_corpus(db_session)

    assert report.course_problems == []
    assert db_session.get(Course, "sso").deadlines == {"3": "2026-09-21"}


def test_a_course_says_how_its_exam_asks_about_code():
    """Drie gevallen, want er zijn er drie. `none`: geen code op het tentamen.
    `read`: je krijgt een fragment en voorspelt de uitvoer, maar hoeft geen
    syntax uit je hoofd te schrijven — zo zei de docent van SSO het bij college
    8. Zonder instelling mag alles."""
    from app.services.corpus_sync import parse_course_config

    lezen = parse_course_config("name: SSO\nstudy:\n  code: read\n")
    geen = parse_course_config("name: SSO\nstudy:\n  code: none\n")

    assert lezen.problems == [] and lezen.study == {"code": "read"}
    assert geen.problems == [] and geen.study == {"code": "none"}


def test_an_unknown_code_setting_is_reported_not_guessed():
    """Een typefout mag niet stil 'alles mag' worden: dan schrijft de weekkaart
    weer `lm()` als vaardigheid op."""
    from app.services.corpus_sync import parse_course_config

    config = parse_course_config("name: SSO\nstudy:\n  code: lezen\n")

    assert any("lezen" in problem for problem in config.problems)
    assert config.study == {}


def test_the_old_no_code_switch_points_to_its_replacement():
    """`no_code: true` stond één dag in SSO's course.yml. Wie hem nog heeft,
    krijgt te horen wat het nu is in plaats van een kale 'onbekende sleutel'."""
    from app.services.corpus_sync import parse_course_config

    config = parse_course_config("name: SSO\nstudy:\n  no_code: true\n")

    assert any("code: none" in problem for problem in config.problems)


def test_a_course_without_that_block_says_nothing_about_code():
    from app.services.corpus_sync import parse_course_config

    assert parse_course_config("name: SSO\n").study == {}


def test_an_unknown_key_inside_study_is_reported():
    from app.services.corpus_sync import parse_course_config

    config = parse_course_config("name: SSO\nstudy:\n  geen_code: true\n")

    assert any("geen_code" in problem for problem in config.problems)


def test_a_course_says_what_you_are_preparing_for():
    """Niet elk vak eindigt in een schriftelijk tentamen statistiek: AFCS heeft
    vijf quizzen over de slides. Voorbeelden en oefenvragen schreven anders voor
    het verkeerde soort toets."""
    from app.services.corpus_sync import parse_course_config

    config = parse_course_config("name: AFCS\nstudy:\n  code: none\n  assessment: vijf quizzen over de slides\n")

    assert config.problems == []
    assert config.study == {"code": "none", "assessment": "vijf quizzen over de slides"}


def test_an_empty_assessment_is_reported():
    from app.services.corpus_sync import parse_course_config

    config = parse_course_config("name: AFCS\nstudy:\n  assessment: ''\n")

    assert any("assessment" in problem for problem in config.problems)
    assert config.study == {}
