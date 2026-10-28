"""Waar een Canvas-bestand in het corpus hoort. Raden mag niet: geen zekere
soort of week is een reden, geen voorstel."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.models import CanvasFile, CanvasPage, Course, Document
from app.services.canvas.placement import material_state, page_state, propose_page, propose_placement

ROOT = Path("/tmp/corpus-test")

FDS = Course(
    slug="fundamentals-of-ds", name="FDS", canvas_id=59831,
    assignments=[{"name": "Assignment 1", "week": 4, "due_date": "2026-09-28", "available_date": None, "points": 100.0}],
    week_plans={"1": {"lectures": [], "topics": [], "reading": []}},
)
SSO = Course(
    slug="sso", name="SSO", canvas_id=59863,
    assignments=[{"name": "Assignment 1", "week": 3, "due_date": "2026-09-21", "available_date": None, "points": 10.0}],
    week_plans={
        "1": {"lectures": [1, 2], "topics": [], "reading": [{"document": "sso/books/Triola.pdf", "sections": ["5", "6.1", "6.2", "6.3"], "pages": None}]},
        "2": {"lectures": [3, 4], "topics": [], "reading": [{"document": "sso/books/Triola.pdf", "sections": ["9.2", "9.3"], "pages": None}]},
    },
)


def _file(filename: str, *, course: Course, folder: str | None = None, module: str | None = None, source: str = "") -> CanvasFile:
    return CanvasFile(
        id=1, canvas_course_id=course.canvas_id, filename=filename, display_name=filename, folder=folder,
        module_name=module, source=source,
    )


@pytest.mark.parametrize(
    "filename, course, folder, module, source, expected",
    [
        ("20260915_lecture05_classification.pdf", FDS, None, "Week 3", "module:Week 3", ("slides", 3, "fundamentals-of-ds/slides/week-03/20260915_lecture05_classification.pdf")),
        ("20260917_lect06_trees_models_validation.pdf", FDS, None, "Week 3", "module:Week 3", ("slides", 3, "fundamentals-of-ds/slides/week-03/20260917_lect06_trees_models_validation.pdf")),
        ("lecture4.pdf", SSO, "statistics/Slides 2026/Lecture 4", "Course material", "page:Schedule", ("slides", 2, "sso/slides/week-02/lecture4.pdf")),
        ("Section+6.2.pdf", SSO, "statistics/Exercises", "Course material", "page:Schedule", ("exercise", 1, "sso/exercises/week-01/Section-6.2.pdf")),
        ("Section+12.1.pdf", SSO, "statistics/Exercises", "Course material", "page:Schedule", ("exercise", None, "sso/exercises/Section-12.1.pdf")),
        ("SSO_assignment1.pdf", SSO, None, None, "assignment:Assignment 1", ("assignment", 3, "sso/assignments/week-03/SSO_assignment1.pdf")),
        # Hoort bij de opdracht, maar is het opgavenblad niet: anders wijst de
        # coach-link naar de tips van vorig jaar in plaats van naar de opgave.
        ("Assignment+1+recommendations+-+2024.pdf", FDS, "Assignments", "Week 3", "module:Week 3", ("note", 4, "fundamentals-of-ds/notes/week-04/Assignment-1-recommendations-2024.pdf")),
        ("Assignment1_template.pdf", SSO, None, None, "assignment:Assignment 1", ("note", 3, "sso/notes/week-03/Assignment1_template.pdf")),
        ("2014-Rougier-PlosCB.pdf", FDS, "Readings", "Week 2", "module:Week 2", ("paper", None, "fundamentals-of-ds/papers/2014-Rougier-PlosCB.pdf")),
        ("baturo-et-al-2017-un-general-debate-corpus.pdf", FDS, None, "Week 3", "module:Week 3", ("paper", None, "fundamentals-of-ds/papers/baturo-et-al-2017-un-general-debate-corpus.pdf")),
        ("matplotlib_cheatsheets.pdf", FDS, "Readings", "Week 2", "module:Week 2", ("paper", None, "fundamentals-of-ds/papers/matplotlib_cheatsheets.pdf")),
        ("An+Introduction+to+Business+Analytics+by+Koole+%282019%29.pdf", SSO, "optimization/Book", None, "front_page", ("book", None, "sso/books/An-Introduction-to-Business-Analytics-by-Koole-2019.pdf")),
        ("MockExam-2022.pdf", SSO, "Exams/Exam 28-10-2022", None, "page:x", ("exam", None, "sso/exams/MockExam-2022.pdf")),
        # Code bij een college is een notitie, geen slides: de demo's van SSO
        # deel 2 heten "lecture_13_crn.py" en stonden zo tussen de slides.
        ("lecture_2_knapsack.py", SSO, None, None, "page:Lecture 2", ("note", 1, "sso/notes/week-01/lecture_2_knapsack.py")),
        ("lecture_4_exercise_1_template.py", SSO, None, None, "page:Lecture 4", ("note", 2, "sso/notes/week-02/lecture_4_exercise_1_template.py")),
        ("20260915_lecture05_demo.ipynb", FDS, None, "Week 3", "module:Week 3", ("note", 3, "fundamentals-of-ds/notes/week-03/20260915_lecture05_demo.ipynb")),
        # De uitwerking van een oud tentamen is geen opdrachtuitwerking: een
        # tentamen valt buiten de spoilerfilter, en je hebt hem juist nodig om
        # het oude tentamen na te kijken. Een herkansing is ook een tentamen.
        ("Answers_SSO_exam_28_10_2022.pdf", SSO, None, "Course material and assignments", "page:Exam preparation", ("exam", None, "sso/exams/Answers_SSO_exam_28_10_2022.pdf")),
        ("SSO+resit+22-12-2022+frontcover+and+formula+sheet.pdf", SSO, None, "Course material and assignments", "page:Exam preparation", ("exam", None, "sso/exams/SSO-resit-22-12-2022-frontcover-and-formula-sheet.pdf")),
    ],
)
def test_a_recognised_file_gets_a_place(filename, course, folder, module, source, expected):
    proposal = propose_placement(_file(filename, course=course, folder=folder, module=module, source=source), course, corpus_root=ROOT)

    assert proposal.placement is not None, proposal.reason
    assert (proposal.placement.doc_kind, proposal.placement.week, proposal.placement.relative_path) == expected
    assert proposal.reason


@pytest.mark.parametrize(
    "filename, course, folder, module, source, hint",
    [
        ("lecture7.pdf", SSO, "statistics/Slides 2026/Lecture 7", None, "page:x", "college 7"),
        ("assign0.pdf", SSO, "Assignments/Assignment0/old", None, "page:x", "course.yml"),
        # Een uitwerking wordt nooit voorgesteld, ook niet als het volgnummer bij
        # een opdracht in course.yml past: als "assignment" zou hij buiten de
        # spoilerfilter vallen.
        ("assign1_sol.pdf", SSO, None, None, "page:x", "uitwerking"),
        ("SSO_assignment0_solution.pdf", SSO, "Assignments/Assignment0", None, "assignment:Assignment 0", "uitwerking"),
        ("Section+6.2+answers.pdf", SSO, "statistics/Exercises", None, "page:x", "uitwerking"),
        ("Statistical_Tables_V2.pdf", SSO, "statistics", None, "page:x", "kies"),
        # "lect" midden in een woord is geen college.
        ("reflect2.pdf", FDS, None, None, "page:x", "kies"),
        # Sinds notebooks worden ingelezen is een zip het voorbeeld van wat
        # niet kan: een startpakket voor een lab, geen stof.
        ("Lab3.zip", FDS, None, "Week 3", "module:Week 3", ".zip"),
        ("weather.txt", SSO, None, None, "assignment:Assignment 1", ".txt"),
    ],
)
def test_an_unsure_or_unsupported_file_gets_a_reason_not_a_place(filename, course, folder, module, source, hint):
    proposal = propose_placement(_file(filename, course=course, folder=folder, module=module, source=source), course, corpus_root=ROOT)

    assert proposal.placement is None
    assert hint in proposal.reason


def test_a_lecture_without_a_week_hints_at_lectures_in_course_yml():
    proposal = propose_placement(_file("lecture7.pdf", course=SSO, folder="statistics/Slides 2026/Lecture 7"), SSO, corpus_root=ROOT)

    assert "lectures" in proposal.reason


def test_the_reason_names_the_evidence():
    """Een reden als 'jaartal of map met literatuur' laat je raden wélke van
    de twee het was."""
    by_folder = propose_placement(_file("matplotlib_cheatsheets.pdf", course=FDS, folder="Readings"), FDS, corpus_root=ROOT)
    by_year = propose_placement(_file("2014-Rougier-PlosCB.pdf", course=FDS), FDS, corpus_root=ROOT)
    by_name = propose_placement(_file("SSO_assignment1.pdf", course=SSO), SSO, corpus_root=ROOT)
    by_aux = propose_placement(_file("Assignment+1+recommendations.pdf", course=FDS, module="Week 3"), FDS, corpus_root=ROOT)

    assert "Readings" in by_folder.reason
    assert "2014" in by_year.reason
    assert "'Assignment 1'" in by_name.reason and "week 3" in by_name.reason
    assert "recommendations" in by_aux.reason and "geen opgavenblad" in by_aux.reason


def test_state_follows_what_the_user_did_and_what_is_already_there():
    file = _file("lecture4.pdf", course=SSO, folder="statistics/Slides 2026/Lecture 4")
    placed = propose_placement(file, SSO, corpus_root=ROOT)
    existing = Document(id="doc", title="x", source_path="sso/slides/week-02/lecture4.pdf", checksum="x", course_slug="sso", doc_kind="slides")

    assert material_state(file, placed, None) == "new"
    assert material_state(file, placed, existing) == "in_corpus"
    file.document_id = "doc"
    assert material_state(file, placed, existing) == "downloaded"
    # Het opgehaalde document is verwijderd: dan is het weer gewoon nieuw.
    assert material_state(file, placed, None) == "new"
    file.ignored_at = datetime(2026, 9, 17)
    assert material_state(file, placed, existing) == "ignored"

    archive = _file("Lab3.zip", course=FDS)
    assert material_state(archive, propose_placement(archive, FDS, corpus_root=ROOT), None) == "unsupported"
    # Een notebook kan wél: hij wacht alleen op een keuze van soort en week.
    notebook = _file("Lab3.ipynb", course=FDS)
    assert material_state(notebook, propose_placement(notebook, FDS, corpus_root=ROOT), None) == "unplaced"
    tables = _file("Statistical_Tables_V2.pdf", course=SSO, folder="statistics")
    assert material_state(tables, propose_placement(tables, SSO, corpus_root=ROOT), None) == "unplaced"


def _page(title: str, *, course: Course, module: str | None) -> CanvasPage:
    return CanvasPage(
        id=f"{course.canvas_id}:x", canvas_course_id=course.canvas_id, page_url="x", title=title, module_name=module,
    )


@pytest.mark.parametrize(
    "title, course, module, expected",
    [
        # Een lab is een oefening: de coach geeft er hints op, en de uitwerking op verzoek.
        ("Instructions Lab 2 - GeoPandas + Seaborn + NetworkX", FDS, "Week 2",
         ("exercise", 2, "fundamentals-of-ds/exercises/week-02/Instructions-Lab-2-GeoPandas-Seaborn-NetworkX.md")),
        ("Details on deriving least squares coefficients (Lecture 4)", FDS, "Week 3",
         ("note", 3, "fundamentals-of-ds/notes/week-03/Details-on-deriving-least-squares-coefficients-Lecture-4.md")),
        # College 3 staat in course.yml in week 2: dat wint van de module.
        ("Extra uitleg bij lecture 3", SSO, "Week 5", ("note", 2, "sso/notes/week-02/Extra-uitleg-bij-lecture-3.md")),
        # Zonder week in de module is een pagina een notitie van het hele vak.
        ("Schedule for the statistics part", SSO, "Course material and assignments",
         ("note", None, "sso/notes/Schedule-for-the-statistics-part.md")),
    ],
)
def test_a_page_becomes_a_note_or_an_exercise(title, course, module, expected):
    proposal = propose_page(_page(title, course=course, module=module), course, corpus_root=ROOT)

    assert proposal.placement is not None
    assert (proposal.placement.doc_kind, proposal.placement.week, proposal.placement.relative_path) == expected
    assert proposal.reason


def test_page_state_follows_the_same_rules_as_a_file():
    page = _page("Schedule for the statistics part", course=SSO, module=None)
    existing = Document(id="doc", title="x", source_path="sso/notes/Schedule-for-the-statistics-part.md", checksum="x",
                        course_slug="sso", doc_kind="note")

    assert page_state(page, None) == "new"
    assert page_state(page, existing) == "in_corpus"
    page.document_id = "doc"
    assert page_state(page, existing) == "downloaded"
    page.ignored_at = datetime(2026, 9, 17)
    assert page_state(page, existing) == "ignored"


def test_the_display_name_counts_when_the_filename_says_nothing():
    """Het voorblad van de SSO-herkansing heet als bestand `ANS+frontcover+and+
    formula+sheet.pdf`; alleen de naam waaronder de docent hem linkt zegt
    "SSO resit 22-12-2022"."""
    file = CanvasFile(
        id=1, canvas_course_id=SSO.canvas_id, filename="ANS+frontcover+and+formula+sheet.pdf",
        display_name="SSO resit 22-12-2022 frontcover and formula sheet.pdf", folder=None,
        module_name="Course material and assignments", source="page:Exam preparation",
    )

    proposal = propose_placement(file, SSO, corpus_root=ROOT)

    assert proposal.placement is not None, proposal.reason
    assert proposal.placement.doc_kind == "exam"
    assert "resit" in proposal.reason
