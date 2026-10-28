"""Code blijft code: regeleinden en inspringing overleven het inlezen.

Proza mag geplet worden — dubbele spaties en afgebroken regels zeggen niets.
Code niet. In Python ís de inspringing de betekenis: welke regels in de lus
vallen bepaalt wat er geprint wordt. Toen de collegeaantekeningen van SSO deel 2
erin kwamen, stond elk codefragment op één regel, en was "wat is de uitvoer
van dit fragment" — precies wat het tentamen vraagt — niet meer te beantwoorden.
"""
from app.services.chunking import chunk_document
from app.services.parsing import ParsedDocument, ParsedPage, normalize_text


CODE = '''```python
for p in products:
    if profit[p] > 3:
        print(p, profit[p])
print("klaar")
```'''


def _doc(text: str, *, outline="Lecture 8 › Knapsack", fmt="notebook") -> ParsedDocument:
    return ParsedDocument(
        title="Lecture 8",
        page_count=1,
        pages=[ParsedPage(page_number=1, text=text, outline_path=outline)],
        metadata={"source_format": fmt},
    )


def test_normalizing_leaves_a_code_block_alone():
    text = f"Tekst   met    spaties.\n\n{CODE}\n\nNog   meer."

    genormaliseerd = normalize_text(text)

    assert "Tekst met spaties." in genormaliseerd
    assert "Nog meer." in genormaliseerd
    assert "    if profit[p] > 3:\n        print(p, profit[p])" in genormaliseerd


def test_normalizing_without_code_is_unchanged():
    assert normalize_text("a  \t b\n\n\n\nc") == "a b\n\nc"


def test_a_note_keeps_its_code_intact():
    """Aantekeningen gaan door de prose-chunker, die met losse woorden werkt."""
    chunks = chunk_document(doc_kind="note", parsed=_doc(f"We lopen de producten af.\n\n{CODE}\n\nDan het resultaat."))

    tekst = "\n".join(chunk.text for chunk in chunks)
    assert "for p in products:\n    if profit[p] > 3:\n        print(p, profit[p])" in tekst
    assert "We lopen de producten af." in tekst


def test_an_exercise_keeps_its_code_intact():
    """Opgavennotebooks gaan per kop door de opgaven-chunker."""
    chunks = chunk_document(doc_kind="exercise", parsed=_doc(f"Exercise 1\nWat print dit?\n\n{CODE}"))

    tekst = "\n".join(chunk.text for chunk in chunks)
    assert "    if profit[p] > 3:\n        print(p, profit[p])" in tekst


def test_the_code_block_starts_on_its_own_line():
    """Een fence midden op een regel is geen fence meer voor een markdownlezer."""
    chunks = chunk_document(doc_kind="note", parsed=_doc(f"Kijk hieronder.\n\n{CODE}"))

    tekst = chunks[0].text
    assert "\n```python\n" in tekst


def test_the_output_block_of_a_notebook_survives_too():
    uitvoer = "Uitvoer:\n\n```text\ndesk 5\nklaar\n```"
    chunks = chunk_document(doc_kind="note", parsed=_doc(f"{CODE}\n\n{uitvoer}"))

    assert "```text\ndesk 5\nklaar\n```" in chunks[0].text


def test_prose_without_code_chunks_as_before():
    tekst = " ".join(f"woord{index}" for index in range(900))

    chunks = chunk_document(doc_kind="note", parsed=_doc(tekst, fmt="markdown"))

    assert len(chunks) >= 2
    assert all("\n```" not in chunk.text for chunk in chunks)
