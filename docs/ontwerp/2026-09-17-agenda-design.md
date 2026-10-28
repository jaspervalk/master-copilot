# Agenda — Design

Datum: 2026-09-17. Bouwt op fase 1 (corpus), 2 (coach) en 3 (oefenen, weken,
tentamentraining). Eerste koppeling met iets buiten de eigen bestanden: de
Canvas-API.

## 1. Waarom

Deadlines staan nu met de hand in `course.yml`, en verder nergens. Ze voeden
de spoilerfilter en de opdrachtstatus, maar niets houdt ze bij: een quiz die
vrijdag sluit, een deliverable van het Data Systems Project, het tentamen op
21 oktober — dat staat allemaal in Canvas, verspreid over drie vakken en vijf
tabbladen. Wat ontbreekt is één pagina die zegt wat er wanneer af moet, en die
vanaf elk item doorlinkt naar wat de copilot ervoor heeft: de coach op het
opgavenblad, de oefententamens, de weekkaart, de herhaalronde.

Canvas kan dat voeden. Met het (student-)token is te lezen: opdrachten met
deadline en eigen inzending, quizzen met open- en sluittijd en eigen score,
aankondigingen, kalenderitems, en het vinkje dat je in Canvas zelf zet. Ook
het lesmateriaal is te vinden — bij FDS in de modules, bij SSO als links in
pagina's en opdrachten — en dat is de tweede reden voor deze koppeling: de
oefententamens zijn zo goed als de stof in het corpus, en die stof komt week
na week op Canvas terecht.

Keuzes die vastliggen (17 september):

1. **Alle actieve Canvas-vakken.** FDS, SSO én DSP. Een vak zonder corpus
   krijgt deadlines, geen doorlinks.
2. **Eigen taken** met een vinkje, lokaal bewaard, naast de Canvas-items.
3. **`course.yml` wint.** Canvas overschrijft nooit een deadline; de pagina
   toont waar ze uiteenlopen. De spoilerfilter verandert dus nooit stil.
4. **Nieuw materiaal** wordt gesignaleerd met een voorgestelde plek in het
   corpus en op verzoek opgehaald. Raden mag niet: wat niet zeker is, wordt
   gemeld, niet geplaatst.

## 2. Wat Canvas geeft

Geverifieerd op 17 september 2026, alleen lezend.

| Aanroep | Levert | Beperking |
|---|---|---|
| `courses?enrollment_state=active&include[]=term` | 59831 FDS, 59863 SSO, 59837 DSP, plus twee oude (6056 MSc IS, 20678) | — |
| `courses/{id}/assignments?include[]=submission` | naam, beschrijving (HTML), `due_at`, `unlock_at`, `lock_at`, punten, `submission_types` (`on_paper` = tentamen), eigen inzending met `workflow_state`, `submitted_at`, `score`, `grade`, `late`, `missing` | — |
| `courses/{id}/quizzes` (+ `…/{qid}/submissions`) | `unlock_at`, `lock_at`, `show_correct_answers_at`, punten; eigen score (Quiz 1: 13,5/15) | vragen: 403 |
| `courses/{id}/discussion_topics?only_announcements=true` | titel, `posted_at`, `read_state`, tekst (HTML) | — |
| `planner/items?start_date&end_date` | één lijst over alle vakken: opdrachten, quizzen, kalenderitems, met `planner_override.marked_complete` | discussies en aankondigingen zitten erbij (overslaan) |
| `courses/{id}/modules?include[]=items` | modules ("Week 3") met `File`- en `Page`-items | SSO heeft geen bestanden in modules |
| `files/{id}` | naam, grootte, type, `folder_id`, download-URL | `courses/{id}/files` en `folders/{id}/files`: 403 |
| `courses/{id}/folders` | mapnamen (`statistics/Slides 2026/Lecture 4`) | inhoud niet |
| `courses/{id}/pages/{url}`, `…?include[]=syllabus_body`, `front_page` | tekst met `/files/<id>`-links | paginalijst: 404 |
| `courses/{id}/assignment_groups` | weging (SSO: opdrachten 50, tentamen 50) | optioneel |

