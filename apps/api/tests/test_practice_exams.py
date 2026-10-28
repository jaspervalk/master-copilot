"""Een transcriptie van een tentamen wordt mechanisch nagelopen voordat hij
kaarten wordt. Een fout kruisje in het antwoordmodel leert je de verkeerde
letter aan, en dat merk je pas op het tentamen zelf."""
from pathlib import Path

import pytest
import yaml

from app.models import Chunk, Document, PracticeCard
from app.services.practice.exams import import_course_exams, import_exam, load_blueprint


REPO_EXAM = Path(__file__).resolve().parents[3] / "corpus" / "fundamentals-of-ds" / "exams" / "mock-exam-1.yml"


def _blueprint(**overrides) -> dict:
    base = {
        "id": "mock-exam-9",
        "title": "Mock Exam 9",
        "course": "fundamentals-of-ds",
        "source": "exams/MockExam.pdf",
        "total_points": 5.5,
        "sections": [
            {
                "number": 3,
                "title": "Supervised Learning",
                "questions": [
                    {
                        "id": "3c",
                        "page": 6,
                        "type": "mc_single",
                        "points": 1.5,
                        "week": 3,
                        "question": "What is the False Negative Rate of the confusion matrix above?",
                        "figure": "TN 2, FP 6, FN 1, TP 5",
                        "options": ["6/11", "5/6", "1/6", "5/11"],
                        "answer": ["c"],
                        "compute": "1 / (1 + 5)",
                        "explanation": "FNR = FN / (FN + TP).",
                    },
                    {
                        "id": "3h",
                        "page": 7,
                        "type": "open",
                        "points": 4,
                        "week": 3,
                        "question": "Name one numerical optimisation method.",
                        "model_answer": "Gradient descent.",
                        "rubric": [{"criterion": "Names gradient descent.", "points": 4}],
                    },
                ],
            }
        ],
    }
    base.update(overrides)
    return base


