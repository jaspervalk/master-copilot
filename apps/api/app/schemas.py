from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.path_metadata import DOC_KINDS


DocKindLiteral = Literal[
    "book", "paper", "slides", "assignment", "exercise", "submission", "solution", "note", "exam"
]
RetrievalMode = Literal["dense", "hybrid"]
AnswerStyle = Literal["short", "explain"]
# "auto" volgt de taal van de vraag; de andere twee pinnen hem vast.
AnswerLanguage = Literal["auto", "nl", "en"]
ConfidenceBucket = Literal["low", "medium", "high"]

# Vangnet tegen uiteenlopen: het literal-type hierboven en de gesloten
# verzameling in path_metadata moeten dezelfde soorten beschrijven.
assert set(DOC_KINDS) == {
    "book",
    "paper",
    "slides",
    "assignment",
    "exercise",
    "submission",
    "solution",
    "note",
    "exam",
}, "DocKindLiteral loopt uit de pas met DOC_KINDS"


class QueryFilters(BaseModel):
    course_slug: str | None = None
    week: int | None = None
    doc_kinds: list[DocKindLiteral] | None = None
    assignment_status: Literal["open", "submitted", "closed"] | None = None

    def is_empty(self) -> bool:
        return not any([self.course_slug, self.week, self.doc_kinds, self.assignment_status])


class CoachOptions(BaseModel):
    document_id: str
    # Alleen zinvol bij een exercise; bij een beoordeelde opdracht wordt hij genegeerd.
    reveal: bool = False


CoachPolicy = Literal["hints", "reveal"]


class CoachEcho(BaseModel):
    document_id: str
    document_title: str
    policy: CoachPolicy


