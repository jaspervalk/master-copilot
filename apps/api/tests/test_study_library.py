"""Externe uitleg bij de onderwerpen van je eigen weken.

De koppeling mag niet gokken: een bron verschijnt bij een onderwerp als een van
zijn trefwoorden als heel woord in dat onderwerp staat. Een onderwerp zonder
match blijft leeg — beter niets dan een link die er niet over gaat.
"""
import pytest

from app.models import Course
from app.services.study.library import Resource, load_library, matches, topics_with_resources


def _bronnen():
    return [
        Resource(
            name="StatQuest",
            url="https://statquest.org/",
            kind="video",
            license="alleen kijken",
            note="",
            topics=["regression", "logistic"],
        ),
        Resource(
            name="Seeing Theory",
            url="https://seeing-theory.brown.edu/",
            kind="interactief",
            license="educatief",
            note="",
            topics=["probability", "sampling"],
        ),
    ]


def test_a_keyword_matches_as_a_whole_word():
    bron = _bronnen()[0]

    assert matches(bron, "logistic regression") is True
    assert matches(bron, "linear regression") is True
    assert matches(bron, "contingency tables") is False


def test_a_keyword_inside_another_word_does_not_count():
    """'gam' mag niet aanslaan op 'gambling' of 'gamma'."""
    bron = Resource(name="x", url="u", kind="video", license="l", note="", topics=["gam"])

    assert matches(bron, "generalized additive models (gam)") is True
    assert matches(bron, "gamma distribution") is False


def test_topics_come_from_the_weeks_of_this_course(db_session):
    db_session.add(
        Course(
            slug="sso",
            name="SSO",
            week_plans={
                "1": {"lectures": [1], "topics": ["probability distributions"], "reading": []},
                "3": {"lectures": [5], "topics": ["linear regression", "contingency tables"], "reading": []},
            },
        )
    )
    db_session.commit()

    rijen = topics_with_resources(db_session, "sso", resources=_bronnen())

    assert [(rij.week, rij.topic) for rij in rijen] == [
        (1, "probability distributions"),
        (3, "linear regression"),
        (3, "contingency tables"),
    ]
    assert [bron.name for bron in rijen[0].resources] == ["Seeing Theory"]
    assert [bron.name for bron in rijen[1].resources] == ["StatQuest"]
    # Geen match: leeg, niet iets willekeurigs.
    assert rijen[2].resources == []


def test_a_course_without_weeks_gives_nothing(db_session):
    db_session.add(Course(slug="sso", name="SSO", week_plans={}))
    db_session.commit()

    assert topics_with_resources(db_session, "sso", resources=_bronnen()) == []


def test_the_real_library_loads_and_every_entry_is_complete():
    """De lijst wordt met de hand bijgehouden; een halve regel valt hier op."""
    library = load_library()

    assert library.resources, "er staan geen bronnen in resources/library.yml"
    for resource in library.resources:
        assert resource.name and resource.url.startswith("http")
        assert resource.license, f"{resource.name} heeft geen licentie"
        assert resource.topics, f"{resource.name} hangt aan geen enkel onderwerp"
    for claim in library.method:
        assert claim.url.startswith("http")
        assert claim.source and claim.title and claim.strength