Alle tijden zijn UTC met `Z`; de vak-tijdzone is Europe/Amsterdam. Een
deadline "23:59" staat er als `21:59:00Z` (zomertijd) of `22:59:00Z`.

## 3. Veiligheid

- Het token staat in `.env` (gitignored) en komt nergens anders: niet in een
  log, niet in een foutmelding, niet in een API-antwoord. De frontend krijgt
  `configured: true|false`.
- De client kent alleen `GET`. Er is geen parameter voor een andere methode;
  naar Canvas schrijven kan dus niet, ook niet per ongeluk.
- Download-URL's van Canvas dragen een `verifier`-geheim en verlopen. Ze
  worden nooit opgeslagen; bij ophalen wordt `files/{id}` opnieuw gelezen.
- Tests kunnen niet naar Canvas: een `autouse`-fixture in `conftest.py` zet
  `canvas_base_url` en `canvas_access_token` op `None`. De echte `.env` heeft
  een echt token, en `Settings` leest `.env`.

## 4. Backend

Nieuw pakket `app/services/canvas/`.

### 4.1 `client.py`

```python
@dataclass(frozen=True)
class CanvasClient:
    base_url: str
    token: str
    opener: Callable = _default_opener   # urlopen met certifi-context; tests geven een stub
    timeout: int = 30

    def get(self, path, params=None, *, paginate=True) -> Any
    def get_optional(self, path, params=None, *, tolerate=(403, 404)) -> Any | None
    def download(self, url, *, max_bytes) -> bytes

def client_from_settings() -> CanvasClient | None   # None zonder URL of token
def strip_html(text) -> str
def parse_timestamp(value) -> datetime | None        # "…Z" → naïef UTC
def file_ids_in_html(html) -> list[int]              # r"/files/(\d+)", ontdubbeld, volgorde behouden
```

Stdlib `urllib` met een injecteerbare `opener`, zoals `app/eval/search.py`.
`per_page=100`, `urlencode(doseq=True)` voor `include[]`, `Link: rel="next"`
gevolgd voor lijstantwoorden. `HTTPError` → `CanvasError(status, path)`;
`URLError` → `CanvasError(None, path, hint)`. De boodschap noemt status en
pad, nooit een header. `CanvasNotConfigured(CanvasError)` voor de lege
configuratie. In `api/errors.py`: `CanvasNotConfigured → 400`,
`CanvasError → 502`. De SSL-context volgt `canvas.py` (certifi, anders
`/etc/ssl/cert.pem`): de python.org-build op macOS heeft geen CA-bundel.

### 4.2 Modellen

Alle tijdstempels naïef UTC, zoals `utcnow()` overal. Nieuwe tabellen via
`create_all`; nieuwe kolommen via `db.py: additive_columns`.

```
Course              + canvas_id INTEGER, assignments JSON, exams JSON
CanvasCourse        id (Canvas-id) PK, name, course_code, term, hidden (van de gebruiker), fetched_at
CanvasItem          id "assignment:714239" | "quiz:135546" | "event:…" PK, canvas_course_id,
                    kind assignment|quiz|exam|event, title, description (gestript, ≤ 4000),
                    html_url, due_at, unlock_at, lock_at, answers_at, points_possible,
                    submission_types JSON, submission JSON, marked_complete,
                    done_at (van de gebruiker), fetched_at
CanvasAnnouncement  id PK, canvas_course_id, title, posted_at, body (gestript), html_url,
                    read_state, fetched_at
CanvasFile          id PK, canvas_course_id, filename, display_name, size, content_type,
                    folder, module_name, source ("module:Week 3" | "page:…" | "assignment:…" |
                    "announcement:…" | "syllabus" | "front_page"), assignment_item_id,
                    updated_at, fetched_at, ignored_at, document_id, corpus_path (van de gebruiker)
Task                id uuid PK, title, notes, due_on DATE, course_slug, link, done_at, created_at
```

