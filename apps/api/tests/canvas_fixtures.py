"""Canvas-antwoorden in de vorm die de echte API geeft (17 september 2026),
teruggebracht tot wat de tests nodig hebben en zonder namen van anderen.

`routes()` geeft elke keer een verse kopie, zodat een test hem mag verbouwen
(een opdracht weghalen, een endpoint 403 laten geven)."""
from __future__ import annotations

import copy
from typing import Any

FDS = 59831
SSO = 59863
OLD = 6056

_COURSES = [
    {"id": FDS, "name": "Fundamentals of Data Science", "course_code": "5294FUDS6Y", "term": {"name": "2026/27 Sem. 1, per. 1"}},
    {"id": SSO, "name": "Statistics, Simulation and Optimization", "course_code": "5294STSO6Y", "term": {"name": "2026/27 Sem. 1, per. 1"}},
    {"id": OLD, "name": "Master Information Studies", "course_code": "MSc IS", "term": {"name": "Default term"}},
]

_ASSIGNMENTS_FDS = [
    {
        "id": 714239,
        "name": "Assignment 1",
        "description": '<p>Zie het <a href="https://canvas.test/courses/59831/files/9001/download?wrap=1">opgavenblad</a>.</p>',
        "due_at": "2026-09-28T21:59:00Z",
        "unlock_at": "2026-09-12T08:00:00Z",
        "lock_at": None,
        "points_possible": 100.0,
        "submission_types": ["online_upload"],
        "html_url": "https://canvas.test/courses/59831/assignments/714239",
        "submission": {"workflow_state": "unsubmitted", "submitted_at": None, "score": None, "grade": None, "late": False, "missing": False},
    },
    {
        "id": 714241,
        "name": "Final Exam",
        "description": "",
        "due_at": "2026-10-21T07:30:00Z",
        "unlock_at": "2026-10-21T07:30:00Z",
        "lock_at": None,
        "points_possible": 100.0,
        "submission_types": ["on_paper"],
        "html_url": "https://canvas.test/courses/59831/assignments/714241",
        "submission": {"workflow_state": "unsubmitted", "submitted_at": None, "score": None, "grade": None, "late": False, "missing": False},
    },
    {
        "id": 714243,
        "name": "Retake exam",
        "description": "",
        "due_at": "2026-12-14T14:00:00Z",
        "unlock_at": None,
        "lock_at": None,
        "points_possible": 0.0,
        "submission_types": ["none"],
        "html_url": "https://canvas.test/courses/59831/assignments/714243",
        "submission": {"workflow_state": "unsubmitted", "submitted_at": None, "score": None, "grade": None, "late": False, "missing": False},
    },
]

_ASSIGNMENTS_SSO = [
    {
        "id": 704506,
        "name": "Assignment 0",
        "description": "<p>Oefenopdracht, niet beoordeeld.</p>",
        "due_at": None,
        "unlock_at": None,
        "lock_at": None,
        "points_possible": 0.0,
        "submission_types": ["none"],
        "html_url": "https://canvas.test/courses/59863/assignments/704506",
        "submission": {"workflow_state": "unsubmitted", "submitted_at": None, "score": None, "grade": None, "late": False, "missing": False},
    },
    {
        "id": 704507,
        "name": "Assignment 1",
        "description": "<p>Lever het pdf in.</p>",
        "due_at": "2026-09-21T21:59:00Z",
        "unlock_at": "2026-09-09T09:00:00Z",
        "lock_at": None,
        "points_possible": 10.0,
        "submission_types": ["online_upload"],
        "html_url": "https://canvas.test/courses/59863/assignments/704507",
        "submission": {"workflow_state": "graded", "submitted_at": "2026-09-20T15:00:00Z", "score": 8.5, "grade": "8.5", "late": False, "missing": False},
    },
]

_QUIZZES_FDS = [
    {
        "id": 135546,
        "title": "Quiz 1: Pandas & Matplotlib",
        "description": "",
        "quiz_type": "practice_quiz",
        "unlock_at": "2026-09-11T11:00:00Z",
        "lock_at": "2026-10-21T17:00:00Z",
        "due_at": None,
        "show_correct_answers_at": "2026-09-14T07:00:00Z",
        "points_possible": 15.0,
        "html_url": "https://canvas.test/courses/59831/quizzes/135546",
    },
    {
        "id": 135544,
        "title": "Quiz 2: Supervised Learning",
        "description": "",
        "quiz_type": "practice_quiz",
        "unlock_at": "2026-09-18T11:00:00Z",
        "lock_at": "2026-10-21T17:00:00Z",
        "due_at": None,
        "show_correct_answers_at": "2026-09-21T08:00:00Z",
        "points_possible": 15.0,
        "html_url": "https://canvas.test/courses/59831/quizzes/135544",
    },
]

