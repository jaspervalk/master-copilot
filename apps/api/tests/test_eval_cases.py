from pathlib import Path

import pytest

from app.eval.cases import CaseFileError, load_cases


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "cases.yml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_a_valid_case_with_page_range(tmp_path):
    path = _write(
        tmp_path,
        """
cases:
  - id: islr-kfold
    course_slug: sso
    question: hoe werkt k-fold cross-validation?
    expected:
      - source_path: sso/books/ISLRv2.pdf
        pages: [214, 216]
""",
    )

    cases = load_cases(path)

    assert len(cases) == 1
    assert cases[0].id == "islr-kfold"
    assert cases[0].expected[0].pages == (214, 216)
    assert cases[0].unverified is False


def test_a_single_page_may_be_written_as_one_number(tmp_path):
    path = _write(
        tmp_path,
        """
cases:
  - id: one
    course_slug: sso
    question: vraag
    expected:
      - source_path: a.pdf
        pages: 12
""",
    )

    assert load_cases(path)[0].expected[0].pages == (12, 12)


def test_reversed_page_range_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
cases:
  - id: one
    course_slug: sso
    question: vraag
    expected:
      - source_path: a.pdf
        pages: [20, 10]
""",
    )

    with pytest.raises(CaseFileError, match="pages"):
        load_cases(path)


def test_case_needs_expected_or_expect_abstain(tmp_path):
    path = _write(
        tmp_path,
        """
cases:
  - id: one
    course_slug: sso
    question: vraag zonder verwachting
""",
    )

    with pytest.raises(CaseFileError, match="expected"):
        load_cases(path)


def test_abstain_case_may_not_also_expect_pages(tmp_path):
    path = _write(
        tmp_path,
        """
cases:
  - id: one
    course_slug: sso
    question: vraag
    expect_abstain: true
    expected:
      - source_path: a.pdf
        pages: 1
""",
    )

    with pytest.raises(CaseFileError, match="expect_abstain"):
        load_cases(path)


def test_duplicate_ids_are_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
cases:
  - id: dup
    course_slug: sso
    question: a
    expect_abstain: true
  - id: dup
    course_slug: sso
    question: b
    expect_abstain: true
""",
    )

    with pytest.raises(CaseFileError, match="dup"):
        load_cases(path)


def test_unverified_flag_is_preserved(tmp_path):
    path = _write(
        tmp_path,
        """
cases:
  - id: seed-1
    course_slug: sso
    question: vraag
    unverified: true
    expected:
      - source_path: a.pdf
        pages: 3
""",
    )

    assert load_cases(path)[0].unverified is True


def test_missing_file_is_a_case_file_error(tmp_path):
    with pytest.raises(CaseFileError, match="bestaat niet"):
        load_cases(tmp_path / "nope.yml")


def test_coach_case_and_must_not_mention_load(tmp_path):
    path = _write(
        tmp_path,
        """
cases:
  - id: coach-a1
    course_slug: sso
    question: hoe begin ik met opgave 1?
    coach:
      document: sso/assignments/week-04/a1.pdf
    must_not_mention: ["2.92"]
    expected:
      - source_path: sso/books/x.pdf
        pages: 10
""",
    )

    case = load_cases(path)[0]

    assert case.coach.document == "sso/assignments/week-04/a1.pdf"
    assert case.coach.reveal is False
    assert case.must_not_mention == ["2.92"]
