"""Kaarten "wat print dit?": het model stelt een fragment voor, de interpreter
levert de sleutel.

De belangrijkste controle zit in wat het model dénkt dat er uitkomt. Klopt dat
niet met wat er echt uitkomt, dan beschrijft de uitleg een uitvoer die er niet
is — en leer je een verkeerde redenering. Zo'n kaart gaat weg.
"""
import pytest

from app.models import Chunk, Document, PracticeCard
from app.services.practice.exam_generation import squash
from app.services.practice.generation import generate_cards
from app.services.practice.output_generation import MAX_SNIPPET_LINES, OutputDraft, check_output_draft
from app.services.practice.snippets import pulp_available


STOF = (
    "The knapsack problem: choose items to maximise value within a weight limit. "
    "We loop over the items and print the ones that fit."
)
MATERIAL = [squash(STOF)]

GOED = "items = {'a': 3, 'b': 5, 'c': 2}\nfor naam, gewicht in items.items():\n    if gewicht <= 3:\n        print(naam)"


def _draft(**overrides):
    velden = dict(
        chunk_id="c",
        question="Wat print dit fragment?",
        code=GOED,
        claimed_output="a\nc",
        explanation="De lus loopt a, b, c af; alleen a (3) en c (2) wegen hooguit 3, dus die worden geprint.",
        source_quote="We loop over the items and print the ones that fit",
    )
    velden.update(overrides)
    return OutputDraft(**velden)


def test_a_good_draft_passes_and_the_key_is_what_really_printed():
    reden, uitvoer = check_output_draft(_draft(), material=MATERIAL, seen=set())

    assert reden is None
    assert uitvoer == "a\nc"


def test_a_draft_that_is_wrong_about_its_own_output_is_refused():
    """Het model dacht 'a' — dan klopt zijn uitleg niet, en leer je die."""
    reden, _ = check_output_draft(_draft(claimed_output="a"), material=MATERIAL, seen=set())

    assert reden is not None and "denkt" in reden


def test_small_formatting_differences_in_the_claim_are_fine():
    reden, _ = check_output_draft(
        _draft(code="print(2 * 2.0)", claimed_output="4", explanation="Twee keer 2.0 is 4.0."),
        material=MATERIAL,
        seen=set(),
    )

    assert reden is None


def test_code_that_does_not_run_is_refused():
    reden, _ = check_output_draft(_draft(code="print(onbekend)"), material=MATERIAL, seen=set())

    assert reden is not None and "NameError" in reden


def test_a_forbidden_import_is_refused_before_running():
    reden, _ = check_output_draft(_draft(code="import os\nprint(os.getcwd())"), material=MATERIAL, seen=set())

    assert reden is not None and "os" in reden


def test_an_output_too_long_to_predict_by_hand_is_refused():
    reden, _ = check_output_draft(
        _draft(code="for i in range(40):\n    print(i)", claimed_output="\n".join(str(i) for i in range(40))),
        material=MATERIAL,
        seen=set(),
    )

    assert reden is not None and "regels" in reden


def test_the_question_must_rest_on_the_material():
    reden, _ = check_output_draft(_draft(source_quote="iets dat nergens staat"), material=MATERIAL, seen=set())

    assert reden is not None and "citaat" in reden


def test_an_explanation_is_required():
    """De uitleg is waar je van leert als je het fout had."""
    reden, _ = check_output_draft(_draft(explanation="  "), material=MATERIAL, seen=set())

    assert reden is not None and "uitleg" in reden


def test_a_code_already_asked_is_skipped():
    reden, _ = check_output_draft(_draft(), material=MATERIAL, seen={squash(GOED)})

    assert reden is not None and "bestaat" in reden


def test_a_snippet_too_long_for_a_card_is_refused():
    """Een kaart is een hap, geen notebookcel. In SSO week 5 waren de fragmenten
    8 tot 13 regels; dat leest als een programma, niet als een tentamenvraag."""
    regels = MAX_SNIPPET_LINES + 1
    reden, _ = check_output_draft(
        _draft(
            code="\n".join(f"print({i})" for i in range(regels)),
            claimed_output="\n".join(str(i) for i in range(regels)),
        ),
        material=MATERIAL,
        seen=set(),
    )

    assert reden is not None and "fragment" in reden and "regels" in reden