`submission` is één JSON (`workflow_state, submitted_at, score, grade, late,
missing, excused, attempt, finished_at`): de status wordt afgeleid, en een
extra veld kost dan geen DDL. Het plaatsingsvoorstel voor een bestand wordt
níet opgeslagen maar bij het lezen berekend: zodra `course.yml` een week
`lectures: [5, 6]` krijgt, is `lecture5.pdf` ineens plaatsbaar, en een
bewaard voorstel zou dat missen. `done_at` op een item is nodig omdat het
token niets in Canvas kan afvinken: het papieren tentamen en een item met
`submission_types: ["none"]` worden anders nooit "klaar".

Geen tabel voor synchronisatieruns: `synced_at` is `max(CanvasCourse.
fetched_at)`, en een fout komt terug uit `POST /sync` en staat als balk op de
pagina.

### 4.3 `course.yml`

Twee nieuwe sleutels; `_KNOWN_TOP_LEVEL_KEYS` uitgebreid.

```yaml
canvas_id: 59831
exams:
  - name: Tentamen
    date: 2026-10-21
  - name: Herkansing
    date: 2026-12-14
```

`_parse_assignments` vult `deadlines` (week → datum) precies zoals nu — de
spoilerlogica raakt dit niet — en bewaart daarnaast de hele lijst
(`name, week, due_date, available_date, points`) in `Course.assignments`,
zodat de agenda per naam kan vergelijken met Canvas en het opgavenblad kan
vinden. `exams` zonder naam of geldige datum is een probleem in het rapport;
`canvas_id` dat geen getal is ook. Beide `course.yml`'s krijgen `canvas_id`
(FDS 59831, SSO 59863) en het tentamen van 21 oktober.

### 4.4 `sync.py`

```python
def sync_canvas(db, client, *, now=None, dry_run=False) -> CanvasSyncReport
def refresh_course_rows(db, corpus_root) -> list[tuple[str, str]]
```

1. `refresh_course_rows`: voor elke `corpus/*/course.yml`
   `upsert_course_from_yaml` en `recompute_assignment_status`. Zo werkt een
   nieuwe `canvas_id` zonder `python -m app.cli sync` (dat de Qdrant-lock
   nodig heeft), en klapt een verstreken deadline ook om naar `closed` als er
   die dag niets is gesynchroniseerd — precies wat de werknotities al
   beloven ("een deadline die vannacht verstreek telt vanochtend").
2. Vakken ophalen; per niet-verborgen vak, in het geheugen: opdrachten met
   inzending, quizzen (+ eigen inzending via `get_optional`), aankondigingen,
   modules met items, mappen, syllabus en voorpagina (alle drie
   `get_optional`), en de tekst van `Page`-items.
3. Eén `planner/items` (venster `now − 90 d … now + 200 d`): kalenderitems
   worden `event`; `marked_complete` wordt overgenomen op het bijbehorende
   item.
4. Bestanden oogsten: `File`-module-items, plus `file_ids_in_html` over
   pagina's, opdrachtbeschrijvingen, aankondigingen, syllabus en voorpagina.
   `files/{id}` alleen voor ids zonder rij (de eerste keer ± 70 aanroepen,
   daarna een handvol); `folder_id` gekoppeld aan de mapnaam.
5. Pas dan schrijven, in één transactie: upsert van wat Canvas beheert (nooit
   `hidden`, `done_at`, `ignored_at`, `document_id`, `corpus_path`), verwijderen
   van items en bestanden van een vak die niet meer terugkwamen, `fetched_at`
   zetten. Een harde fout (401, netwerk) laat de vorige momentopname staan;
   een afgeschermd hulpendpoint komt als `skipped` in het rapport.

