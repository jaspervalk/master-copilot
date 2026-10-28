# Huiswerkcoach — Design (Fase 2)

Datum: 2026-09-02. Bouwt op fase 1 (corpus, retrieval, antwoord) en fase 4
(eval-harness). Vervangt de ene regel over fase 2 in het fase-1-ontwerp.

## 1. Wat het is

Een modus waarin het systeem je helpt met een opdracht zonder hem voor je te
maken. Twee beleidsregels, gekozen op de soort opdracht, plus een spoilerfilter
die altijd aanstaat.

Wat de studiewijzers van FDS en SSO laten zien, en wat het ontwerp bepaalt:

- Beide vakken hebben **beoordeelde groepsopdrachten** met strikte deadlines en
  een fraudereglement (FDS: twee, SSO: drie), én **oefenmateriaal dat niet
  wordt ingeleverd** (SSO: huiswerkopgaven uit Triola, "representative of the
  exam"; FDS: lab-notebooks en formatieve quizzen).
- Bij groepswerk levert een teamgenoot in. Een status die alleen van een bestand
  in `submissions/` afhangt blijft dan ten onrechte op `open` staan. De harde
  deadline is het betrouwbare signaal.

## 2. Beslissingen

### 2.1 Twee soorten opdrachten, onderscheiden via het pad

Nieuwe map en `doc_kind`:

| map | `doc_kind` | betekenis | beleid |
|---|---|---|---|
| `assignments/week-NN/` | `assignment` | beoordeeld, wordt ingeleverd | streng: alleen hints |
| `exercises/week-NN/` | `exercise` | oefenmateriaal, niet ingeleverd | hints eerst; uitwerking op verzoek |

Het pad blijft de enige bron van metadata; `doc_kind` blijft een gesloten
verzameling (`DOC_KINDS` in `path_metadata.py`, `DocKindLiteral` in
`schemas.py`, `DOC_KINDS` in `types.ts` — de assert in `schemas.py` houdt ze
gelijk). `exercise` chunkt zoals `assignment`: op opgave-eenheden.

### 2.2 Status: open, submitted, closed

`assignment_status` krijgt een derde waarde. Per beoordeelde opdracht (vak,
week):

```
closed     als course.yml een deadline voor die week noemt en die is verstreken
submitted  anders, als er een bestand staat in submissions/week-NN/
open       anders
```

`course.yml` krijgt een optionele lijst; elke regel is één beoordeelde
opdracht, gekoppeld op week:

```yaml
name: Fundamentals of DS
assignments:
  - week: 4
    deadline: 2026-09-28
  - week: 6
    deadline: 2026-10-12
```

"Verstreken" is: de datum ligt vóór vandaag (lokale datum; op de dag zelf is
de opdracht nog open). Een ongeldige datum of een week zonder opdracht geeft
een waarschuwing bij `sync` en wordt genegeerd — nooit een stille default.
Herberekend bij elke `sync`, upload en verwijdering, zoals nu. `exercise`-
documenten hebben geen status (`None`), net als boeken.

### 2.3 Spoilerfilter: altijd aan, niet alleen in coachmodus

Retrieval sluit chunks uit met `doc_kind ∈ {solution, submission}` uit een week
waarin voor dat vak een **beoordeelde** opdracht `open` staat. Uitwerkingen van
oefenmateriaal worden nooit verborgen: nakijken hoort bij oefenen.

Dit geldt voor elke vraag, met of zonder coachmodus. Het verbergen van een
uitwerking mag niet van een schakelaar afhangen die je vergeet.

Implementatie: de server berekent per vak de verzameling open weken
(`open_assignment_weeks(course_slug)`) en geeft die als uitsluiting mee aan
beide retrievaltakken — Qdrant als `must_not`-conditie, BM25 in
`HybridIndex._matches`. Dat het in beide takken moet, is precies de gotcha uit
de werknotities: de sparse tak kent zijn eigen filters.

Zonder vakfilter ("Alle vakken") geldt de uitsluiting per vak van de chunk.

### 2.4 Coachmodus: expliciet, met opdrachtkeuze

Geen automatische herkenning. De gebruiker zet de coach aan en kiest een
document uit de open opdrachten en het oefenmateriaal van het gekozen vak.

`ChatRequest` krijgt:

```python
class CoachOptions(BaseModel):
    document_id: str          # een assignment (status open) of een exercise
    reveal: bool = False      # alleen zinvol bij exercise

coach: CoachOptions | None = None
```

De server:

1. laadt het document; is het geen `assignment`/`exercise` van het gefilterde
   vak, dan 400 met een leesbare melding; is het een gesloten of ingeleverde
   opdracht, dan ook 400 — coachen op een dichte opdracht is zinloos en
   verwarrend;
2. **pint de chunks van de opdracht** vooraan in het bewijs (vóór de
   opgehaalde chunks, zonder ze mee te tellen in `top_k`), zodat de coach de
   echte opgavetekst ziet. Een opgavenblad is kort; alle chunks gaan mee, met
   een plafond van 12;
3. kiest het beleid op `doc_kind` en `reveal`, en voegt dat als extra blok toe
   aan `build_instructions`.

`AnswerResponse` krijgt `coach: CoachEcho | None` met `document_id`,
`document_title`, `policy: "hints" | "reveal"`, zodat de UI de beurt kan
labelen en de log het vastlegt.

### 2.5 Het beleid in de prompt

**hints** (assignment altijd; exercise zonder `reveal`):

> Je begeleidt een student bij een opdracht die beoordeeld wordt. Geef nooit
> het eindantwoord, geen uitkomst, geen volledige code of afleiding. Geef wél:
> de eerstvolgende stap, het begrip dat erachter zit, en waar dat in het
> materiaal staat. Vraag wat de student al heeft geprobeerd als dat niet
> duidelijk is. Gaat de vraag niet over de opdracht, antwoord dan gewoon.

Voor `exercise` in dezelfde toon, met één zin erbij: *"De student kan om de
volledige uitwerking vragen; verwijs daar niet zelf naar."*

**reveal** (alleen exercise met `reveal: true`):

> Geef de volledige uitwerking, stap voor stap, met bij elke stap de
> vindplaats in het materiaal. Sluit af met wat de student moet onthouden
> voor het tentamen.

De opgavetekst zelf staat in het bewijs met de kop `Opdracht` in plaats van
`[n]`, zodat het model hem niet als bron citeert.

### 2.6 UI

In de composer, naast antwoordstijl en zoekmodus: een schakelaar **Coach**.
Aan → een keuzelijst met de open opdrachten en het oefenmateriaal van het
gekozen vak, opgehaald met de bestaande
`GET /api/documents?course_slug=…&doc_kind=assignment&doc_kind=exercise`
(gesloten en ingeleverde opdrachten weggefilterd in de UI). Zonder gekozen
vak is de schakelaar uit en uitgeschakeld.

Bij een `exercise` verschijnt onder het antwoord een knop **Laat de uitwerking
zien**, die dezelfde vraag opnieuw stelt met `reveal: true`. Beurten in
coachmodus krijgen een label met de opdrachttitel en het beleid.

### 2.7 Eval

`eval/cases.yml` krijgt naast `must_mention` ook `must_not_mention` en een
optioneel `coach: {document: <source_path>, reveal: bool}`. De runner zoekt
het document op `source_path` (stabiel, zoals de andere verwachtingen) en
geeft `coach` door aan de antwoordfunctie. Zo is lekkage meetbaar: een case
met het eindantwoord in `must_not_mention` hoort met `--answers` te slagen.
Alleen met `--answers`; retrieval-only negeert coach-cases niet, maar meet er
alleen de treffers van.

## 3. Onderdelen

```
apps/api/app/services/path_metadata.py   exercises/ → exercise
apps/api/app/schemas.py                  DocKindLiteral, CoachOptions, CoachEcho, ChatRequest, AnswerResponse
apps/api/app/services/chunking/__init__.py  exercise → chunk_assignment
apps/api/app/services/corpus_sync.py     deadlines uit course.yml; status open/submitted/closed
apps/api/app/services/spoilers.py        open_assignment_weeks(db, course_slug) -> set[int]
apps/api/app/services/qdrant_index.py    must_not op (doc_kind, week)-paren
apps/api/app/services/hybrid_index.py    _matches kent de uitsluiting
apps/api/app/services/retrieval.py       haalt de uitsluiting op en geeft hem aan beide takken
apps/api/app/services/coach.py           laden + valideren van de opdracht, gepinde chunks, beleid, prompttekst
apps/api/app/services/answering.py       build_instructions(style, coach_policy); compose met gepinde chunks
apps/api/app/services/answer_stream.py   idem voor de streamende route
apps/api/app/api/routes/chat.py, stream.py   CoachOptions doorgeven
apps/api/app/eval/cases.py, answers.py, runner.py   must_not_mention, coach
apps/web/lib/types.ts, api.ts            exercise, CoachOptions, coach-echo
apps/web/components/chat/composer.tsx    schakelaar + keuzelijst
apps/web/components/chat/chat-workspace.tsx  coach-state, reveal-herhaling
apps/web/components/chat/thread.tsx      label + knop
apps/web/components/corpus/upload-modal.tsx  exercises als soort
corpus/README.md, README.md
```

## 4. Fouten

- Coach op een document dat geen opdracht of oefening is, of niet van het
  gefilterde vak: 400, melding noemt het document.
- Coach op een gesloten of ingeleverde opdracht: 400, melding noemt de status.
- `course.yml` met een onleesbare deadline: waarschuwing in de sync-uitvoer,
  regel genegeerd, status als zonder deadline.
- De spoilerfilter faalt nooit stil: kan de verzameling open weken niet worden
  bepaald (databasefout), dan faalt de vraag met 500 in plaats van zonder
  filter door te gaan.

## 5. Testen

- `path_metadata`: `exercises/week-03/x.pdf` → `exercise`; `exercises/x.pdf`
  krijgt de week uit de bestandsnaam zoals nu, anders `None` — een `exercise`
  zonder week is toegestaan.
- `corpus_sync`: status `closed` bij verstreken deadline, ook mét inzending;
  `submitted` zonder deadline; `open` bij toekomstige deadline; ongeldige
  datum → waarschuwing.
- `spoilers`: open weken per vak; `exercise`-weken tellen niet mee.
- Beide retrievaltakken: een `solution` uit een open week komt niet terug, uit
  een gesloten week wél, en een `solution` van een `exercise`-week altijd.
- `coach`: validatie (soort, vak, status), plafond op gepinde chunks, beleid
  per soort en `reveal`, de opgavetekst met kop `Opdracht`.
- `answering`: gepinde chunks staan vóór de opgehaalde en tellen niet in
  `top_k`; `build_instructions` bevat het beleidsblok.
- API: `POST /api/chat` met `coach` geeft `coach`-echo terug; 400-gevallen.
- Eval: `must_not_mention` faalt bij lekkage; `coach` in een case bereikt de
  antwoordfunctie.
- `tsc --noEmit` schoon.

Alles op fixtures: er staan nog geen echte opdrachten in het corpus.

## 6. Wat dit niet doet

Geen notebook-ingest (de coach ziet de opgave, niet jouw uitwerking). Geen
automatische herkenning van opdrachtvragen. Geen week→hoofdstuk-koppeling uit
de studiewijzer — dat is de grootste retrievalwinst die nog open ligt en krijgt
een eigen ontwerp. Geen uitvoeren van R- of Python-code.

## 7. Definitie van klaar

- Een `solution` uit een open beoordeelde week komt in geen enkele vraag terug;
  na de deadline (of inzending) wel.
- Coachmodus op een `assignment` geeft hints met vindplaats en geen
  eindantwoord; op een `exercise` idem, en met *Laat de uitwerking zien* de
  volledige uitwerking.
- Een coach-case met `must_not_mention` slaagt met `eval --answers`.
- `pytest` groen, `tsc --noEmit` schoon, documentatie bijgewerkt.
