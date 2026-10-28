"""De evalset: vragen met een verwachte vindplaats.

Verwachtingen wijzen naar `source_path` en paginabereik, nooit naar een
chunk_id — die is een UUID die bij elke herindexering verandert, en een
evalset die daarop leunt is na één `sync` waardeloos.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class CaseFileError(ValueError):
    """eval/cases.yml is onleesbaar of inhoudelijk fout."""


class ExpectedHit(BaseModel):
    source_path: str
    pages: tuple[int, int]

    @field_validator("pages", mode="before")
    @classmethod
    def _one_number_is_a_range(cls, value):
        # `pages: 12` is prettiger dan `pages: [12, 12]` voor een enkele bladzijde.
        if isinstance(value, int):
            return (value, value)
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return (int(value[0]), int(value[1]))
        raise ValueError("pages moet één getal of [begin, eind] zijn")

    @model_validator(mode="after")
    def _ordered(self):
        if self.pages[0] > self.pages[1]:
            raise ValueError(f"pages {self.pages}: begin ligt na eind")
        return self


class CoachCase(BaseModel):
    # source_path van de opdracht: stabiel over herindexeringen, net als expected.
    document: str
    reveal: bool = False


class EvalCase(BaseModel):
    id: str
    course_slug: str | None = None
    question: str = Field(min_length=3)
    expected: list[ExpectedHit] = Field(default_factory=list)
    expect_abstain: bool = False
    must_mention: list[str] = Field(default_factory=list)
    # Termen die níet in het antwoord mogen staan: het eindantwoord van een
    # opdracht. Meet of de coach dichthoudt.
    must_not_mention: list[str] = Field(default_factory=list)
    coach: CoachCase | None = None
    # Door eval-seed aangemaakt en nog niet nagekeken. De runner slaat deze
    # over: een verwachting die niemand heeft bevestigd is geen meetlat.
    unverified: bool = False

    @model_validator(mode="after")
    def _expected_xor_abstain(self):
        if self.expect_abstain and self.expected:
            raise ValueError("expect_abstain en expected sluiten elkaar uit")
        if not self.expect_abstain and not self.expected:
            raise ValueError("een case heeft expected nodig, of expect_abstain: true")
        return self


class _CaseFile(BaseModel):
    cases: list[EvalCase]


def load_cases(path: Path) -> list[EvalCase]:
    if not path.exists():
        raise CaseFileError(f"{path} bestaat niet")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CaseFileError(f"{path} is geen geldige YAML: {exc}") from exc

    try:
        parsed = _CaseFile.model_validate(raw)
    except ValidationError as exc:
        raise CaseFileError(f"{path}: {exc}") from exc

    seen: set[str] = set()
    for case in parsed.cases:
        if case.id in seen:
            raise CaseFileError(f"case-id '{case.id}' komt twee keer voor")
        seen.add(case.id)
    return parsed.cases
