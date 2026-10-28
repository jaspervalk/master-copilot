"""Antwoord samenstellen uit opgehaald bewijs.

Verschil met een beleidsdomein: de verwijzing dient om na te slaan, niet om te
bewijzen. Er wordt alleen geabstineerd als er niets relevants ligt — een
copilot die bij twijfel zwijgt, is bij studeren onbruikbaar.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas import AnswerCitation, AnswerResponse, QueryChunkResult, QueryFilters
from app.services.coach import CoachContext, policy_instruction
from app.services.retrieval import RetrievalService
from app.services.terms import KEEP_TERMS

try:  # pragma: no cover — de app moet importeerbaar blijven zonder de SDK
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


logger = logging.getLogger(__name__)

ConfidenceBucket = Literal["low", "medium", "high"]
_BUCKET_ORDER = {"low": 0, "medium": 1, "high": 2}

_STYLE_INSTRUCTIONS = {
    "short": (
        "Antwoord kort en direct: hooguit vijf zinnen. Geen inleiding, geen samenvatting achteraf."
    ),
    "explain": (
        "Leg het uit alsof de lezer het onderwerp voor het eerst ziet: bouw op vanaf de kern, "
        "gebruik een voorbeeld waar dat helpt, en benoem de notatie die in het materiaal staat."
    ),
}

_MATH_NOTATION_INSTRUCTION = (
    "Zet wiskunde in LaTeX tussen dollartekens: $...$ in de lopende tekst en $$...$$ op een "
    "eigen regel. Gebruik echte regelovergangen in plaats van de tekens \\n, en gebruik geen "
    "\\( of \\[ als scheidingsteken."
)

# Het antwoordmodel schrijft LaTeX binnen een JSON-string en escapet daarbij zijn
# eigen backslashes. Waar het een witregel bedoelt levert dat `\\n` op, en dat is
# na het parsen een letterlijke backslash-n in plaats van een newline.
#
# Een geëscapete regelovergang en het commando `\nabla` zijn op stringniveau niet
# te onderscheiden: allebei backslash plus n. Kijken of er een letter volgt helpt
# niet, want juist het gewone geval is `\n` gevolgd door de volgende zin. Wat wel
# werkt is de omgekeerde vraag: begint hier een LaTeX-commando dat echt bestaat?
# Zo niet, dan was het een regelovergang.
_LATEX_N_COMMANDS = frozenset(
    {
        "nabla", "natural", "ne", "nearrow", "neg", "negthinspace", "neq", "newline",
        "ni", "nmid", "nolimits", "nonumber", "norm", "not", "notin", "nparallel",
        "nsubseteq", "nsupseteq", "nu", "numberwithin",
    }
)
_LATEX_T_COMMANDS = frozenset(
    {
        "tan", "tanh", "tau", "tbinom", "text", "textbf", "textit", "textrm",
        "textstyle", "tfrac", "therefore", "theta", "tilde", "times", "tiny", "to",
        "top", "triangle", "triangleq", "tt",
    }
)
_LATEX_B_COMMANDS = frozenset(
    {
        "bar", "begin", "beta", "bf", "big", "bigcap", "bigcup", "binom", "bm",
        "bmatrix", "boldsymbol", "bot", "bowtie", "boxed", "bullet",
    }
)
_LATEX_F_COMMANDS = frozenset({"fbox", "flat", "floor", "forall", "frac", "frown"})
_LATEX_R_COMMANDS = frozenset(
    {
        "rangle", "rbrace", "rceil", "rfloor", "rho", "right", "rightarrow",
        "rightleftharpoons", "rm", "rvert",
    }
)
_COMMANDS_BY_LETTER = {
    "b": _LATEX_B_COMMANDS,
    "f": _LATEX_F_COMMANDS,
    "n": _LATEX_N_COMMANDS,
    "r": _LATEX_R_COMMANDS,
    "t": _LATEX_T_COMMANDS,
}

_ESCAPE_RE = re.compile(r"\\([nt])([A-Za-z]*)")

# De andere kant van hetzelfde probleem. Escapet het model zijn LaTeX *niet*
# dubbel, dan sloopt de JSON-parser het commando zelf: "\beta" wordt een
# backspace gevolgd door "eta", "\frac" een formfeed gevolgd door "rac". Het
# teken is onzichtbaar, dus in de UI staat er "$eta_j$" en niemand ziet waarom.
# Juist b, f, n, r en t zijn geldige JSON-escapes én de eerste letter van de
# meest gebruikte commando's in statistiek.
_CONTROL_TO_LETTER = {"\x08": "b", "\x0c": "f", "\r": "r", "\t": "t", "\n": "n"}
_CONTROL_RE = re.compile(r"([\x08\x0c\r\t\n])([A-Za-z]+)")

# Een derde variant, waargenomen op de streamende route: DEL (0x7f) staat waar
# de backslash hoorde te staan — "$\x7fbar X$" in plaats van "$\bar X$". Het is
# niet te reproduceren en de oorzaak is onbekend, maar DEL hoort in geen enkel
# antwoord thuis, dus staat hij vóór letters altijd voor een backslash.
_DEL_BEFORE_LETTERS_RE = re.compile(r"\x7f(?=[A-Za-z])")
_STRAY_CONTROL_RE = re.compile(r"[\x08\x0c\x7f]")


def _restore_control(match: re.Match[str]) -> str:
    control, letters = match.group(1), match.group(2)
    letter = _CONTROL_TO_LETTER[control]
    word = letter + letters
    # Exact matchen, niet op voorvoegsel: "\n" gevolgd door "ote that" moet een
    # regelovergang blijven, ook al is "not" een commando.
    if word in _COMMANDS_BY_LETTER[letter]:
        return "\\" + word
    # Een backspace of formfeed hoort niet in een antwoord; een tab of newline
    # wel, dus die blijven staan.
    if control in ("\x08", "\x0c"):
        return letters
    return match.group(0)


def _resolve_escape(match: re.Match[str]) -> str:
    letter, rest = match.group(1), match.group(2)
    word = letter + rest
    commands = _LATEX_N_COMMANDS if letter == "n" else _LATEX_T_COMMANDS
    # Het langste bekende commando dat vooraan past wint: `\nabla` blijft staan,
    # ook als er direct tekst tegenaan geplakt zit.
    if any(word[:end] in commands for end in range(len(word), 0, -1)):
        return match.group(0)
    return ("\n" if letter == "n" else "\t") + rest


def normalize_answer_text(answer: str) -> str:
    """Maak dubbel-geëscapete regelovergangen weer tot echte witregels.

    Zonder dit staat er letterlijk `\\n` in het antwoord: zichtbaar in de UI, en
    opgeslagen in de querylog die in fase 4 de eval-dataset wordt.
    """
    answer = _DEL_BEFORE_LETTERS_RE.sub(lambda _match: "\\", answer)
    answer = _CONTROL_RE.sub(_restore_control, answer)
    answer = _STRAY_CONTROL_RE.sub("", answer)
    if "\\" not in answer:
        return answer
    return _ESCAPE_RE.sub(_resolve_escape, answer)


_LANGUAGE_INSTRUCTIONS = {
    # "in de taal van de vraag" alleen was niet genoeg: het model volgde de taal
    # van deze instructie en antwoordde in het Nederlands op een Engelse vraag.
    # Daarom staat er nu expliciet bij waar het níet naar moet kijken.
    "auto": (
        "Antwoord in de taal van de vraag — niet in de taal van het materiaal en niet in "
        "die van deze instructie. Een Engelse vraag krijgt een Engels antwoord, een "
        "Nederlandse vraag een Nederlands antwoord."
    ),
    "nl": "Antwoord in het Nederlands, ook als de vraag of het materiaal Engels is.",
    "en": "Answer in English, even when the question or the material is in Dutch.",
}
_NOTATION_INSTRUCTION = f"{KEEP_TERMS} Notatie houd je zoals in het materiaal."

# Zonder deze regel plette het model het onderscheid dat de bron maakt: de slide
# zei "exact normaal bij een normale populatie, bij benadering anders" en het
# antwoord maakte daar één "ongeveer normaal" van. Bij een tentamenvak is juist
# die voorwaarde het punt.
_CONDITIONS_INSTRUCTION = (
    "Noem bij een resultaat ook wanneer het geldt. Maakt het materiaal onderscheid tussen "
    "gevallen — exact versus bij benadering, met of zonder aanname, boven of onder een "
    "grens — neem dat onderscheid dan over in plaats van er één geval van te maken."
)


def build_instructions(
    style: str, coach_policy: str | None = None, language: str = "auto"
) -> str:
    """Eén bron voor de systeeminstructie; de streamende route deelt hem.

    Twee kopieën liepen anders uiteen zodra er een regel bij kwam — de
    wiskundenotatie hierboven is precies zo'n regel. Het coachbeleid komt er
    als apart blok bij, vóór de citatieregels: het beleid bepaalt wát er
    gezegd wordt, de citatieregels hoe.
    """
    coach_block = f"{coach_policy}\n" if coach_policy else ""
    return (
        "Je bent een studiehulp voor een universitaire studie. Beantwoord de vraag "
        "uitsluitend met het aangeboden bewijs uit het studiemateriaal van de student.\n"
        f"{_STYLE_INSTRUCTIONS.get(style, _STYLE_INSTRUCTIONS['explain'])}\n"
        f"{_LANGUAGE_INSTRUCTIONS.get(language, _LANGUAGE_INSTRUCTIONS['auto'])} "
        f"{_NOTATION_INSTRUCTION}\n"
        f"{_MATH_NOTATION_INSTRUCTION}\n"
        f"{_CONDITIONS_INSTRUCTION}\n"
        f"{coach_block}"
        "Verwijs in de lopende tekst met [1], [2], … naar de citaties in je antwoord. "
        "Neem in elke citatie het chunk_id letterlijk over uit het bewijs; verzin er nooit "
        "een. Zet abstained alleen op true wanneer het bewijs de vraag echt niet raakt."
    )


class AnswerCitationDraft(BaseModel):
    chunk_id: str = Field(description="Het chunk_id uit het aangeboden bewijs, letterlijk overgenomen")
    support: str = Field(description="Het letterlijke fragment uit dat bewijs dat de bewering draagt")


class AnswerDraft(BaseModel):
    answer: str
    abstained: bool
    confidence: ConfidenceBucket
    confidence_reasons: list[str] = Field(default_factory=list)
    citations: list[AnswerCitationDraft] = Field(default_factory=list)


def evidence_confidence(
    chunks: list[QueryChunkResult],
    *,
    provider: str,
    min_score: float,
) -> tuple[ConfidenceBucket, list[str]]:
    """Vertrouwen uit het bewijs zelf, niet uit wat het model over zichzelf zegt."""
    if not chunks:
        return "low", ["Er is niets opgehaald uit het corpus."]

    reasons: list[str] = [f"{len(chunks)} fragmenten opgehaald."]
    distinct_documents = {chunk.document_id for chunk in chunks}
    if len(distinct_documents) > 1:
        reasons.append(f"Bewijs uit {len(distinct_documents)} verschillende documenten.")

    # Hash-embeddings leveren cosinusscores die niets zeggen over relevantie;
    # de drempel geldt daarom alleen voor echte embeddings.
    if provider.startswith("local"):
        reasons.append("Embeddingprovider is local-hash; scores zijn niet met de drempel te vergelijken.")
        return ("medium" if len(chunks) >= 2 else "low"), reasons

    top_score = max(chunk.score for chunk in chunks)
    reasons.append(f"Hoogste score {top_score:.2f} (drempel {min_score:.2f}).")
    if top_score < min_score:
        return "low", reasons

    strong = [chunk for chunk in chunks if chunk.score >= min_score]
    if len(strong) >= 3 and len(distinct_documents) >= 2:
        return "high", reasons
    if len(strong) >= 2:
        return ("high" if top_score >= min_score * 2 else "medium"), reasons
    return "medium", reasons


def combine_confidence(model_bucket: ConfidenceBucket, evidence_bucket: ConfidenceBucket) -> ConfidenceBucket:
    """Neem het laagste van beide: een model dat zichzelf overschat, wint niet."""
    return model_bucket if _BUCKET_ORDER[model_bucket] <= _BUCKET_ORDER[evidence_bucket] else evidence_bucket


_MARKER_RE = re.compile(r"\[(\d+)\]")
# Waar een marker wegvalt blijft anders " ," of " ." achter: een spatie vóór
# leesteken, of een komma die niets meer scheidt.
_DANGLING_SEPARATOR_RE = re.compile(r"\s*,(?=\s*[.,;:)])")
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"[ \t]+(?=[.,;:!?)])")


def referenced_evidence_indices(answer: str, evidence_count: int) -> list[int]:
    """De bewijsnummers waar de lopende tekst naar verwijst, in volgorde."""
    seen: list[int] = []
    for match in _MARKER_RE.finditer(answer):
        index = int(match.group(1))
        if 1 <= index <= evidence_count and index not in seen:
            seen.append(index)
    return seen


def renumber_citation_markers(answer: str, mapping: dict[int, int]) -> str:
    """Zet de bewijsnummers uit de prompt om naar de posities in de citatielijst.

    De prompt nummert álle opgehaalde fragmenten [1..N], maar de citatielijst is
    een deelverzameling die weer bij 1 begint. Zonder deze vertaling verwijst het
    antwoord naar een "[7]" die in het bronpaneel niet bestaat.
    """

    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        target = mapping.get(index)
        return f"[{target}]" if target else ""

    tidied = _MARKER_RE.sub(replace, answer)
    tidied = _DANGLING_SEPARATOR_RE.sub("", tidied)
    return _SPACE_BEFORE_PUNCTUATION_RE.sub("", tidied).strip()


def ensure_inline_citation_markers(answer: str, citation_count: int) -> str:
    """Vangnet: zonder markers is niet te zien welke zin waarop steunt."""
    if citation_count <= 0 or not answer.strip():
        return answer
    if re.search(r"\[\d+\]", answer):
        return answer
    markers = " ".join(f"[{index}]" for index in range(1, citation_count + 1))
    return f"{answer.rstrip()} {markers}"


class AnsweringService:
    def __init__(self) -> None:
        self.retrieval_service = RetrievalService()
        self.model = settings.openai_answer_model
        self.client = None
        if settings.openai_api_key and OpenAI is not None:
            try:
                self.client = OpenAI(api_key=settings.openai_api_key)
            except Exception:  # pragma: no cover
                logger.exception("OpenAI-client kon niet worden opgezet; extractieve modus.")

    def retrieve(
        self,
        question: str,
        top_k: int,
        filters: QueryFilters | None = None,
        mode: str = "hybrid",
    ) -> tuple[str, list[QueryChunkResult]]:
        """Alleen ophalen. De streamende route heeft dit apart nodig, omdat hij
        de gevonden fragmenten al toont voordat het antwoord begint te lopen."""
        return self.retrieval_service.search(question, top_k=top_k, filters=filters, mode=mode)

    def compose(
        self,
        *,
        question: str,
        retrieval_query: str | None,
        top_k: int,
        filters: QueryFilters | None,
        mode: str = "hybrid",
        style: str = "explain",
        coach: CoachContext | None = None,
        language: str = "auto",
    ) -> AnswerResponse:
        started = time.perf_counter()
        search_query = retrieval_query or question
        provider, chunks = self.retrieve(search_query, top_k=top_k, filters=filters, mode=mode)
        response = self.compose_from_chunks(
            question=question,
            retrieval_query=retrieval_query,
            chunks=chunks,
            provider=provider,
            style=style,
            coach=coach,
            language=language,
        )
        response.latency_ms = int((time.perf_counter() - started) * 1000)
        return response

    def compose_from_chunks(
        self,
        *,
        question: str,
        retrieval_query: str | None,
        chunks: list[QueryChunkResult],
        provider: str,
        style: str = "explain",
        coach: CoachContext | None = None,
        language: str = "auto",
    ) -> AnswerResponse:
        coach_echo = coach.echo if coach else None
        if not chunks:
            return AnswerResponse(
                question=question,
                rewritten_query=retrieval_query,
                answer=(
                    "Dit staat niet in je materiaal. Voeg het betreffende hoofdstuk of college toe aan "
                    "je corpus, of stel de vraag zonder vak- of weekfilter."
                ),
                abstained=True,
                confidence="low",
                confidence_reasons=["Er is niets opgehaald uit het corpus."],
                citations=[],
                retrieved_chunks=[],
                embedding_provider=provider,
                answer_model="none",
                answer_style=style,
                answer_language=language,
                coach=coach_echo,
            )

        evidence_bucket, evidence_reasons = evidence_confidence(
            chunks, provider=provider, min_score=settings.min_evidence_score
        )
        retrieved = {chunk.chunk_id: chunk for chunk in chunks}

        if self.client is None:
            return self._fallback_answer(
                question=question,
                retrieval_query=retrieval_query,
                chunks=chunks,
                provider=provider,
                style=style,
                evidence_bucket=evidence_bucket,
                evidence_reasons=evidence_reasons,
                coach=coach,
                language=language,
            )

        try:
            parsed = self.client.responses.parse(
                model=self.model,
                instructions=build_instructions(
                    style,
                    policy_instruction(coach.policy, coach.doc_kind) if coach else None,
                    language,
                ),
                input=self._build_prompt(
                    question=question, chunks=chunks, pinned=coach.pinned if coach else ()
                ),
                text_format=AnswerDraft,
            )
            draft: AnswerDraft = parsed.output_parsed
        except Exception:  # pragma: no cover — netwerkpad
            logger.exception("Antwoordmodel faalde; extractieve modus.")
            return self._fallback_answer(
                question=question,
                retrieval_query=retrieval_query,
                chunks=chunks,
                provider=provider,
                style=style,
                evidence_bucket=evidence_bucket,
                evidence_reasons=evidence_reasons,
                coach=coach,
                language=language,
            )

        answer, citations = self.aligned_citations(
            answer=normalize_answer_text(draft.answer),
            chunks=chunks,
            draft_citations=[(item.chunk_id, item.support) for item in draft.citations],
        )
        if not citations and not draft.abstained:
            # Het model gaf geen bruikbare bron; val terug op wat retrieval bovenaan zette.
            citations = self._citation_records(
                draft_citations=[(chunk.chunk_id, self._quote_preview(chunk.text)) for chunk in chunks[:2]],
                retrieved=retrieved,
            )

        return AnswerResponse(
            question=question,
            rewritten_query=retrieval_query,
            answer=ensure_inline_citation_markers(answer, len(citations)),
            abstained=draft.abstained,
            confidence=combine_confidence(draft.confidence, evidence_bucket),
            confidence_reasons=[*draft.confidence_reasons, *evidence_reasons],
            citations=citations,
            retrieved_chunks=chunks,
            embedding_provider=provider,
            answer_model=self.model,
            answer_style=style,
            answer_language=language,
            coach=coach_echo,
        )

    def _fallback_answer(
        self,
        *,
        question: str,
        retrieval_query: str | None,
        chunks: list[QueryChunkResult],
        provider: str,
        style: str,
        evidence_bucket: ConfidenceBucket,
        evidence_reasons: list[str],
        coach: CoachContext | None = None,
        language: str = "auto",
    ) -> AnswerResponse:
        summary = self._quote_preview(chunks[0].text, max_length=600)
        answer = (
            "Er is geen antwoordmodel beschikbaar, dus hier is het meest relevante fragment uit je "
            f"materiaal:\n\n{summary}"
        )
        citations = self._citation_records(
            draft_citations=[(chunk.chunk_id, self._quote_preview(chunk.text)) for chunk in chunks[:2]],
            retrieved={chunk.chunk_id: chunk for chunk in chunks},
        )
        return AnswerResponse(
            question=question,
            rewritten_query=retrieval_query,
            answer=ensure_inline_citation_markers(answer, len(citations)),
            abstained=False,
            confidence=combine_confidence("medium", evidence_bucket),
            confidence_reasons=[*evidence_reasons, "Extractief antwoord: geen antwoordmodel geconfigureerd."],
            citations=citations,
            retrieved_chunks=chunks,
            embedding_provider=provider,
            answer_model="local-extractive",
            answer_style=style,
            answer_language=language,
            coach=coach.echo if coach else None,
        )

    def _build_prompt(self, *, question: str, chunks: list[QueryChunkResult], pinned=()) -> str:
        lines = [f"Vraag: {question}"]
        if pinned:
            # De opdracht staat vóór het bewijs en zonder [n]: het model moet
            # hem lezen, niet citeren.
            lines.append("\nOpdracht waar de student aan werkt:")
            for chunk in pinned:
                lines.append(f"\n{chunk.section_path or ''}\n{chunk.text}".rstrip())
        lines.append("\nBewijs uit het studiemateriaal:")
        for index, chunk in enumerate(chunks, start=1):
            where = chunk.section_path or f"pagina {chunk.page_start}"
            lines.append(
                f"\n[{index}] chunk_id={chunk.chunk_id}\n"
                f"bron: {chunk.document_title} ({chunk.doc_kind}, {where}, "
                f"p. {chunk.page_start}-{chunk.page_end})\n"
                f"{chunk.text}"
            )
        return "\n".join(lines)

    def aligned_citations(
        self,
        *,
        answer: str,
        chunks: list[QueryChunkResult],
        draft_citations: list[tuple[str, str]],
    ) -> tuple[str, list[AnswerCitation]]:
        """Breng de markers in de tekst en de citatielijst op één nummering.

        Het model verwijst met de nummers uit de prompt, die álle opgehaalde
        fragmenten telt. Zijn eigen citatielijst is daar een deelverzameling van
        en soms onvolledig: het schrijft "[7]" zonder fragment 7 ook in
        `citations` te zetten. Beide bronnen worden hier samengevoegd, zodat
        elke verwijzing in de tekst een bron heeft en andersom.
        """
        by_index = {index: chunk for index, chunk in enumerate(chunks, start=1)}
        index_of = {chunk.chunk_id: index for index, chunk in by_index.items()}
        supports = {chunk_id: support for chunk_id, support in draft_citations}

        wanted = {index_of[chunk_id] for chunk_id in supports if chunk_id in index_of}
        wanted.update(referenced_evidence_indices(answer, len(chunks)))

        ordered = sorted(wanted)
        citations = self._citation_records(
            draft_citations=[
                (by_index[index].chunk_id, supports.get(by_index[index].chunk_id, ""))
                for index in ordered
            ],
            retrieved={chunk.chunk_id: chunk for chunk in chunks},
        )

        position = {index: place for place, index in enumerate(ordered, start=1)}
        return renumber_citation_markers(answer, position), citations

    def _citation_records(
        self,
        *,
        draft_citations: list[tuple[str, str]],
        retrieved: dict[str, QueryChunkResult],
    ) -> list[AnswerCitation]:
        records: list[AnswerCitation] = []
        seen: set[str] = set()
        for chunk_id, support in draft_citations:
            chunk = retrieved.get(chunk_id)
            # Onbekende chunk_ids worden weggegooid: nooit een bron verzinnen.
            if chunk is None or chunk_id in seen:
                continue
            seen.add(chunk_id)
            records.append(
                AnswerCitation(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    document_title=chunk.document_title,
                    source_path=chunk.source_path,
                    course_slug=chunk.course_slug,
                    doc_kind=chunk.doc_kind,
                    week=chunk.week,
                    section_path=chunk.section_path,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    quote=self._quote_preview(support or chunk.text),
                )
            )
        return records

    @staticmethod
    def _quote_preview(text: str, max_length: int = 320) -> str:
        compact = " ".join(text.split())
        return compact if len(compact) <= max_length else f"{compact[:max_length].rstrip()}…"