def test_blank_lines_do_not_make_a_snippet_too_long():
    reden, _ = check_output_draft(
        _draft(
            code="\n\n".join(f"print({i})" for i in range(MAX_SNIPPET_LINES)),
            claimed_output="\n".join(str(i) for i in range(MAX_SNIPPET_LINES)),
        ),
        material=MATERIAL,
        seen=set(),
    )

    assert reden is None


@pytest.mark.skipif(not pulp_available(), reason="pulp ontbreekt")
def test_solving_a_model_too_big_to_do_by_hand_is_refused():
    """Alle twaalf output-kaarten van SSO week 5 lieten een model oplossen, tot
    een knapsack met zes items. Dan wordt 'wat print dit' eigenlijk 'los dit
    model op in je hoofd'."""
    code = (
        "import pulp\n"
        "m = pulp.LpProblem('k', pulp.LpMaximize)\n"
        "x = pulp.LpVariable.dicts('x', range(4), cat='Binary')\n"
        "m += pulp.lpSum((i + 1) * x[i] for i in range(4))\n"
        "m += pulp.lpSum(x.values()) <= 2\n"
        "m.solve(pulp.PULP_CBC_CMD(msg=False))\n"
        "print(pulp.value(m.objective))"
    )
    reden, _ = check_output_draft(_draft(code=code, claimed_output="7.0"), material=MATERIAL, seen=set())

    assert reden is not None and "variabelen" in reden


@pytest.mark.skipif(not pulp_available(), reason="pulp ontbreekt")
def test_a_model_small_enough_to_solve_by_hand_passes():
    """Twee variabelen: op papier grafisch op te lossen, dus een eerlijke vraag."""
    code = (
        "import pulp\n"
        "m = pulp.LpProblem('m', pulp.LpMaximize)\n"
        "x = pulp.LpVariable('x', lowBound=0)\n"
        "y = pulp.LpVariable('y', lowBound=0)\n"
        "m += 3 * x + 5 * y\n"
        "m += x + 3 * y <= 12\n"
        "m += 2 * x + y <= 10\n"
        "m.solve(pulp.PULP_CBC_CMD(msg=False))\n"
        "print(x.value(), y.value())"
    )
    reden, _ = check_output_draft(_draft(code=code, claimed_output="3.6 2.8"), material=MATERIAL, seen=set())

    assert reden is None


class _FakeClient:
    def __init__(self, drafts):
        self._drafts = drafts
        outer = self
        self.prompts = []

        class _Responses:
            def parse(self, *, model, instructions, input, text_format):
                outer.prompts.append(input)
                return type("Parsed", (), {"output_parsed": text_format(cards=outer._drafts)})()

        self.responses = _Responses()


@pytest.mark.skipif(not __import__("app.services.practice.snippets", fromlist=["x"]).pulp_available(), reason="pulp ontbreekt")
def test_a_card_is_stored_with_the_real_output_as_its_key(db_session):
    stof = (
        "The knapsack problem: we loop over the items and print the ones that fit.\n\n"
        "```python\nimport pulp\nm = pulp.LpProblem('knap', pulp.LpMaximize)\n"
        "x = pulp.LpVariable('x', lowBound=0, upBound=3, cat='Integer')\n```"
    )
    document = Document(
        title="Lecture 8", source_path="sso/notes/week-05/lecture8_integer-optimization.ipynb",
        checksum="k" * 64, course_slug="sso", doc_kind="note", week=5, ingestion_status="indexed",
    )
    document.chunks.append(
        Chunk(chunk_index=0, section_path="Lecture 8 › Knapsack", page_start=1, page_end=1,
              token_count=30, text=stof, normalized_text=stof.lower(), chunk_metadata={})
    )
    db_session.add(document)
    db_session.commit()
    chunk = document.chunks[0]
    fragment = (
        "import pulp\n"
        "m = pulp.LpProblem('t', pulp.LpMaximize)\n"
        "x = pulp.LpVariable('x', lowBound=0, upBound=3, cat='Integer')\n"
        "m += 2 * x\n"
        "m.solve(pulp.PULP_CBC_CMD(msg=False))\n"
        "print(x.value())"
    )

    report = generate_cards(
        db_session, course_slug="sso", section_path="Lecture 8 › Knapsack", kind="output",
        client=_FakeClient([_draft(chunk_id=chunk.id, code=fragment, claimed_output="3",
                                   explanation="2x is maximaal bij de bovengrens x = 3.")]),
        topic="knapsack problem", week=5,
    )

    assert report.rejected == [], report.rejected
    card = db_session.query(PracticeCard).one()
    assert card.kind == "output"
    assert card.setup == fragment
    # De sleutel is wat er echt uitkwam, niet wat het model schreef ("3").
    assert card.reference_answer == "3.0"
    assert card.week == 5
    assert card.spec["topic"] == "knapsack problem"


