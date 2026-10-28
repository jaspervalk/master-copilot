from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.utcnow()


def _uuid() -> str:
    return str(uuid.uuid4())


class Course(Base):
    __tablename__ = "courses"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    period: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lecturer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # week (als string, JSON-sleutel) → ISO-datum van de harde deadline van de
    # beoordeelde opdracht in die week. Uit course.yml; leeg als er geen is.
    deadlines: Mapped[dict] = mapped_column(JSON, default=dict)
    # week (als string) → {lectures, topics, reading}. Koppelt een week aan de
    # hoofdstukken die erbij horen; een boek heeft zelf geen week.
    week_plans: Mapped[dict] = mapped_column(JSON, default=dict)
    # Het Canvas-id uit course.yml. De agenda koppelt daarmee de Canvas-
    # momentopname aan dit vak; de koppeling staat alleen hier, niet ook op
    # de Canvas-kant, zodat er één bron is.
    canvas_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # Dezelfde opdrachten als `deadlines`, mét naam en punten:
    # [{name, week, due_date, available_date, points}]. Voor de agenda; de
    # spoilerfilter blijft op `deadlines` draaien.
    assignments: Mapped[list] = mapped_column(JSON, default=list)
    # [{name, date}] — tentamens die niet als Canvas-opdracht bestaan (SSO).
    exams: Mapped[list] = mapped_column(JSON, default=list)
    # Uit `study:` in course.yml. `{"code": "none"}`: geen code op het tentamen;
    # `{"code": "read"}`: fragmenten lezen en de uitvoer voorspellen, geen
    # syntax schrijven. Stuurt de instructie van de weekkaart.
    study: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255))
    # Pad ten opzichte van corpus_dir, posix-vorm. Uniek: één rij per bestand.
    source_path: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    course_slug: Mapped[str] = mapped_column(String(64), index=True)
    doc_kind: Mapped[str] = mapped_column(String(16), index=True)
    week: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # Alleen gevuld voor doc_kind == "assignment": "open" of "submitted".
    assignment_status: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    ingestion_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.chunk_index",
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    chunk_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship("Document", back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    course_slug: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    # De zelfstandig gemaakte zoekvraag; None bij de eerste beurt of bij een gebruikersbeurt.
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    abstained: Mapped[bool | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="messages")


class QueryLog(Base):
    __tablename__ = "query_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    endpoint: Mapped[str] = mapped_column(String(16), index=True)
    question: Mapped[str] = mapped_column(Text)
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    retrieval_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    answer_style: Mapped[str | None] = mapped_column(String(16), nullable=True)
    top_k: Mapped[int] = mapped_column(Integer)
    retrieved_chunk_ids: Mapped[list] = mapped_column(JSON, default=list)
    retrieved_documents: Mapped[list] = mapped_column(JSON, default=list)
    retrieved_scores: Mapped[list] = mapped_column(JSON, default=list)
    embedding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    answer_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abstained: Mapped[bool | None] = mapped_column(nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confidence_inputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PracticeCard(Base):
    """Eén oefenvraag, afgeleid van één chunk.

    Kaarten blijven bestaan: genereren is een aparte handeling, oefenen is
    gratis. Dat is ook de voorwaarde voor herhaling-in-de-tijd later — zonder
    vaste kaart-identiteit valt er niets te plannen.
    """

    __tablename__ = "practice_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    course_slug: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    # Het bewijs waar de vraag op steunt; blijft staan als de chunk verdwijnt,
    # zodat een kaart niet stil zijn herkomst verliest bij een herindexering.
    chunk_id: Mapped[str] = mapped_column(String(36))
    section_path: Mapped[str | None] = mapped_column(String(512), index=True, nullable=True)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    # "code": een NumPy- of pandas-uitdrukking, nagekeken door uit te voeren.
    # "stats": een toets met de hand uitgerekend, nagekeken op waarde met een
    # afrondingsmarge. "mc": meerkeuze, nagekeken op de verzameling gekozen
    # letters. "open": een open tentamenvraag, nagekeken door een model tegen
    # een beoordelingsschema.
    kind: Mapped[str] = mapped_column(String(16), index=True)
    setup: Mapped[str] = mapped_column(Text, default="")
    question: Mapped[str] = mapped_column(Text)
    reference_answer: Mapped[str] = mapped_column(Text)
    # De uitgewerkte oplossing: hypotheses, formule, verdeling, conclusie. Bij
    # een toetskaart is dát het leermateriaal — het getal alleen leert niets.
    # Komt pas na je poging naar buiten.
    explanation: Mapped[str] = mapped_column(Text, default="")
    # Wat alleen bij één soort hoort. "mc": opties, goede letters, en eventueel
    # een uitdrukking die het goede antwoord narekent. "open": het
    # beoordelingsschema en hoeveel opgesomde items meetellen. Samen in één
    # kolom, zodat een nieuwe soort geen nieuwe kolommen vraagt.
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    # Hoeveel punten deze vraag op het tentamen waard is; leeg bij code en stats.
    points: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Waar de kaart vandaan komt als hij niet uit het materiaal is gemaakt: het
    # id van een (proef)tentamen, met de plek van de vraag daarin.
    origin: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # In welke week de stof wordt behandeld. Een tentamenvraag over week 6 hoort
    # niet in je herhaalronde van week 2.
    week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Weggegooid door de gebruiker: de kaart blijft staan zodat pogingen hun
    # verwijzing houden, maar hij komt niet meer in een ronde.
    disabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PracticeAttempt(Base):
    """Een poging op een kaart.

    Vastgelegd om drie redenen: je ziet wat je fout deed, een latere fase kan
    er herhaling op plannen, en het is een signaal over de kaart zelf — een
    kaart die altijd fout gaat is waarschijnlijk zelf fout.
    """

    __tablename__ = "practice_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    card_id: Mapped[str] = mapped_column(ForeignKey("practice_cards.id", ondelete="CASCADE"), index=True)
    given_answer: Mapped[str] = mapped_column(Text)
    correct: Mapped[bool] = mapped_column()
    # De verwachte en gegeven waarde, of de foutmelding.
    detail: Mapped[str] = mapped_column(Text, default="")
    # Bij tentamenvragen telt het aantal punten, niet alleen goed of fout: een
    # open vraag van 10 punten met 6 punten is iets anders dan een nul.
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Per criterium van het schema: toegekend, maximum, en het citaat uit je
    # antwoord waarop het oordeel steunt.
    feedback: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class WeekSummary(Base):
    """De samenvatting van één week, zoals hij is gemaakt.

    Bewaard en niet elke keer opnieuw gemaakt: het kost een modelaanroep over
    de hele week, en je leest hem vaker dan het materiaal verandert. De
    vingerafdruk over de gebruikte fragmenten zegt of dat laatste toch gebeurd
    is — dan staat er "verouderd" bij in plaats van dat je het niet merkt.
    """

    __tablename__ = "week_summaries"

    course_slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    week: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    # Hoeveel fragmenten er meegingen en hoeveel de week er heeft; bij een
    # lange week past niet alles in één prompt en dat hoor je te zien.
    chunks_used: Mapped[int] = mapped_column(Integer, default=0)
    chunks_total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Example(Base):
    """Een uitgewerkt voorbeeld bij één onderwerp van één week.

    Waarom dit geen oefenkaart is: bij nieuwe stof levert een uitgewerkte
    oplossing bestuderen méér op dan zelf puzzelen (Barbieri e.a. 2023 vinden
    g = 0.48 voor wiskunde). Maar dat draait om zodra je het kunt — dezelfde
    uitleg remt dan juist (Kalyuga e.a. 2003). Vandaar apart van de kaarten,
    en vandaar dat de pagina hem wegvouwt zodra je het onderwerp beheerst.

    De vraag onderaan (`prompt`) wordt niet nagekeken. Dat hoeft ook niet: het
    formuleren van het antwoord is zelf het werkzame bestanddeel (Bisra e.a.
    2018, g = 0.55).
    """

    __tablename__ = "examples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    course_slug: Mapped[str] = mapped_column(String(64), index=True)
    week: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    topic: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(255))
    # Het verhaal waar het voorbeeld over gaat.
    situation: Mapped[str] = mapped_column(Text)
    # [{label, body}] — de stappen van de uitwerking, met $formules$.
    steps: Mapped[list] = mapped_column(JSON, default=list)
    # De regel die je hieruit meeneemt, in één zin.
    takeaway: Mapped[str] = mapped_column(Text, default="")
    # De vraag die je jezelf stelt na het lezen; niet nagekeken, met opzet.
    prompt: Mapped[str] = mapped_column(Text, default="")
    # Waar het op steunt, net als bij een kaart.
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    chunk_id: Mapped[str] = mapped_column(String(36))
    page_start: Mapped[int] = mapped_column(Integer, default=0)
    page_end: Mapped[int] = mapped_column(Integer, default=0)
    source_quote: Mapped[str] = mapped_column(Text, default="")
    # De figuur: de code die hem tekent en het resultaat als SVG. De code wordt
    # uitgevoerd voordat het voorbeeld wordt bewaard; wat niet tekent, gaat weg.
    figure_code: Mapped[str] = mapped_column(Text, default="")
    figure_svg: Mapped[str] = mapped_column(Text, default="")
    figure_caption: Mapped[str] = mapped_column(String(512), default="")
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IndexCollection(Base):
    """Stempelt de actieve collectie met provider, model en dimensie.

    Voorkomt dat vectoren van verschillende embeddingproviders in één collectie
    belanden — dan zijn afstanden betekenisloos.
    """

    __tablename__ = "index_collections"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    dimensions: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# --- Canvas-momentopname en agenda -------------------------------------------
#
# Wat hieronder staat is een spiegel van Canvas, geschreven door de sync, plus
# een paar kolommen die van de gebruiker zijn (`hidden`, `done_at`,
# `ignored_at`, …) en die de sync dus nooit aanraakt. Tijden zijn naïef UTC,
# zoals overal in dit bestand.


class CanvasCourse(Base):
    """Een vak zoals Canvas het kent. Welk corpusvak erbij hoort staat op
    `Course.canvas_id`, niet hier: één bron voor de koppeling."""

    __tablename__ = "canvas_courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    course_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    term: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Een oud vak dat in Canvas nog "actief" heet, uit beeld gezet.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CanvasItem(Base):
    """Alles in Canvas met een datum: opdracht, quiz, tentamen, kalenderitem."""

    __tablename__ = "canvas_items"

    # "assignment:714239", "quiz:135546", "event:12": het soort zit in de
    # sleutel omdat Canvas per soort een eigen id-reeks heeft.
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    canvas_course_id: Mapped[int] = mapped_column(Integer, index=True)
    # assignment | quiz | exam | event
    kind: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    html_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unlock_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Quiz: vanaf wanneer de goede antwoorden te zien zijn.
    answers_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    points_possible: Mapped[float | None] = mapped_column(Float, nullable=True)
    submission_types: Mapped[list] = mapped_column(JSON, default=list)
    # De eigen inzending als één JSON: {workflow_state, submitted_at, score,
    # grade, late, missing, …}. De status wordt hieruit afgeleid, dus een
    # extra veld kost geen kolom.
    submission: Mapped[dict] = mapped_column(JSON, default=dict)
    # Het vinkje dat je in Canvas zelf zet (planner_override).
    marked_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    # Het vinkje dat je hier zet. Nodig omdat het token niets in Canvas kan
    # afvinken, en een papieren tentamen anders nooit "klaar" wordt.
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # En hier zet je het weer uit. Om dezelfde reden een eigen kolom: het token
    # kan in Canvas ook niets uitvinken, dus zonder dit is een item dat je daar
    # afvinkte voorgoed uit de lijst. Vervalt zodra Canvas opnieuw afvinkt.
    unmarked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CanvasAnnouncement(Base):
    __tablename__ = "canvas_announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canvas_course_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(255))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # HTML gestript; de opmaak doet er niet toe, de links wel (die zijn al
    # geoogst).
    body: Mapped[str] = mapped_column(Text, default="")
    html_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    read_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CanvasFile(Base):
    """Een bestand dat Canvas aanbiedt, en waar het gevonden is.

    Het voorstel waar het in het corpus hoort staat hier bewust níet: dat
    wordt bij het lezen berekend, want het hangt af van course.yml en dat
    verandert."""

    __tablename__ = "canvas_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canvas_course_id: Mapped[int] = mapped_column(Integer, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # De Canvas-map zonder "course files/": "statistics/Slides 2026/Lecture 4".
    folder: Mapped[str | None] = mapped_column(String(512), nullable=True)
    module_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "module:Week 3" | "page:…" | "assignment:…" | "announcement:…" |
    # "syllabus" | "front_page" — de eerste plek waar de link stond.
    source: Mapped[str] = mapped_column(String(255), default="")
    # Gezet als het bestand bij een opdracht hoorde: dan is het opgavenblad.
    assignment_item_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Van de gebruiker.
    ignored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    corpus_path: Mapped[str | None] = mapped_column(String(512), nullable=True)


class CanvasPage(Base):
    """Een pagina uit een module: de afleiding bij een college, lab-instructies,
    het rooster met huiswerkopgaven. Alleen wát er is; de tekst wordt bij
    ophalen vers gelezen, want een docent past een pagina nog aan."""

    __tablename__ = "canvas_pages"

    # "<vak-id>:<page_url>": een page_url is alleen binnen een vak uniek.
    id: Mapped[str] = mapped_column(String(300), primary_key=True)
    canvas_course_id: Mapped[int] = mapped_column(Integer, index=True)
    page_url: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    module_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Van de gebruiker.
    ignored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Task(Base):
    """Een eigen taak naast de Canvas-items. Een datum, geen tijd: 'sectie 3
    van het proeftentamen maken' hoort bij een dag."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    course_slug: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Een pad binnen de app ("/oefenen?course=sso&review=1"), zodat een taak
    # naar de handeling wijst.
    link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Knoppen naar wat je voor de taak nodig hebt, elk met een naam:
    # [{"label": "Opgaven college 8", "href": "https://…"}]. Een studietaak
    # wijst naar meer dan één plek, en een titel als enige link zag eruit als
    # gewone tekst.
    links: Mapped[list] = mapped_column(JSON, default=list)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Verwijderen is één klik zonder bevestiging; de rij blijft dus staan zodat
    # "ongedaan maken" ook na een herlaadbeurt werkt, en het id hetzelfde
    # blijft. Eén gebruiker, kleine tabel: opruimen is niet nodig.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