def _write(tmp_path: Path, data: dict, name: str = "mock-exam-9.yml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _question(data: dict, qid: str) -> dict:
    return next(q for s in data["sections"] for q in s["questions"] if q["id"] == qid)


@pytest.mark.skipif(not REPO_EXAM.exists(), reason="corpus/ staat bewust niet in git")
def test_the_real_mock_exam_transcription_is_consistent():
    """Het bestand in de repo: 100 punten, elk schema klopt, elke rekenvraag
    valt op de aangekruiste optie."""
    blueprint, problems = load_blueprint(REPO_EXAM)

    assert problems == []
    assert blueprint.total_points == 100
    assert len(blueprint.questions()) == 34


def test_the_draft_solutions_own_mistake_is_caught(tmp_path):
    """De conceptuitwerking kruiste eerst 5/6 aan bij de false negative rate."""
    data = _blueprint()
    _question(data, "3c")["answer"] = ["b"]

    _, problems = load_blueprint(_write(tmp_path, data))

    assert problems == ["vraag 3c: 'compute' geeft 0.166667, dat is optie c — aangemerkt staat b"]


def test_a_numeric_question_without_a_computation_is_refused(tmp_path):
    data = _blueprint()
    del _question(data, "3c")["compute"]

    _, problems = load_blueprint(_write(tmp_path, data))

    assert any("'compute' ontbreekt" in problem for problem in problems)


def test_points_that_do_not_add_up_are_refused(tmp_path):
    _, problems = load_blueprint(_write(tmp_path, _blueprint(total_points=100)))

    assert problems == ["de vragen tellen op tot 5.5 punten, niet tot 100"]


def test_a_rubric_must_add_up_to_the_points_of_its_question(tmp_path):
    data = _blueprint()
    _question(data, "3h")["rubric"][0]["points"] = 3

    _, problems = load_blueprint(_write(tmp_path, data))

    assert problems == ["vraag 3h: het schema telt op tot 3, de vraag is 4 punten"]


def test_a_single_choice_question_needs_exactly_one_answer(tmp_path):
    data = _blueprint()
    _question(data, "3c")["answer"] = ["c", "d"]
    del _question(data, "3c")["compute"]
    _question(data, "3c")["options"] = ["a", "b", "c", "d"]

    _, problems = load_blueprint(_write(tmp_path, data))

    assert "vraag 3c: één goed antwoord verwacht, 2 gegeven" in problems


def test_importing_turns_questions_into_cards(db_session, tmp_path):
    document = Document(
        title="MockExam", source_path="fundamentals-of-ds/exams/MockExam.pdf", checksum="0" * 64,
        course_slug="fundamentals-of-ds", doc_kind="exam", ingestion_status="indexed",
    )
    document.chunks.append(Chunk(
        chunk_index=0, section_path=None, page_start=5, page_end=6, token_count=3,
        text="3c What is the False Negative Rate", normalized_text="3c", chunk_metadata={},
    ))
    db_session.add(document)
    db_session.commit()

    report = import_exam(db_session, _write(tmp_path, _blueprint()))

    assert (report.created, report.problems) == (2, [])
    keuze, open_vraag = db_session.query(PracticeCard).order_by(PracticeCard.position).all()
    assert (keuze.kind, keuze.points, keuze.week, keuze.origin, keuze.position) == ("mc", 1.5, 3, "mock-exam-9", 1)
    assert keuze.spec["options"] == ["6/11", "5/6", "1/6", "5/11"]
    assert keuze.spec["answer"] == [2]
    assert keuze.reference_answer == "c"
    assert keuze.section_path == "Mock Exam 9 › 3 Supervised Learning"
    # De vraag staat op pagina 6; die valt in de chunk van pagina 5-6.
    assert (keuze.document_id, keuze.chunk_id) == (document.id, document.chunks[0].id)
    assert open_vraag.kind == "open"
    assert open_vraag.spec["rubric"] == [{"criterion": "Names gradient descent.", "points": 4.0}]
    assert open_vraag.reference_answer == "Gradient descent."


def test_a_transcription_with_problems_writes_nothing(db_session, tmp_path):
    data = _blueprint()
    _question(data, "3c")["answer"] = ["b"]

    report = import_exam(db_session, _write(tmp_path, data))

    assert report.problems
    assert db_session.query(PracticeCard).count() == 0


def test_importing_again_updates_in_place(db_session, tmp_path):
    """Een verbeterde typfout mag geen tweede kaart opleveren: je pogingen
    horen aan de vraag te blijven hangen."""
    path = _write(tmp_path, _blueprint())
    import_exam(db_session, path)
    kaart_id = db_session.query(PracticeCard).filter_by(position=2).one().id

    herhaald = import_exam(db_session, path)
    assert (herhaald.created, herhaald.updated, herhaald.unchanged) == (0, 0, 2)

    data = _blueprint()
    _question(data, "3h")["question"] = "Name one numerical optimisation method (typo fixed)."
    bijgewerkt = import_exam(db_session, _write(tmp_path, data))

    assert (bijgewerkt.created, bijgewerkt.updated) == (0, 1)
    kaart = db_session.query(PracticeCard).filter_by(position=2).one()
    assert kaart.id == kaart_id
    assert kaart.question.endswith("(typo fixed).")


def test_a_question_removed_from_the_transcription_is_retired(db_session, tmp_path):
    import_exam(db_session, _write(tmp_path, _blueprint()))
    data = _blueprint(total_points=1.5)
    data["sections"][0]["questions"].pop()

    report = import_exam(db_session, _write(tmp_path, data))

    assert report.retired == 1
    assert db_session.query(PracticeCard).filter_by(position=2).one().disabled is True


def test_the_exams_folder_of_a_course_is_picked_up(db_session, tmp_path):
    folder = tmp_path / "fundamentals-of-ds" / "exams"
    folder.mkdir(parents=True)
    _write(folder, _blueprint())

    (report,) = import_course_exams(db_session, "fundamentals-of-ds", tmp_path)

    assert report.exam_id == "mock-exam-9"
    assert import_course_exams(db_session, "sso", tmp_path) == []


def test_the_layout_file_is_not_a_transcription(db_session, tmp_path):
    """`opbouw.yml` staat naast de transcripties maar is er geen; als transcriptie
    gelezen zou hij bij elke sync als kapot gemeld worden."""
    folder = tmp_path / "fundamentals-of-ds" / "exams"
    folder.mkdir(parents=True)
    _write(folder, _blueprint())
    (folder / "opbouw.yml").write_text(yaml.safe_dump({"title": "Tentamen 2026", "total_points": 100, "sections": []}), encoding="utf-8")

    reports = import_course_exams(db_session, "fundamentals-of-ds", tmp_path)

    assert [report.exam_id for report in reports] == ["mock-exam-9"]


def test_the_preparation_file_is_not_a_transcription(db_session, tmp_path):
    """`voorbereiding.yml` (de tab Tentamen) staat ook in `exams/`; zonder
    uitzondering werd hij bij elke sync als kapotte transcriptie gemeld."""
    folder = tmp_path / "fundamentals-of-ds" / "exams"
    folder.mkdir(parents=True)
    _write(folder, _blueprint())
    (folder / "voorbereiding.yml").write_text(yaml.safe_dump({"patterns": []}), encoding="utf-8")

    reports = import_course_exams(db_session, "fundamentals-of-ds", tmp_path)

    assert [report.exam_id for report in reports] == ["mock-exam-9"]
