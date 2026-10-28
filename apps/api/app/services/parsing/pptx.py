from __future__ import annotations

from pathlib import Path

from pptx import Presentation

from app.services.parsing import ParsedDocument, ParsedPage, normalize_text


def _slide_text(slide) -> str:
    lines: list[str] = []
    for shape in slide.shapes:
        if not getattr(shape, "has_text_frame", False):
            continue
        for paragraph in shape.text_frame.paragraphs:
            line = normalize_text("".join(run.text for run in paragraph.runs) or paragraph.text)
            if line:
                lines.append(line)
    if slide.has_notes_slide:
        notes = normalize_text(slide.notes_slide.notes_text_frame.text or "")
        if notes:
            lines.append(f"[notities] {notes}")
    return "\n".join(lines).strip()


def parse_pptx(file_path: Path) -> ParsedDocument:
    presentation = Presentation(str(file_path))
    pages: list[ParsedPage] = []
    for index, slide in enumerate(presentation.slides, start=1):
        text = _slide_text(slide)
        if text:
            pages.append(ParsedPage(page_number=index, text=text))

    title = pages[0].text.splitlines()[0] if pages else file_path.stem.replace("-", " ").title()
    # page_count telt de slides mét tekst: een lege slide levert geen chunk op
    # en hoort dus ook niet in de corpusweergave mee te tellen.
    return ParsedDocument(
        title=title,
        page_count=len(pages),
        pages=pages,
        metadata={"source_format": "pptx"},
    )
