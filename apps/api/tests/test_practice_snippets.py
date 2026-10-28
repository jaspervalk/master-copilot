"""Codefragmenten uitvoeren en een voorspelde uitvoer nakijken.

"Wat is de uitvoer van dit fragment" — zo vraagt het tentamen van SSO deel 2.
Het goede antwoord komt hier niet van een model maar van het uitvoeren: het
fragment draait, en wat het print is de sleutel. Dezelfde afspraak als overal:
het model stelt voor, de interpreter beslist.

Het nakijken is mild waar de docent mild is. "Een vergeten komma, maak je geen
zorgen" ging over schrijven; bij voorspellen betekent het: 4 of 4.0, enkele of
dubbele aanhalingstekens, een spatie meer of minder — dat telt niet. Een ander
getal of een regel te weinig telt wél.
"""
import pytest

from app.services.practice.snippets import (
    SnippetRejected,
    outputs_match,
    pulp_available,
    run_snippet,
    run_snippet_measured,
    validate_snippet,
)


# --- nakijken ---------------------------------------------------------------


def test_the_same_output_matches():
    assert outputs_match("integer optimum: 4\n", "integer optimum: 4")


def test_whitespace_does_not_count():
    assert outputs_match("x = 3\ny = 5", "  x =  3\n\ny = 5  \n")


def test_four_and_four_point_zero_are_the_same_number():
    """PuLP geeft `4.0` terug; wie 4 opschrijft heeft het goed."""
    assert outputs_match("desk 4.0", "desk 4")
    assert outputs_match("desk 4", "desk 4.0")


def test_a_rounded_answer_counts_if_it_rounds_correctly():
    assert outputs_match("objective = 3.3333333333", "objective = 3.33")
    assert not outputs_match("objective = 3.3333333333", "objective = 3.34")


def test_an_integer_for_a_fraction_is_wrong():
    """'3' voor 3.33 is geen afronding maar een ander getal."""
    assert not outputs_match("3.3333333333", "3")


def test_quote_style_does_not_count():
    assert outputs_match("{'desk': 4.0}", '{"desk": 4}')


def test_a_different_number_is_wrong():
    assert not outputs_match("desk 4.0", "desk 3.0")


def test_a_missing_line_is_wrong():
    assert not outputs_match("Optimal\n29.0", "Optimal")


def test_the_status_word_must_be_right():
    assert not outputs_match("Optimal", "Infeasible")


def test_an_empty_answer_is_wrong():
    assert not outputs_match("Optimal", "   ")


# --- de grens om de code ------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "import pulp\nprint(1)",
        "import numpy as np\nprint(np.arange(3).sum())",
        "from itertools import permutations\nprint(len(list(permutations('abc'))))",
        "import random\nrandom.seed(1)\nprint(random.randint(1, 6))",
    ],
)
def test_the_libraries_of_the_course_are_allowed(code):
    validate_snippet(code)


@pytest.mark.parametrize(
    "code, woord",
    [
        ("import os\nprint(os.listdir('.'))", "os"),
        ("import subprocess", "subprocess"),
        ("print(open('/etc/passwd').read())", "open"),
        ("__import__('os').system('ls')", "__import__"),
        ("exec('print(1)')", "exec"),
        ("from pathlib import Path", "pathlib"),
    ],
)
def test_what_a_snippet_does_not_need_is_refused(code, woord):
    """Het fragment komt van een model en draait zonder dat iemand het leest."""
    with pytest.raises(SnippetRejected) as caught:
        validate_snippet(code)

    assert woord in str(caught.value)


# --- uitvoeren ----------------------------------------------------------------


def test_running_returns_what_was_printed():
    assert run_snippet("for i in range(3):\n    print(i * 2)") == "0\n2\n4"


def test_an_error_is_named():
    with pytest.raises(SnippetRejected) as caught:
        run_snippet("print(1 / 0)")

    assert "ZeroDivisionError" in str(caught.value)


def test_an_endless_loop_is_stopped():
    with pytest.raises(SnippetRejected) as caught:
        run_snippet("while True:\n    pass", timeout=2)

    assert "lang" in str(caught.value)


def test_output_that_differs_between_runs_is_refused():
    """Een ongeseede willekeurige trekking kun je niet voorspellen; dan is het
    ook geen vraag."""
    with pytest.raises(SnippetRejected) as caught:
        run_snippet("import random\nprint(random.random())")

    assert "verschilt" in str(caught.value)


def test_a_snippet_that_prints_nothing_is_refused():
    with pytest.raises(SnippetRejected) as caught:
        run_snippet("x = 3")

    assert "niets" in str(caught.value)


@pytest.mark.skipif(not pulp_available(), reason="pulp niet geïnstalleerd")
def test_a_pulp_model_from_the_notes_runs_as_written():
    """De aantekeningen vragen `getSolver("COIN_CMD")`, dat een losse cbc nodig
    heeft. Die is dezelfde solver als de meegeleverde, dus die wordt gebruikt —
    en de code draait zoals hij in de stof staat."""
    code = (
        "import pulp\n"
        "m = pulp.LpProblem('t', pulp.LpMaximize)\n"
        "x = pulp.LpVariable('x', lowBound=0, upBound=4, cat='Integer')\n"
        "m += 3 * x\n"
        "m.solve(pulp.getSolver('COIN_CMD', msg=False))\n"
        "print(pulp.LpStatus[m.status], x.value())"
    )

    assert run_snippet(code) == "Optimal 4.0"


@pytest.mark.skipif(not pulp_available(), reason="pulp niet geïnstalleerd")
def test_the_sandbox_reports_how_many_variables_each_solved_model_had():
    """Of je een uitvoer met de hand kunt voorspellen hangt af van hoe groot het
    model is dat het fragment oplost. Dat telt de interpreter, niet een regex:
    `LpVariable.dicts` over een lijst is in de code één regel en in het model
    vier variabelen."""
    code = (
        "import pulp\n"
        "m = pulp.LpProblem('t', pulp.LpMaximize)\n"
        "x = pulp.LpVariable.dicts('x', ['a', 'b', 'c', 'd'], cat='Binary')\n"
        "m += pulp.lpSum(x.values())\n"
        "m += x['a'] + x['b'] <= 1\n"
        "m.solve(pulp.PULP_CBC_CMD(msg=False))\n"
        "print(pulp.value(m.objective))"
    )

    uitvoer, groottes = run_snippet_measured(code)

    assert uitvoer == "3.0"
    assert groottes == [4]


def test_a_snippet_that_solves_nothing_reports_no_models():
    assert run_snippet_measured("print(2 + 2)") == ("4", [])


def test_a_snippet_with_a_null_byte_is_refused_not_a_crash():
    with pytest.raises(SnippetRejected):
        validate_snippet("print(1)\x00")