_ANNOUNCEMENTS_FDS = [
    {
        "id": 1159317,
        "title": "Week 3 announcements",
        "posted_at": "2026-09-14T09:29:20Z",
        "read_state": "unread",
        "message": '<p>De slides staan <a href="/courses/59831/files/9002?wrap=1">hier</a>.</p>',
        "html_url": "https://canvas.test/courses/59831/discussion_topics/1159317",
    },
    {
        "id": 1156810,
        "title": "Week 2 announcements",
        "posted_at": "2026-09-07T08:17:18Z",
        "read_state": "read",
        "message": "<p>Welkom in week 2.</p>",
        "html_url": "https://canvas.test/courses/59831/discussion_topics/1156810",
    },
]

_ANNOUNCEMENTS_SSO = [
    {
        "id": 1155000,
        "title": "Assignment templates",
        "posted_at": "2026-09-02T21:55:00Z",
        "read_state": "read",
        "message": "<p>Gebruik de templates.</p>",
        "html_url": "https://canvas.test/courses/59863/discussion_topics/1155000",
    },
]

_MODULES_FDS = [
    {
        "id": 1,
        "name": "Week 3",
        "items": [
            {"id": 11, "type": "File", "title": "20260915_lecture05_classification.pdf", "content_id": 9003},
            {"id": 12, "type": "Page", "title": "Details on deriving least squares", "page_url": "details-on-deriving"},
            {"id": 13, "type": "Assignment", "title": "Assignment 1", "content_id": 714239},
        ],
    }
]

_MODULES_SSO = [
    {
        "id": 2,
        "name": "Course material and assignments",
        "items": [
            {"id": 21, "type": "Page", "title": "Schedule for the statistics part", "page_url": "schedule-for-the-statistics-part"},
        ],
    }
]

_PAGES = {
    "courses/59831/pages/details-on-deriving": {
        "title": "Details on deriving least squares",
        "body": "<p>Geen bestanden.</p>",
        "updated_at": "2026-09-12T10:00:00Z",
        "html_url": "https://canvas.test/courses/59831/pages/details-on-deriving",
    },
    "courses/59863/pages/schedule-for-the-statistics-part": {
        "title": "Schedule for the statistics part",
        "body": (
            '<p><a href="https://canvas.test/courses/59863/files/9004/download?download_frd=1">Slides 4</a>'
            ' en <a href="https://canvas.test/courses/59863/files/9005/download">Section 6.2</a></p>'
        ),
    },
}

_FOLDERS_FDS = [{"id": 3, "full_name": "course files/Lectures slides"}]
_FOLDERS_SSO = [
    {"id": 1, "full_name": "course files/statistics/Slides 2026/Lecture 4"},
    {"id": 2, "full_name": "course files/statistics/Exercises"},
]

_FILES = {
    9001: {"id": 9001, "filename": "FDS_assignment1.pdf", "display_name": "FDS_assignment1.pdf", "size": 120_000, "content-type": "application/pdf", "folder_id": 3, "updated_at": "2026-09-12T07:00:00Z", "url": "https://canvas.test/files/9001/download?verifier=geheim"},
    9002: {"id": 9002, "filename": "Lab3.ipynb", "display_name": "Lab3.ipynb", "size": 41_000, "content-type": "application/octet-stream", "folder_id": 3, "updated_at": "2026-09-14T07:00:00Z", "url": "https://canvas.test/files/9002/download?verifier=geheim"},
    9003: {"id": 9003, "filename": "20260915_lecture05_classification.pdf", "display_name": "20260915_lecture05_classification.pdf", "size": 3_201_000, "content-type": "application/pdf", "folder_id": 3, "updated_at": "2026-09-15T07:00:00Z", "url": "https://canvas.test/files/9003/download?verifier=geheim"},
    9004: {"id": 9004, "filename": "lecture4.pdf", "display_name": "lecture4.pdf", "size": 715_000, "content-type": "application/pdf", "folder_id": 1, "updated_at": "2026-09-10T07:00:00Z", "url": "https://canvas.test/files/9004/download?verifier=geheim"},
    9005: {"id": 9005, "filename": "Section+6.2.pdf", "display_name": "Section+6.2.pdf", "size": 421_000, "content-type": "application/pdf", "folder_id": 2, "updated_at": "2026-08-30T07:00:00Z", "url": "https://canvas.test/files/9005/download?verifier=geheim"},
}

