"""Notebooks: de collegeaantekeningen van SSO deel 2, en de labs van FDS.

Een notebook wordt markdown en gaat dan dezelfde weg als elk markdownbestand:
koppen worden het kopjespad, codecellen worden codeblokken. De uitvoer blijft
erbij staan, direct onder de code die hem maakte — "wat print dit?" is precies
wat het tentamen van SSO vraagt, en zonder de uitvoer is een codecel maar de
helft van het verhaal.
"""
import json
from pathlib import Path

import pytest

from app.services.parsing import EmptyDocumentError, parse_document
from app.services.parsing.notebook import MAX_OUTPUT_CHARS, notebook_to_markdown
from app.services.path_metadata import SUPPORTED_SUFFIXES


def _nb(*cells) -> dict:
    return {"cells": list(cells), "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


def _md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text}


def _code(source: str, *outputs) -> dict:
    return {"cell_type": "code", "metadata": {}, "source": source, "outputs": list(outputs), "execution_count": 1}


def _stream(text: str) -> dict:
    return {"output_type": "stream", "name": "stdout", "text": text}


def _write(tmp_path: Path, nb: dict, name="lecture8_linear-optimization.ipynb") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(nb), encoding="utf-8")
    return path


def test_notebooks_are_a_supported_format():
    assert ".ipynb" in SUPPORTED_SUFFIXES


def test_headings_become_the_outline(tmp_path):
    nb = _nb(
        _md("# Lecture 8: Linear Optimization\n\nIntro."),
        _md("## Solving the Model Directly in pulp\n\nWe use pulp."),
        _code("import pulp\nprint(pulp.LpMaximize)", _stream("-1\n")),
    )

    parsed = parse_document(_write(tmp_path, nb))

    assert parsed.title == "Lecture 8: Linear Optimization"
    paths = [page.outline_path for page in parsed.pages]
    assert "Lecture 8: Linear Optimization › Solving the Model Directly in pulp" in paths


def test_code_and_its_output_stay_together():
    """De uitvoer staat direct onder zijn code, anders is 'wat print dit?' niet
    uit de stof af te leiden."""
    markdown = notebook_to_markdown(_nb(_code("x = 3\nprint(x * 2)", _stream("6\n"))))

    code_at = markdown.index("print(x * 2)")
    output_at = markdown.index("6")
    assert "```python" in markdown
    assert code_at < output_at
    assert "Uitvoer" in markdown


def test_a_returned_value_counts_as_output():
    result = {"output_type": "execute_result", "data": {"text/plain": "'Optimal'"}, "metadata": {}, "execution_count": 2}

    assert "'Optimal'" in notebook_to_markdown(_nb(_code("pulp.LpStatus[1]", result)))


def test_an_image_is_named_not_embedded():
    """Een plot staat als base64 in het notebook. Dat hoort niet in een chunk,
    en al helemaal niet in een embedding."""
    image = {"output_type": "display_data", "data": {"image/png": "iVBORw0KGgo" * 500, "text/plain": "<Figure>"}, "metadata": {}}

    markdown = notebook_to_markdown(_nb(_code("plt.plot([1, 2])", image)))

    assert "iVBORw0KGgo" not in markdown
    assert "[figuur]" in markdown


def test_a_long_output_is_cut():
    markdown = notebook_to_markdown(_nb(_code("print('x' * 10_000)", _stream("x" * 10_000))))

    assert len(markdown) < MAX_OUTPUT_CHARS + 500
    assert "ingekort" in markdown


def test_an_error_output_keeps_its_message():
    error = {"output_type": "error", "ename": "ZeroDivisionError", "evalue": "division by zero", "traceback": ["..."]}

    assert "ZeroDivisionError: division by zero" in notebook_to_markdown(_nb(_code("1 / 0", error)))


def test_a_comment_in_code_is_not_a_heading(tmp_path):
    nb = _nb(
        _md("# Lecture 8\n\nTekst."),
        _code("# Import pulp\nimport pulp", _stream("")),
    )

    parsed = parse_document(_write(tmp_path, nb))

    assert all("Import pulp" not in (page.outline_path or "") for page in parsed.pages)


def test_source_as_a_list_of_lines_works_too():
    """nbformat staat beide toe: één string of een lijst regels."""
    cell = {"cell_type": "markdown", "metadata": {}, "source": ["# Titel\n", "\n", "Tekst."]}

    assert "# Titel" in notebook_to_markdown(_nb(cell))


def test_an_exercise_notebook_is_split_per_heading(tmp_path):
    """Opgaven staan onder hun eigen kop, net als in een markdownopgavenblad."""
    nb = _nb(
        _md("# Lecture 8: Exercises"),
        _md("## Exercise 1\n\nFormuleer het productmixprobleem."),
        _md("## Exercise 2\n\nLos het knapzakprobleem op."),
    )

    parsed = parse_document(_write(tmp_path, nb, name="lecture8_exercises.ipynb"))

    assert parsed.metadata["source_format"] == "notebook"


def test_an_empty_notebook_is_refused(tmp_path):
    with pytest.raises(EmptyDocumentError):
        parse_document(_write(tmp_path, _nb()))


def test_broken_json_is_a_clear_error(tmp_path):
    path = tmp_path / "kapot.ipynb"
    path.write_text("{ geen json", encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        parse_document(path)

    assert "notebook" in str(caught.value)


# --- Python-scripts: de demo's bij de colleges van SSO deel 2 -----------------

DEMO = '''"""Product mix: lecture 8."""
import pulp

profit = {"bookcase": 3, "desk": 5}
model = pulp.LpProblem("product_mix", pulp.LpMaximize)
x = {p: pulp.LpVariable(p, lowBound=0) for p in profit}
model += pulp.lpSum(profit[p] * x[p] for p in profit)
for p in profit:
    if profit[p] > 3:
        print(p)
'''


def test_scripts_are_a_supported_format():
    assert ".py" in SUPPORTED_SUFFIXES


def test_a_script_keeps_its_code_intact(tmp_path):
    """De demo's van SSO deel 2 zijn de code waarvan het tentamen vraagt wat hij
    print. Inspringing hoort erbij: wat er in de lus valt bepaalt de uitvoer."""
    path = tmp_path / "lecture_8_product_mix.py"
    path.write_text(DEMO, encoding="utf-8")

    parsed = parse_document(path)
    tekst = "\n".join(page.text for page in parsed.pages)

    assert parsed.title == "Lecture 8 product mix"
    assert "for p in profit:\n    if profit[p] > 3:\n        print(p)" in tekst
    assert parsed.metadata["source_format"] == "script"


def test_a_comment_in_a_script_is_not_a_heading(tmp_path):
    path = tmp_path / "demo.py"
    path.write_text("# Import pulp\nimport pulp\nprint(pulp.__version__)\n", encoding="utf-8")

    parsed = parse_document(path)

    assert all("Import pulp" not in (page.outline_path or "") for page in parsed.pages)


def test_an_empty_script_is_refused(tmp_path):
    path = tmp_path / "leeg.py"
    path.write_text("\n\n", encoding="utf-8")

    with pytest.raises(EmptyDocumentError):
        parse_document(path)