class QueryChunkResult(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    source_path: str
    course_slug: str
    doc_kind: str
    week: int | None = None
    assignment_status: str | None = None
    section_path: str | None = None
    page_start: int
    page_end: int
    score: float
    text: str
    chunk_metadata: dict = Field(default_factory=dict)


class QueryRequest(BaseModel):
    question: str = Field(min_length=3)
    top_k: int = Field(default=8, ge=1, le=25)
    filters: QueryFilters | None = None
    retrieval_mode: RetrievalMode = "hybrid"


class QueryResponse(BaseModel):
    question: str
    embedding_provider: str
    top_k: int
    results: list[QueryChunkResult]


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    source_path: str
    course_slug: str
    doc_kind: str
    week: int | None
    assignment_status: str | None
    ingestion_status: str
    page_count: int
    chunk_count: int
    parse_error: str | None
    indexed_at: datetime | None
    created_at: datetime


class UploadDocumentResponse(BaseModel):
    document: DocumentRead
    chunk_count: int
    embedding_provider: str
    embedding_dimensions: int


class IndexDocumentResponse(BaseModel):
    document: DocumentRead
    chunk_count: int
    embedding_provider: str
    embedding_dimensions: int


class DeleteDocumentResponse(BaseModel):
    document_id: str
    title: str
    deleted_chunk_count: int
    removed_from_index: bool
    trashed_path: str | None


class CourseRead(BaseModel):
    slug: str
    name: str
    period: str | None = None
    lecturer: str | None = None
    document_count: int
    weeks: list[int]
    open_assignment_count: int


class AnswerCitation(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    source_path: str
    course_slug: str
    doc_kind: str
    week: int | None = None
    section_path: str | None = None
    page_start: int
    page_end: int
    quote: str


class AnswerResponse(BaseModel):
    question: str
    rewritten_query: str | None = None
    answer: str
    abstained: bool
    confidence: ConfidenceBucket
    confidence_reasons: list[str] = Field(default_factory=list)
    citations: list[AnswerCitation] = Field(default_factory=list)
    retrieved_chunks: list[QueryChunkResult] = Field(default_factory=list)
    embedding_provider: str
    answer_model: str
    answer_style: AnswerStyle
    answer_language: AnswerLanguage = "auto"
    latency_ms: int | None = None
    coach: CoachEcho | None = None


class ChatRequest(BaseModel):
    question: str = Field(min_length=3)
    conversation_id: str | None = None
    top_k: int = Field(default=8, ge=1, le=25)
    filters: QueryFilters | None = None
    retrieval_mode: RetrievalMode = "hybrid"
    answer_style: AnswerStyle = "explain"
    answer_language: AnswerLanguage = "auto"
    coach: CoachOptions | None = None


class ChatResponse(AnswerResponse):
    conversation_id: str


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    rewritten_query: str | None
    citations: list
    confidence: str | None
    abstained: bool | None
    created_at: datetime


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_slug: str | None
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead] = Field(default_factory=list)


class WeekTopicRead(BaseModel):
    label: str
    covers: str
    where: str


class WeekConceptRead(BaseModel):
    term: str
    meaning: str


class WeekSymbolRead(BaseModel):
    symbol: str
    meaning: str


class WeekFormulaRead(BaseModel):
    name: str
    # LaTeX zonder dollartekens; de pagina zet ze eromheen.
    latex: str
    when: str
    symbols: list[WeekSymbolRead] = Field(default_factory=list)


class WeekSummaryRead(BaseModel):
    course_slug: str
    week: int
    thread: str
    topics: list[WeekTopicRead] = Field(default_factory=list)
    formulas: list[WeekFormulaRead] = Field(default_factory=list)
    concepts: list[WeekConceptRead] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    # Formules die zijn afgevallen, met de reden. Stil weglaten zou verbergen
    # dat het formuleblad niet compleet is.
    problems: list[str] = Field(default_factory=list)
    # Het materiaal is veranderd sinds deze samenvatting is gemaakt.
    stale: bool = False
    chunks_used: int = 0
    chunks_total: int = 0
    created_at: datetime


class WeekRead(BaseModel):
    week: int
    topics: list[str] = Field(default_factory=list)
    lectures: list[int] = Field(default_factory=list)
    chunk_count: int = 0
    has_summary: bool = False
    # Leesregels uit course.yml die nergens op uitkwamen.
    unresolved: list[str] = Field(default_factory=list)


class BuildSummaryRequest(BaseModel):
    course_slug: str
    week: int = Field(ge=1, le=60)


class DeckRead(BaseModel):
    section_path: str
    document_title: str
    page_start: int
    page_end: int
    chunk_count: int
    card_count: int
    # Hoeveel van die kaarten nu weer aan de beurt zijn.
    due_count: int = 0


class PracticeCardRead(BaseModel):
    """Wat je nodig hebt om de vraag te maken — en niets wat het antwoord verraadt.

    Het goede antwoord, het beoordelingsschema en de uitleg staan ook in
    `spec`, maar gaan pas mee in de reactie op je poging.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    course_slug: str
    section_path: str | None
    document_id: str
    page_start: int
    page_end: int
    kind: str
    setup: str
    question: str
    points: float | None = None
    origin: str | None = None
    position: int | None = None
    week: int | None = None
    options: list[str] = Field(default_factory=list)
    multi: bool = False
    # Een figuur of stuk code bij de vraag, uitgeschreven naar tekst.
    figure: str = ""
    exam_section: str | None = None
    # Hoeveel opgesomde items meetellen; staat ook op het tentamen in de vraag.
    max_items: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _unpack_spec(cls, value):
        if isinstance(value, dict):
            return value
        spec = getattr(value, "spec", None) or {}
        return {
            "id": value.id,
            "course_slug": value.course_slug,
            "section_path": value.section_path,
            "document_id": value.document_id,
            "page_start": value.page_start,
            "page_end": value.page_end,
            "kind": value.kind,
            "setup": value.setup or "",
            "question": value.question,
            "points": value.points,
            "origin": value.origin,
            "position": value.position,
            "week": value.week,
            "options": spec.get("options") or [],
            "multi": bool(spec.get("multi")),
            "figure": spec.get("figure") or "",
            "exam_section": spec.get("section"),
            "max_items": spec.get("max_items"),
        }


class GenerateCardsRequest(BaseModel):
    course_slug: str
    section_path: str
    count: int = Field(default=8, ge=1, le=20)
    # "code": een NumPy- of pandas-uitdrukking. "stats": een toets uitvoeren.
    # "exam": vragen in de vorm van het tentamen — meerkeuze en open.
    kind: Literal["code", "stats", "exam"] = "code"


class ExamSectionRead(BaseModel):
    number: int
    title: str
    question_count: int
    points: float
    answered: int
    answered_points: float
    last_score: float


class ExamSetRead(BaseModel):
    origin: str
    title: str
    question_count: int
    points: float
    answered: int
    answered_points: float
    last_score: float
    sections: list[ExamSectionRead]

    @classmethod
    def from_progress(cls, exam) -> "ExamSetRead":
        """Uit `practice.exams.ExamProgress`; de oefenroute en de agenda tonen
        dezelfde cijfers."""
        return cls(
            origin=exam.origin,
            title=exam.title,
            question_count=exam.question_count,
            points=exam.points,
            answered=exam.answered,
            answered_points=exam.answered_points,
            last_score=exam.last_score,
            sections=[ExamSectionRead(**asdict(section)) for section in exam.sections],
        )


class DueCountRead(BaseModel):
    total: int


class GenerateExamSectionRequest(BaseModel):
    course_slug: str
    section: int = Field(ge=1, le=20)
    # Leeg: een nieuw oefententamen. Anders een sectie toevoegen aan dit tentamen.
    origin: str | None = Field(default=None, pattern=r"^oefententamen-\d+$")


class GenerateExamSectionResponse(BaseModel):
    origin: str
    title: str
    section_number: int
    section_title: str
    created: int
    points: float
    planned_points: float
    # Plekken uit de opbouw die niet gevuld konden worden, als leesbare regel.
    missing: list[str] = Field(default_factory=list)
    rejected: list["RejectedCard"] = Field(default_factory=list)
    uncovered_topics: list[str] = Field(default_factory=list)
    # Gevuld als (een deel van) de sectie alleen op het proeftentamen steunt.
    source_note: str = ""


class RejectedCard(BaseModel):
    label: str
    reason: str


class GenerateCardsResponse(BaseModel):
    created: list[PracticeCardRead]
    rejected: list[RejectedCard]


class AttemptRequest(BaseModel):
    answer: str = Field(min_length=1)


class CriterionRead(BaseModel):
    criterion: str
    points: float
    awarded: float
    evidence: str = ""
    comment: str = ""
    withdrawn: bool = False


class AttemptResponse(BaseModel):
    correct: bool
    kind: str
    # Pas ná je poging: zo zie je wat het had moeten zijn.
    reference_answer: str
    # De uitgewerkte oplossing van een toetskaart; leeg bij een codekaart.
    explanation: str = ""
    expected_repr: str
    given_repr: str
    error: str | None = None
    section_path: str | None = None
    page_start: int
    page_end: int
    # Tentamenvragen: punten in plaats van alleen goed of fout.
    score: float | None = None
    max_score: float | None = None
    # Meerkeuze: wat je koos en wat goed was, als optienummers.
    options: list[str] = Field(default_factory=list)
    selected: list[int] = Field(default_factory=list)
    correct_options: list[int] = Field(default_factory=list)
    # Open vraag: het oordeel per criterium en wat er ontbrak.
    criteria: list[CriterionRead] = Field(default_factory=list)
    feedback: str = ""
    # Waar je dit nakijkt in je materiaal.
    material: str = ""


# --- agenda -------------------------------------------------------------------

AgendaItemKind = Literal["assignment", "quiz", "exam", "event"]
AgendaStatus = Literal[
    "locked", "open", "submitted", "late", "graded", "missing", "overdue", "done", "closed", "upcoming", "past"
]
AgendaBucket = Literal["overdue", "today", "tomorrow", "this_week", "next_week", "later", "undated", "done"]


class AgendaQuizRead(BaseModel):
    attempt: int | None = None
    score: float | None = None
    finished_at: datetime | None = None
    # Vanaf wanneer Canvas de goede antwoorden laat zien.
    answers_at: datetime | None = None


class AgendaYamlLink(BaseModel):
    """De regel in course.yml die bij dit Canvas-item hoort, op naam."""

    name: str
    week: int
    due_date: date
    # Dezelfde Amsterdamse kalenderdag als de Canvas-deadline.
    same_day: bool


class AgendaItemRead(BaseModel):
    id: str
    kind: AgendaItemKind
    course_id: int | None
    course_slug: str | None
    course_name: str
    title: str
    html_url: str | None = None
    description: str = ""
    due_at: datetime | None = None
    unlock_at: datetime | None = None
    lock_at: datetime | None = None
    # Een tentamen uit course.yml heeft een dag, geen tijd.
    due_on: date | None = None
    # due_at, of anders lock_at (een quiz heeft meestal alleen een sluittijd).
    deadline_at: datetime | None = None
    days_left: int | None = None
    points_possible: float | None = None
    submission_types: list[str] = Field(default_factory=list)
    status: AgendaStatus
    bucket: AgendaBucket
    # Waar de rij staat. `bucket` zegt wat hij betekent (afgerond telt niet
    # mee in de navigatiebalk); een afgevinkte rij blijft op zijn dag staan.
    place: AgendaBucket
    score: float | None = None
    grade: str | None = None
    submitted_at: datetime | None = None
    late: bool = False
    missing: bool = False
    marked_complete: bool = False
    done_at: datetime | None = None
    # Of het vinkje zin heeft: er moet een CanvasItem-rij achter zitten (een
    # tentamen uit course.yml heeft die niet) en de status mag niet vastliggen.
    # Staat hier zodat de frontend die regel niet hoeft te kopiëren.
    tickable: bool = False
    quiz: AgendaQuizRead | None = None
    yaml: AgendaYamlLink | None = None
    # Het open opgavenblad in het corpus, als dat er is: de coach-link.
    coach_document_id: str | None = None


class AgendaAnnouncementRead(BaseModel):
    id: int
    title: str
    posted_at: datetime | None
    body: str
    html_url: str | None
    unread: bool


class AgendaExamRead(BaseModel):
    name: str
    date: date | None
    days_left: int | None
    source: Literal["yaml", "canvas", "both"]
    canvas_item_id: str | None


class AgendaDiffRead(BaseModel):
    """Waar course.yml en Canvas uiteenlopen. Alleen ter melding: course.yml
    stuurt de spoilerfilter en wordt hier nooit aangepast."""

    kind: Literal[
        "due_date_differs",
        "yaml_only",
        "canvas_only",
        "exam_date_differs",
        "exam_missing_in_yaml",
        "canvas_id_missing",
        "assignment_sheet_missing",
    ]
    message: str
    item_id: str | None = None
    week: int | None = None
    file_id: int | None = None
    # Bij een ontbrekend opgavenblad zonder pdf: de beschrijving in Canvas kan
    # als tekst het corpus in (POST /agenda/items/{item_id}/sheet).
    can_fetch_text: bool = False


class AgendaCopilotRead(BaseModel):
    due_count: int
    exam_sets: list[ExamSetRead]
    weeks_without_summary: list[int]
    # Weken waarvan de stof veranderde sinds de weekkaart gemaakt is.
    stale_summaries: list[int] = Field(default_factory=list)


class AgendaCourseRead(BaseModel):
    canvas_id: int | None
    course_slug: str | None
    name: str
    course_code: str | None
    term: str | None
    hidden: bool
    fetched_at: datetime | None
    item_count: int
    exams: list[AgendaExamRead]
    # Leeg voor een Canvas-vak zonder corpus.
    copilot: AgendaCopilotRead | None
    announcements: list[AgendaAnnouncementRead]
    diffs: list[AgendaDiffRead]
    # Alleen voor een vak met een corpus; elders valt er niets te plaatsen.
    materials: list["MaterialRead"] = Field(default_factory=list)
    pages: list["PageRead"] = Field(default_factory=list)


class TaskRead(BaseModel):
    id: str
    title: str
    notes: str
    due_on: date | None
    course_slug: str | None
    link: str | None
    links: list["TaskLink"] = Field(default_factory=list)
    done_at: datetime | None
    created_at: datetime
    bucket: AgendaBucket
    # Waar de rij staat. `bucket` zegt wat hij betekent (afgerond telt niet
    # mee in de navigatiebalk); een afgevinkte rij blijft op zijn dag staan.
    place: AgendaBucket


def _clean_title(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("een taak heeft een titel nodig")
    return cleaned


def _safe_href(value: str | None) -> str | None:
    """Een link wordt een href in de pagina: een pad binnen de app of een
    https-adres. `javascript:` of `//ander-domein` hoort daar niet, en een pad
    zonder slash zou relatief aan /agenda gaan wijzen."""
    if value is None:
        return None
    href = value.strip()
    if (href.startswith("/") and not href.startswith("//")) or href.startswith("https://"):
        return href
    raise ValueError("een link begint met / (binnen de app) of met https://")


class TaskLink(BaseModel):
    """Een knop bij een taak: hoe hij heet en waar hij heen gaat."""

    label: str = Field(max_length=60)
    href: str = Field(max_length=512)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("een link heeft een naam nodig")
        return cleaned

    _href = field_validator("href")(_safe_href)


# Genoeg voor opgaven, uitwerking, hint en weekkaart; meer knoppen onder één
# taak lees je niet meer.
MAX_TASK_LINKS = 6


class TaskCreate(BaseModel):
    title: str = Field(max_length=200)
    notes: str = ""
    due_on: date | None = None
    course_slug: str | None = None
    link: str | None = None
    links: list[TaskLink] = Field(default_factory=list, max_length=MAX_TASK_LINKS)

    _title = field_validator("title")(_clean_title)
    _link = field_validator("link")(_safe_href)


class TaskUpdate(BaseModel):
    """Alleen wat er in het verzoek staat wordt gewijzigd; `due_on: null`
    wist de datum, een verzoek zonder due_on laat hem staan."""

    title: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    due_on: date | None = None
    course_slug: str | None = None
    link: str | None = None
    links: list[TaskLink] | None = Field(default=None, max_length=MAX_TASK_LINKS)
    done: bool | None = None

    _title = field_validator("title")(_clean_title)
    _link = field_validator("link")(_safe_href)


class AgendaCanvasState(BaseModel):
    configured: bool
    synced_at: datetime | None
    # Ouder dan canvas_stale_after_minutes, of nooit gesynchroniseerd.
    stale: bool


class AgendaRead(BaseModel):
    now: datetime
    canvas: AgendaCanvasState
    courses: list[AgendaCourseRead]
    items: list[AgendaItemRead]
    tasks: list[TaskRead]
    # Wat er aan de course.yml's mankeert, zoals in het sync-rapport.
    problems: list[str]


class CanvasSyncResponse(BaseModel):
    synced_at: datetime
    courses: int
    items: int
    announcements: int
    files_new: int
    lines: list[str]
    problems: list[str]


class CanvasCoursePatch(BaseModel):
    hidden: bool


class CanvasCourseRead(BaseModel):
    canvas_id: int
    name: str
    hidden: bool


class AgendaItemPatch(BaseModel):
    done: bool


# --- materiaal uit Canvas ------------------------------------------------------

MaterialState = Literal["new", "in_corpus", "downloaded", "ignored", "unsupported", "unplaced"]


class MaterialPlacementRead(BaseModel):
    doc_kind: str
    week: int | None
    relative_path: str


class MaterialRead(BaseModel):
    id: int
    canvas_course_id: int
    filename: str
    display_name: str
    size: int | None
    content_type: str | None
    folder: str | None
    module_name: str | None
    source: str
    updated_at: datetime | None
    state: MaterialState
    # Het voorstel; leeg als er niets zekers te zeggen valt. `reason` altijd.
    placement: MaterialPlacementRead | None
    reason: str
    document_id: str | None
    corpus_path: str | None


class MaterialFetchRequest(BaseModel):
    """Zonder velden: het voorstel. Met `doc_kind` (en `week`): de eigen keuze."""

    doc_kind: DocKindLiteral | None = None
    week: int | None = Field(default=None, ge=1, le=60)
    overwrite: bool = False


class MaterialFetchResponse(BaseModel):
    material: MaterialRead
    document: DocumentRead
    chunk_count: int


class MaterialIgnoreRequest(BaseModel):
    ignored: bool = True


class AssignmentTextRequest(BaseModel):
    overwrite: bool = False


class AssignmentTextResponse(BaseModel):
    document: DocumentRead
    chunk_count: int


PageState = Literal["new", "in_corpus", "downloaded", "ignored"]


class PageRead(BaseModel):
    id: str
    canvas_course_id: int
    title: str
    module_name: str | None
    updated_at: datetime | None
    state: PageState
    placement: MaterialPlacementRead | None
    reason: str
    document_id: str | None


class PageFetchRequest(BaseModel):
    overwrite: bool = False


class PageFetchResponse(BaseModel):
    page: PageRead
    document: DocumentRead
    chunk_count: int


# --- studeren ---------------------------------------------------------------


class StudyExamRead(BaseModel):
    name: str
    date: date
    days_left: int
    source: str


class SessionCardRead(BaseModel):
    """Eén kaart in de ronde, met waarom hij erin zit."""

    card: PracticeCardRead
    # zwak | herhalen | nieuw
    reason: str
    topic: str | None = None
    procedure: str | None = None
    minutes: float


class StudySessionRead(BaseModel):
    minutes: int
    estimated_minutes: float
    cards: list[SessionCardRead] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class StudyWeekRead(BaseModel):
    week: int
    lectures: list[int] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    material_chunks: int
    cards: int
    new: int
    learning: int
    mastered: int
    weak: int
    due: int
    topics_without_cards: list[str] = Field(default_factory=list)
    has_summary: bool
    summary_stale: bool
    last_practised: datetime | None = None
    examples: list["ExampleRead"] = Field(default_factory=list)


class StudyRead(BaseModel):
    course_slug: str
    now: datetime
    exam: StudyExamRead | None = None
    pace: "PaceRead | None" = None
    session: StudySessionRead
    weeks: list[StudyWeekRead] = Field(default_factory=list)
    # Over alle weken heen; de tellers boven aan de pagina.
    totals: dict[str, int] = Field(default_factory=dict)


class FillWeekRequest(BaseModel):
    course_slug: str
    # keuze | stats | code | exam | output
    kind: str = "keuze"
    count: int = Field(default=4, ge=1, le=20)


class FillWeekResponse(BaseModel):
    week: int
    created: int
    topics_done: list[str] = Field(default_factory=list)
    skipped: list[tuple[str, str]] = Field(default_factory=list)
    rejected: list[RejectedCard] = Field(default_factory=list)


class ResourceRead(BaseModel):
    name: str
    url: str
    kind: str
    license: str
    note: str


class MethodClaimRead(BaseModel):
    claim: str
    source: str
    title: str
    url: str
    strength: str


class TopicResourcesRead(BaseModel):
    week: int
    topic: str
    resources: list[ResourceRead] = Field(default_factory=list)


class LibraryRead(BaseModel):
    course_slug: str
    topics: list[TopicResourcesRead] = Field(default_factory=list)
    method: list[MethodClaimRead] = Field(default_factory=list)


class ExampleStepRead(BaseModel):
    label: str
    body: str


class ExampleRead(BaseModel):
    id: str
    week: int | None
    topic: str
    title: str
    situation: str
    steps: list[ExampleStepRead] = Field(default_factory=list)
    takeaway: str
    # De vraag die je jezelf stelt; wordt met opzet niet nagekeken.
    prompt: str
    # De figuur als svg, klaar om in de pagina te zetten. Leeg als er geen is.
    figure_svg: str = ""
    figure_caption: str = ""
    page_start: int
    page_end: int


class MakeExamplesRequest(BaseModel):
    course_slug: str
    count: int = Field(default=1, ge=1, le=3)
    figures: bool = True


class MakeExamplesResponse(BaseModel):
    week: int
    created: int
    topics_done: list[str] = Field(default_factory=list)
    skipped: list[tuple[str, str]] = Field(default_factory=list)
    rejected: list[RejectedCard] = Field(default_factory=list)
    # (titel, reden) — voorbeelden die het zonder figuur moeten doen.
    figure_problems: list[tuple[str, str]] = Field(default_factory=list)


class AttentionRead(BaseModel):
    """Drie getallen voor de navigatiebalk."""

    today: int
    overdue: int
    due_cards: int


class PaceRead(BaseModel):
    """Haal je het in de tijd die er nog is? Bewust optimistisch gerekend:
    alsof je alles goed hebt."""

    exam_name: str
    days_left: int
    cards: int
    reviews_needed: int
    reviews_possible: int
    minutes: int
    minutes_per_day_needed: int
    feasible: bool


# --- de tab Tentamen ------------------------------------------------------------


class ExamFactsRead(BaseModel):
    duration_minutes: int | None
    aids: list[str]
    notes: list[str]


class GroupStandingRead(BaseModel):
    number: int
    title: str
    points: float
    mc: int
    open: int
    mc_points: float
    open_points: list[float]
    answered: int
    answered_points: float
    scored: float
    # None: nog niet geoefend.
    share: float | None
    to_gain: float


class PrepSourceRead(BaseModel):
    label: str
    quote: str
    found: bool
    # Waarom een bron niet is teruggevonden; leeg als hij gevonden is.
    reason: str | None
    href: str | None


class PrepScenarioRead(BaseModel):
    card_id: str
    question_id: str
    topic: str
    points: float
    last_score: float | None


class PrepPracticeRead(BaseModel):
    """Waar je de scenario's van een patroon oefent: /oefenen?exam=…&section=…."""

    origin: str
    section: int


class PrepPatternRead(BaseModel):
    id: str
    title: str
    detail: str
    group: int | None
    seen: int | None
    of: int | None
    sources: list[PrepSourceRead]
    scenarios: list[PrepScenarioRead] = []
    practice: PrepPracticeRead | None = None


class PrepPredictionRead(BaseModel):
    id: str
    group: int | None
    points: float | None
    question: str
    answer: str
    why: str
    sources: list[PrepSourceRead]


class PrepTacticRead(BaseModel):
    id: str
    title: str
    detail: str
    sources: list[PrepSourceRead]


class PrepRuleRead(BaseModel):
    id: str
    group: int | None
    new: bool
    see: str
    do: str
    points: str
    trap: str
    sources: list[PrepSourceRead]


class PrepPlanStepRead(BaseModel):
    id: str
    title: str
    day: str
    detail: str
    minutes: int | None
    exam: str | None
    links: list[TaskLink]
    slides: list[TaskLink]


class ExamPrepRead(BaseModel):
    course_slug: str
    has_file: bool
    exam: StudyExamRead | None
    facts: ExamFactsRead | None
    total_points: float | None
    minutes_per_point: float | None
    groups: list[GroupStandingRead]
    exam_sets: list[ExamSetRead]
    patterns: list[PrepPatternRead]
    predictions: list[PrepPredictionRead]
    tactics: list[PrepTacticRead]
    rules: list[PrepRuleRead]
    plan: list[PrepPlanStepRead]
    problems: list[str]