_PLANNER = [
    {
        "plannable_type": "calendar_event",
        "plannable_id": 55,
        "course_id": FDS,
        "plannable_date": "2026-09-16T08:00:00Z",
        "plannable": {"id": 55, "title": "Office hours", "start_at": "2026-09-16T08:00:00Z", "end_at": "2026-09-16T09:00:00Z", "all_day": False},
        "html_url": "https://canvas.test/calendar?event_id=55",
        "submissions": False,
        "planner_override": None,
    },
    {
        "plannable_type": "quiz",
        "plannable_id": 135546,
        "course_id": FDS,
        "plannable_date": "2026-10-21T17:00:00Z",
        "plannable": {"id": 135546, "title": "Quiz 1: Pandas & Matplotlib", "points_possible": 15.0},
        "html_url": "https://canvas.test/courses/59831/quizzes/135546",
        "submissions": False,
        "planner_override": {"marked_complete": True},
    },
    {
        "plannable_type": "assignment",
        "plannable_id": 714239,
        "course_id": FDS,
        "plannable_date": "2026-09-28T21:59:00Z",
        "plannable": {"id": 714239, "title": "Assignment 1", "points_possible": 100.0},
        "html_url": "https://canvas.test/courses/59831/assignments/714239",
        "submissions": {"submitted": False},
        "planner_override": None,
    },
    {
        "plannable_type": "announcement",
        "plannable_id": 1159317,
        "course_id": FDS,
        "plannable_date": "2026-09-14T09:29:20Z",
        "plannable": {"id": 1159317, "title": "Week 3 announcements"},
        "html_url": "https://canvas.test/courses/59831/discussion_topics/1159317",
    },
    {
        "plannable_type": "discussion_topic",
        "plannable_id": 77,
        "course_id": SSO,
        "plannable_date": "2026-09-09T07:18:00Z",
        "plannable": {"id": 77, "title": "Looking for a group"},
        "html_url": "https://canvas.test/courses/59863/discussion_topics/77",
    },
]


def routes() -> dict[str, Any]:
    fixture: dict[str, Any] = {
        "courses": _COURSES,
        "planner/items": _PLANNER,
        f"courses/{FDS}/assignments": _ASSIGNMENTS_FDS,
        f"courses/{SSO}/assignments": _ASSIGNMENTS_SSO,
        f"courses/{OLD}/assignments": [],
        f"courses/{FDS}/quizzes": _QUIZZES_FDS,
        f"courses/{FDS}/quizzes/135546/submissions": {"quiz_submissions": [{"attempt": 1, "score": 13.5, "workflow_state": "complete", "finished_at": "2026-09-11T12:29:00Z"}]},
        f"courses/{FDS}/quizzes/135544/submissions": {"quiz_submissions": []},
        # SSO en het oude vak hebben geen quizzen: Canvas geeft daar 404.
        f"courses/{FDS}/discussion_topics": _ANNOUNCEMENTS_FDS,
        f"courses/{SSO}/discussion_topics": _ANNOUNCEMENTS_SSO,
        f"courses/{OLD}/discussion_topics": [],
        f"courses/{FDS}/modules": _MODULES_FDS,
        f"courses/{SSO}/modules": _MODULES_SSO,
        f"courses/{FDS}/folders": _FOLDERS_FDS,
        f"courses/{SSO}/folders": _FOLDERS_SSO,
        f"courses/{FDS}": {"id": FDS, "name": "Fundamentals of Data Science", "syllabus_body": '<a href="/files/9001">Syllabus</a>'},
        f"courses/{SSO}": {"id": SSO, "name": "Statistics, Simulation and Optimization", "syllabus_body": None},
        # Geen voorpagina: 404, en dat mag.
    }
    fixture.update(_PAGES)
    fixture.update({f"files/{file_id}": meta for file_id, meta in _FILES.items()})
    return copy.deepcopy(fixture)


def course_yml(canvas_id: int, *, assignment_due: str = "2026-09-28") -> str:
    return (
        f"name: Vak {canvas_id}\n"
        f"canvas_id: {canvas_id}\n"
        "exams:\n  - name: Tentamen\n    date: 2026-10-21\n"
        "assignments:\n"
        f"  - name: Assignment 1\n    week: 3\n    due_date: {assignment_due}\n    points: 10\n"
        "weeks:\n"
        "  - week: 1\n    lectures: [1, 2]\n    topics: [intro]\n"
        "  - week: 2\n    lectures: [3, 4]\n    topics: [toetsen]\n"
    )