def test_material_without_code_saves_the_model_call(db_session):
    """Staat er geen code in de stof, dan valt er niets te vragen — en hoeft het
    model niet eens gebeld te worden."""
    document = Document(
        title="Lecture 9", source_path="sso/notes/week-05/lecture9_introduction.ipynb",
        checksum="p" * 64, course_slug="sso", doc_kind="note", week=5, ingestion_status="indexed",
    )
    document.chunks.append(
        Chunk(chunk_index=0, section_path="Lecture 9", page_start=1, page_end=1,
              token_count=30, text=STOF, normalized_text=STOF.lower(), chunk_metadata={})
    )
    db_session.add(document)
    db_session.commit()
    client = _FakeClient([_draft()])

    report = generate_cards(
        db_session, course_slug="sso", section_path="Lecture 9", kind="output", client=client, topic="modeling",
    )

    assert report.created == []
    assert client.prompts == []
    assert "geen code" in report.rejected[0][1]

CODE_STOF = (
    "We model the product mix in pulp.\n\n"
    "```python\nimport pulp\n"
    "m = pulp.LpProblem(name='mix', sense=pulp.LpMaximize)\n"
    "x = pulp.LpVariable(name='x', lowBound=0)\n"
    "m += pulp.lpSum([3 * x])\n```"
)


def test_the_names_the_course_code_uses_are_collected():
    from app.services.practice.output_generation import course_code_names

    namen = course_code_names([CODE_STOF])

    assert {"LpProblem", "LpVariable", "lpSum", "LpMaximize"} <= namen
    # Wat elk Python-fragment gebruikt, zegt niets over de stof.
    assert "print" not in namen and "range" not in namen


def test_prose_without_code_has_no_course_names():
    from app.services.practice.output_generation import course_code_names

    assert course_code_names(["Lecture 9 covers covering, scheduling and transportation."]) == set()


def test_a_snippet_that_uses_nothing_from_the_course_is_refused():
    """In de eerste echte ronde kwamen er kaarten over het printen van
    collegetitels met enumerate — Python lezen, geen optimalisatie."""
    triviaal = _draft(
        code="labels = ['a', 'b', 'c', 'd']\nfor i, x in enumerate(labels):\n    if i % 2 == 0:\n        print(x)",
        claimed_output="a\nc",
    )

    reden, _ = check_output_draft(
        triviaal, material=MATERIAL, seen=set(), course_names={"LpProblem", "LpVariable", "lpSum"}
    )

    assert reden is not None and "stof" in reden


def test_a_snippet_that_uses_the_course_code_passes():
    pulp_fragment = _draft(
        code=(
            "import pulp\n"
            "m = pulp.LpProblem('t', pulp.LpMaximize)\n"
            "x = pulp.LpVariable('x', lowBound=0, upBound=3, cat='Integer')\n"
            "m += 2 * x\n"
            "m.solve(pulp.PULP_CBC_CMD(msg=False))\n"
            "print(x.value())"
        ),
        claimed_output="3.0",
        explanation="De doelfunctie 2x wordt maximaal bij de bovengrens x = 3.",
    )

    reden, uitvoer = check_output_draft(
        pulp_fragment, material=MATERIAL, seen=set(), course_names={"LpProblem", "LpVariable", "lpSum"}
    )

    assert reden is None, reden
    assert uitvoer == "3.0"


def test_without_code_in_the_material_there_is_no_code_question():
    reden, _ = check_output_draft(_draft(), material=MATERIAL, seen=set(), course_names=set())

    assert reden is not None and "geen code" in reden
