"""Jupyter-notebooks: de collegeaantekeningen van SSO deel 2, de labs van FDS.

Een notebook wordt eerst markdown en gaat dan door dezelfde parser als elk
`.md`-bestand (`parse_markdown_text`). Zo is er één plek waar koppen een
kopjespad worden, en weten de chunkers niet eens dat er een notebook was.

De uitvoer van een codecel blijft staan, direct onder de code die hem maakte.
Dat is de reden om notebooks überhaupt in te lezen in plaats van de `.py`-versie
ernaast: het tentamen van SSO vraagt "wat is de uitvoer van dit codefragment",
en zonder de uitvoer is een codecel maar de helft van het antwoord.

Wat er níet in komt: plaatjes. Een plot staat als base64 in het notebook; dat
is geen tekst, en in een embedding bij OpenAI hoort het al helemaal niet.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.parsing import ParsedDocument, title_from_filename
from app.services.parsing.markdown import parse_markdown_text


# Een dataframe van duizend rijen of een solverlog is geen stof. Genoeg om te
# zien wát er uitkomt, niet alles.
MAX_OUTPUT_CHARS = 1500


def _text(value) -> str:
    """nbformat staat beide toe: één string, of een lijst regels."""
    if isinstance(value, list):
        return "".join(str(part) for part in value)
    return str(value or "")


def _output_text(output: dict) -> str:
    kind = output.get("output_type")
    if kind == "stream":
        return _text(output.get("text"))
    if kind == "error":
        return f"{output.get('ename', 'Error')}: {output.get('evalue', '')}"
    if kind in ("execute_result", "display_data"):
        data = output.get("data") or {}
        if any(key.startswith("image/") for key in data):
            return "[figuur]"
        return _text(data.get("text/plain"))
    return ""


def _cap(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS].rstrip() + "\n… (uitvoer ingekort)"


def notebook_to_markdown(notebook: dict) -> str:
    """Het notebook als markdown: tekstcellen letterlijk, code in een blok, de
    uitvoer eronder."""
    blocks: list[str] = []
    for cell in notebook.get("cells") or []:
        source = _text(cell.get("source")).strip()
        kind = cell.get("cell_type")
        if kind == "markdown":
            if source:
                blocks.append(source)
        elif kind == "code":
            if source:
                blocks.append(f"```python\n{source}\n```")
            uitvoer = "\n".join(
                part for part in (_output_text(output).rstrip() for output in cell.get("outputs") or []) if part
            )
            if uitvoer:
                blocks.append(f"Uitvoer:\n\n```text\n{_cap(uitvoer)}\n```")
    return "\n\n".join(blocks) + "\n"


def parse_notebook(file_path: Path) -> ParsedDocument:
    try:
        notebook = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"'{file_path.name}' is geen leesbaar notebook: {exc.msg}") from None
    return parse_markdown_text(notebook_to_markdown(notebook), stem=file_path.stem, source_format="notebook")


def parse_script(file_path: Path) -> ParsedDocument:
    """Een Python-script: de demo's bij de colleges van SSO deel 2.

    Het hele script wordt één codeblok onder een kop met de bestandsnaam, en
    gaat dan door dezelfde parser als een notebook. Zo blijft de inspringing
    staan (`normalize_text` laat een codeblok heel) en wordt een
    `# commentaar` in de code geen kop.
    """
    code = file_path.read_text(encoding="utf-8").strip("\n")
    if not code.strip():
        return ParsedDocument(title=file_path.stem, page_count=0, pages=[], metadata={"source_format": "script"})
    title = title_from_filename(file_path.stem)
    return parse_markdown_text(f"# {title}\n\n```python\n{code}\n```\n", stem=file_path.stem, source_format="script")