Soort: `exam` bij `on_paper` in `submission_types` of `exam|tentamen|final`
in de naam (vangt "Retake exam" met types `["none"]`), anders `assignment`.

CLI: `python -m app.cli canvas-sync [--dry-run]`, naar het patroon van
`_run_sync` (`init_db`, `SessionLocal`, `as_lines()`, exitcode 1 bij
`course.yml`-problemen; geen Qdrant nodig).

### 4.5 `agenda.py` — het leesmodel

```python
def build_agenda(db, *, now=None) -> AgendaRead
def derive_status(item, now) -> str
def bucket_for(deadline, *, now, finished) -> str
def local_date(dt) -> date            # naïef UTC → Amsterdamse kalenderdag
def match_assignments(yaml, items)    # op genormaliseerde naam
def diff_course(course, canvas, items, docs_by_week, files) -> list[AgendaDiffRead]
```

**Status**, in volgorde van voorrang. Opdracht en tentamen: `graded` →
`late`/`submitted` (`submitted_at` gezet) → `done` (`done_at` of
`marked_complete`) → `missing` → `closed` (`lock_at` verstreken) → `overdue`
(`due_at` verstreken; bij een tentamen `past`) → `locked` (`unlock_at` in de
toekomst) → `open`. Quiz: `graded` (`finished_at`, met score en "antwoorden
zichtbaar vanaf") → `done` → `closed` → `locked` → `open`; de deadline is
`due_at or lock_at`. Kalenderitem: `past`/`upcoming`. Taak: `done`/`open`.

**Bucket**: `done` voor afgeronde statussen; `undated` zonder datum;
`overdue`; `today`, `tomorrow` (Amsterdamse kalenderdag); `this_week` (zelfde
ISO-week); `next_week`; `later`. Berekend op de server met `zoneinfo`, zodat
een test `now` kan vastzetten; de browser formatteert alleen. `tzdata` gaat
in `requirements.txt` als vangnet.

**Per vak** (elk Canvas-vak, plus elk corpusvak zonder `canvas_id`, zodat
`exams` en de copilot-toestand ook dan zichtbaar zijn): items, aankondigingen
(laatste 10, tekst inbegrepen), materiaal (voorstel + staat, zie 4.6),
tentamens (uit `course.yml` samengevoegd met Canvas-tentamens: bron `yaml`,
`canvas` of `both`, met `days_left`), en de copilot: `due_count`
(`len(due_cards(db, slug))`), `exam_sets` (`exam_progress`, dezelfde
afbeelding als de oefenroute — die helper wordt gedeeld), weken zonder
samenvatting (uit `week_plans` en `WeekSummary`, nooit `is_stale`: dat
herberekent de stof), open opgavenbladen (`Document`, lichte select — niet
`list_documents`, die laadt chunks).

**Verschillen** (`diffs`): `due_date_differs` (Amsterdamse datum van
`due_at` ≠ `course.yml`), `yaml_only`, `canvas_only` (Canvas-opdracht met
deadline zonder regel in `course.yml` — de spoilerfilter kent hem niet),
`exam_date_differs`, `exam_missing_in_yaml`, `canvas_id_missing` (met de
vermoedelijke slug als de namen overlappen), `assignment_sheet_missing` (het
opgavenblad zit bij de opdracht in Canvas maar niet in het corpus; wijst
naar het bestand).

**Doorlinks**: een opdracht met een `course.yml`-regel in week *W* krijgt
`coach_document_id` als er een open `assignment`-document in die week is →
`/?course=<slug>&coach=<id>`. Tentamen → `/oefenen?course=<slug>&exam=
<origin>` per set en `/oefenen?course=<slug>&review=1`. Week → `/weken?
course=<slug>&week=N`.

**Tijd op de draad**: opslag naïef UTC; het leesmodel hangt `timezone.utc`
eraan, zodat pydantic `Z` schrijft en `new Date()` in de browser goed valt.
Zonder dat leest de browser `2026-09-28T21:59:00` als lokale tijd: twee uur
ernaast. Datums uit `course.yml` en `Task.due_on` blijven `YYYY-MM-DD`.

### 4.6 Materiaal: `placement.py` en `materials.py`

```python
def propose_placement(file, course, *, corpus_root) -> Proposal   # placement | None, altijd een reden
def material_state(file, proposal, existing) -> str               # new | in_corpus | downloaded | ignored | unsupported | unplaced
def fetch_material(db, client, file_id, *, doc_kind=None, week=None, overwrite=False)
def set_ignored(db, file_id, ignored) -> CanvasFile
```

Regels, de eerste die past wint, elke regel schrijft zijn bewijs in de reden;
nooit `submission`, `solution` of `note`:

1. Extensie niet in `SUPPORTED_SUFFIXES` → `unsupported` ("`.ipynb` wordt
   niet geïndexeerd; alleen .pdf en .pptx").
2. Gelinkt vanuit een opdracht, of `assignment|opdracht|homework` in de naam
   → `assignment`; week uit de `course.yml`-regel met dezelfde
   genormaliseerde naam (of hetzelfde volgnummer: `SSO_assignment1` → 1).
   Geen regel → geen voorstel ("opdrachtblad, maar geen regel in course.yml
   heet zo"). Assignment 0 en uitwerkingen vallen hier bewust buiten.
3. Collegenummer *n* uit de naam (`lecture05`) of de map (`Lecture 4`) →
   `slides`; week uit de modulenaam ("Week 3") of uit `lectures:` in
   `course.yml`. Geen week → geen voorstel ("college 5, maar geen week in
   course.yml noemt college 5 — voeg `lectures:` toe").
4. Map `Exercises` of naam `Section+6.2.pdf` → `exercise`; week uit het
   leesplan als de sectie daar staat (`"6.2"` → SSO week 1), anders geen
   week.
5. `exam|tentamen|mock` → `exam`. Jaartal vooraan (`2014-Rougier`) of map
   `Readings` → `paper`.
6. Alles wat overblijft (handouts, tabellen, R-intro) → geen voorstel met
   reden; de gebruiker kiest soort en week in de pagina.

Het pad komt uit `build_corpus_path` (dus `Section+6.2.pdf` wordt
`Section-6.2.pdf`). Staat `in_corpus` als er al een document met die
bestandsnaam in het vak is (lecture1–3 van SSO staan er al).

Ophalen gaat door hetzelfde ingestpad als uploaden. Daarvoor verhuist het
lijf van de uploadroute naar `services/documents.py`:

```python
def ingest_bytes(db, *, content, filename, course_slug, doc_kind, week, overwrite=False)
    -> tuple[Document, int, str, int]
```

(`validate_upload` → `build_corpus_path` → duplicaatcontrole → `write_bytes`
→ `Document` → `index_document` → `upsert_course_from_yaml` →
`recompute_assignment_status`). De uploadroute wordt een dunne schil; de
bestaande uploadtests bewaken de verhuizing. `fetch_material` neemt een
expliciete `doc_kind`/`week` als de gebruiker het voorstel corrigeert, en
weigert zonder voorstel én zonder keuze ("kies soort en week").

### 4.7 Routes

`api/routes/agenda.py`, `APIRouter(prefix="/agenda")`; `_client()` als
seam.

| Route | Antwoord | Fouten |
|---|---|---|
| `GET /api/agenda` | `AgendaRead {now, canvas: {configured, synced_at, stale}, courses[], tasks[], problems[]}` | — |
| `POST /api/agenda/sync` | `CanvasSyncResponse {synced_at, courses, items, announcements, files_new, lines[], problems[]}` | 400 zonder configuratie, 502 bij een Canvas-fout (momentopname blijft) |
| `PATCH /api/agenda/courses/{canvas_id}` `{hidden}` | `CanvasCourseRead` | 404 |
| `PATCH /api/agenda/items/{id}` `{done}` | `AgendaItemRead` | 404 |
| `POST /api/agenda/tasks`, `PATCH …/{id}`, `DELETE …/{id}` | `TaskRead` (`title, notes, due_on, course_slug, link, done_at, bucket`) | 404, 422 |
| `POST /api/agenda/materials/{id}/fetch` `{doc_kind?, week?, overwrite?}` | `{material, document, chunk_count}` | 400 (geen voorstel, niet ondersteund), 409 (bestaat), 502 |
| `POST /api/agenda/materials/{id}/ignore` `{ignored}` | `MaterialRead` | 404 |

`stale` = geen `synced_at` of ouder dan `canvas_stale_after_minutes` (30).
Er draait geen planner in de app: de pagina synchroniseert zelf als de
momentopname oud is, en bij *Ververs*. Dat houdt `lifespan` leeg, en dus de
tests vrij van bijwerkingen.

## 5. Frontend

- Nav-item **Agenda** vooraan. `app/agenda/page.tsx` → `components/agenda/
  agenda-console.tsx`; scrollende pagina zoals `/corpus`.
- Kop: de dag, "bijgewerkt 12 min geleden", knop *Ververs* ("Bezig…").
  Balken voor: geen token, synchronisatiefout, `course.yml`-problemen.
- **Deadlines** (`deadline-list.tsx`, `deadline-row.tsx`): Canvas-items én
  taken in één lijst per bucket — Verlopen, Vandaag, Morgen, Deze week,
  Volgende week, Later (ingeklapt), Zonder datum, Afgerond (ingeklapt). Rij:
  datum en tijd, relatief ("over 4 dagen"), vak, soort, titel (naar Canvas),
  punten of score, status-badge, en de knoppen Coach / Opgavenblad ophalen /
  Klaar. Een taak heeft een vinkje en verwijderen.
- **Tentamens** (`exam-cards.tsx`): per vak dagen te gaan, `course.yml`
  naast Canvas als ze verschillen, de sets met laatste score, *Herhalen (n)*,
  weken zonder samenvatting.
- **Per vak** (`course-panel.tsx`): weging als die er is, **Nieuw op Canvas**
  (`materials-list.tsx`: bestand, herkomst, voorgesteld pad in monospace of
  de reden in accentkleur; bij geen voorstel een soort-keuze en weekveld;
  *Haal op* / *Negeer*; niet-ondersteund grijs met reden), **Aankondigingen**
  (ingeklapte tekst, "ongelezen"), verschillen als waarschuwingsbalken,
  verbergen. Verborgen vakken onderaan met "toon".
- Nieuw: `lib/dates.ts` (`formatDate`, `formatDateTime`, `formatRelative`,
  `formatAgo`, alles `Intl.DateTimeFormat("nl-NL", {timeZone: "Europe/
  Amsterdam"})`; `YYYY-MM-DD` handmatig geparsed), types en `api.ts`-functies.
- **Doorlinks** in de bestaande consoles, met hun state-model intact:
  `useSearchParams()` in `ChatWorkspace` (`course`, `coach`),
  `PracticeConsole` (`course`, `exam`, `section`, `review`) en `WeekConsole`
  (`course`, `week`); de page-shims krijgen `<Suspense fallback={null}>`
  (Next 15 weigert anders te bouwen). De parameters worden één keer gelezen
  (`useRef`-vlag) nadat de vakken en het overzicht geladen zijn:
  `selectCourse(slug)` en dan `setCoach({document_id})` zodra het document
  in `coachChoices` zit; `openExam(origin, section)`; `startReview()`; de
  week kiezen. Niets schrijft terug naar de URL.

## 6. Tests

Backend, met opgenomen en geschoonde Canvas-antwoorden in
`tests/fixtures/canvas/*.json` en een stub-`opener` in `tests/canvas_stub.py`
(pad → antwoord, telt aanroepen, controleert de Bearer-header).

- `test_canvas_client.py`: header en `/api/v1/`-prefix, `include[]` met
  `doseq`, paginering over twee pagina's, dict-antwoord niet gepagineerd,
  403 → `CanvasError` zonder token in de tekst, `URLError` → status None,
  `get_optional`, `download` boven `max_bytes`, `strip_html`,
  `parse_timestamp` naïef, `file_ids_in_html`, `client_from_settings` None
  onder de autouse-fixture.
- `test_corpus_sync.py`: `canvas_id`, `exams`, `assignments`-lijst,
  problemen bij foute invoer; `deadlines` ongewijzigd.
- `test_canvas_sync.py`: eerste run (soorten, naïef UTC, score,
  `marked_complete`, bestanden met map en herkomst); tweede run zonder
  dubbelingen en zonder `files/{id}`; verdwenen item weg, `done_at`/
  `ignored_at`/`hidden` blijven; verborgen vak niet opgehaald; 403 op mappen
  → `skipped`; 401 → niets geschreven; verstreken deadline → `closed`;
  `dry_run`.
- `test_canvas_placement.py`: tabelgestuurd over de regels en alle
  redenen; `in_corpus`.
- `test_canvas_materials.py`: ophalen schrijft in `tmp_corpus` en
  indexeert met de fake-pijplijn uit `test_documents_api.py`; correctie
  wint; zonder voorstel 400; 409; `.ipynb` 400; Canvas 404 → 502; negeren.
- `test_agenda_model.py`: statusmatrix; bucketgrenzen in Amsterdamse tijd
  (`21:59Z` is vandaag, `22:30Z` morgen; zondag deze week, maandag
  volgende); `due_date_differs` en `same_day`; elk verschil; coachlink
  alleen bij een open opgavenblad; copilot-tellers; `Z` in de JSON.
- `test_agenda_api.py`: `GET` zonder Canvas; `POST /sync` 400 en met stub
  200; 401 → 502 met intacte rijen; verbergen; items afvinken; taken
  aanmaken, afvinken, datum wissen, verwijderen.
- `test_cli.py`: `canvas-sync` regels en exitcode, zonder configuratie,
  `--dry-run`.

Frontend: `npx tsc --noEmit` én `npx next build` (die vangt de
Suspense-eis).

## 7. Fasen

Elke fase eindigt groen en is een eigen commit.

0. Instellingen, `course.yml`-sleutels, `Course`-kolommen, tabellen,
   autouse-fixture.
1. `client.py`, fixtures, stub.
2. `sync.py` + `refresh_course_rows` + CLI.
3. `agenda.py`, schema's, routes (`GET`, `POST /sync`, vakken, items, taken).
4. Pagina: types, `api.ts`, `dates.ts`, nav, deadlines, tentamens, taken,
   aankondigingen, verschillen, auto-sync bij `stale`.
5. Doorlinks in de drie consoles.
6. Materiaal: `placement.py`, `ingest_bytes`-verhuizing, `materials.py`,
   routes, `materials-list.tsx`.
7. `course.yml`'s invullen, `.env.example`, `README`, `corpus/README`,
   statusregel. Optioneel: weging uit `assignment_groups`.

## 8. Risico's

- Een test die per ongeluk naar Canvas gaat — de autouse-fixture is niet
  onderhandelbaar.
- De eerste synchronisatie duurt 10–30 s (± 70 bestandsaanroepen): de pagina
  toont eerst de momentopname en synchroniseert daarna.
- `CERTIFICATE_VERIFY_FAILED` op de python.org-build: certifi-context.
- Naamkoppeling `course.yml` ↔ Canvas mist een keer: dat wordt een
  `yaml_only`/`canvas_only`-melding, nooit een verkeerde koppeling.
- `init_db` voegt kolommen toe aan `data/app.db` bij de eerste start (en in
  tests, zoals nu al). Eén keer `data/app.db` kopiëren vóór de eerste run is
  goedkoop.
- `.md` en `.ipynb` blijven buiten het corpus: gemeld, niet geplaatst.
