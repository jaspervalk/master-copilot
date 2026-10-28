# Master Copilot — Design (Fase 1)

**Datum:** 2026-09-01
**Status:** ter review

---

## 1. Wat dit is

Een retrieval-copilot over het eigen studiemateriaal van een Data Science-master:
tekstboeken, colleges­lides, papers, opgavenbladen, eigen ingeleverde uitwerkingen en
officiële uitwerkingen. Je stelt een vraag, krijgt uitleg terug met een vindplaats die
je kunt naslaan ("Bishop §5.3", "week 4, slide 12").

Het project is een werktuig eerst. Het moet bruikbaar zijn in het eerste blok; dat het
ook een portfoliostuk wordt, is bijvangst.

### Fasering

Fase 1 is de spec hieronder. De latere fasen staan hier alleen zodat fase 1 hun
fundament niet blokkeert.

| Fase | Inhoud | Leunt op |
|---|---|---|
| **1** | Corpus uit mapstructuur, upload via de browser, PDF + PPTX, hybride retrieval met vak/week-filters, meerdere gespreksbeurten, antwoord met vindplaats, minimale chat-UI, query-logging | — |
| 2 | Huiswerk-coach: hints in plaats van antwoorden, uitwerkingen van *open* opdrachten uitgesloten van retrieval | `assignment_status` uit fase 1 |
| 3 | Tentamentrainer: vragen genereren, overhoren, antwoord toetsen aan materiaal | corpus + retrieval |
| 4 | Eval-harness gevoed door de echte query-log | logging uit fase 1 |

### Wat fase 1 uitdrukkelijk niet doet

Geen notebooks of losse code (uitwerkingen worden als PDF geëxporteerd), geen
URL-ingest van webboeken, geen OCR, geen eval-dashboard, geen multi-user of
authenticatie, geen coach- of overhoormodus.

---

## 2. Herkomst van de code

Dit is een nieuw repo dat bewezen modules overneemt uit
`Healthcare-Policy-Copilot`. Overnemen betekent kopiëren en aanpassen, geen
gedeelde package.

**Vrijwel ongewijzigd over te nemen**

| Module | Aanpassing |
|---|---|
| `services/embeddings.py` | geen |
| `services/index_stamp.py` | geen |
| `services/qdrant_index.py` | payloadvelden en payload-indexen worden de nieuwe metadata |
| `services/storage.py` | sha256, padhulp, schrijven binnen `corpus/` |
| `services/upload_safety.py` | groottelimiet en magic-byte-check uitgebreid met PPTX (`PK\x03\x04`) |
| `services/answer_stream.py` | geen |
| `api/errors.py`, `db.py`, `main.py` | geen noemenswaardige |
| web: `components/ui/*`, `shell/*`, `qa/citation-chip`, `qa/evidence-panel`, `qa/confidence-chip`, `qa/answer-with-citations`, `lib/api.ts:streamAnswer` | labels en velden |

**Overnemen met inhoudelijke wijziging:** `services/chunking.py` (zie §5),
`services/retrieval.py` (zie §6), `services/answering.py` (zie §7),
`services/hybrid_index.py` (zie §6), `services/query_logs.py` (velden).

**Vervalt:** de heuristische detectors in `services/documents.py`
(`_detect_department`, `_detect_policy_status`, `_detect_document_type`,
`_detect_version`) — het pad levert de metadata —, `api/auth.py` (lokaal,
één gebruiker), `PATCH /api/documents/{id}` (metadata wijzig je door het bestand te
verplaatsen), `components/evals/*`, `components/queries/*`.

**Overnemen met wijziging:** `components/library/library-console.tsx` wordt de
corpuspagina: dezelfde tabel, filters en verwijderdialoog, maar het uploadformulier
vraagt vak, soort en week in plaats van beleidsmetadata.

**Nieuw:** `services/path_metadata.py`, `services/pptx_parser.py`,
`services/slide_chunking.py`, `services/corpus_sync.py`, `cli.py`,
`services/conversations.py`, web `components/chat/*`.

---

## 3. Corpus: de mapstructuur is de waarheid

```
corpus/
  <vak-slug>/                     bijv. statistical-learning
    course.yml                    optioneel: volledige naam, periode, docent
    books/                        tekstboeken, hele PDF's
    papers/                       losse artikelen
    slides/week-03/               collegeslides (PDF of PPTX)
    assignments/week-03/          opgavenbladen
    submissions/week-03/          eigen ingeleverde uitwerkingen (PDF-export)
    solutions/week-03/            officiële uitwerkingen
    notes/                        eigen aantekeningen
```

**Afleidingsregels**

- `course_slug` — eerste segment onder `corpus/`.
- `doc_kind` — tweede segment, uit de gesloten verzameling
  `book | paper | slides | assignment | submission | solution | note`.
- `week` — uit een `week-NN`-map, anders uit een `week-NN`/`wNN`-patroon in de
  bestandsnaam, anders `null`.
- `title` — uit `course.yml` indien aanwezig, anders uit de PDF-metadata, anders
  de opgeschoonde bestandsnaam.

Een pad dat niet aan de vorm voldoet — onbekende tweede map, bestand direct onder
`corpus/<vak>/` — wordt **geweigerd met een expliciete melding**, niet stil op een
default gezet. Een verkeerd gelabeld document verpest retrieval zonder dat je het
merkt; een foutmelding bij `sync` is goedkoper dan een verkeerd antwoord in week 6.

`course.yml` is optioneel en bevat alleen presentatievelden:

```yaml
name: Statistical Learning
period: 2026-1
lecturer: ...
```

**Opdrachtstatus** wordt afgeleid, niet ingevoerd: een opdracht van vak X, week N
heeft `assignment_status = submitted` zodra er ten minste één bestand in
`corpus/X/submissions/week-NN/` staat, anders `open`. De status wordt bij elke `sync`
herberekend voor alle opdrachten van het vak. Fase 1 slaat de status op, toont hem in
de bron-weergave en maakt hem filterbaar; fase 2 gebruikt hem om uitwerkingen van
open opdrachten te verbergen.

`corpus/` staat in `.gitignore`. Auteursrechtelijk beschermd studiemateriaal hoort
niet in een publiek repo.

---

## 4. Ingest: twee ingangen, één pijplijn

Eén commando, idempotent:

```bash
python -m app.cli sync [--course statistical-learning] [--dry-run]
```

Stappen:

1. Loop `corpus/` af, verzamel bestanden met een ondersteunde extensie (`.pdf`, `.pptx`).
2. Leid metadata af uit het pad (§3). Weiger onbekende vormen en verzamel die
   fouten; rapporteer ze aan het eind, ga door met de rest.
3. Bereken sha256. Vergelijk met de `Document`-rij voor dat pad:
   - onbekend pad → indexeren;
   - bekend pad, gelijke hash → overslaan;
   - bekend pad, andere hash → opnieuw indexeren (chunks en vectoren vervangen);
   - rij zonder bestand op schijf → document, chunks en Qdrant-punten verwijderen.
4. Parse → chunk (§5) → embed → Qdrant-upsert, met dezelfde atomaire schrijfvolgorde
   als het healthcare-project: SQL-transactie open, Qdrant schrijven, dan pas
   committen; faalt Qdrant, dan rollback.
5. Herbereken `assignment_status` per vak.
6. Herbouw de BM25-index.
7. Print een samenvatting: toegevoegd, bijgewerkt, overgeslagen, verwijderd, geweigerd.

`--dry-run` doet stap 1–3 en drukt het plan af zonder te schrijven.

Er is geen achtergrondwachter en geen wachtrij. Je draait `sync` als je nieuw
materiaal hebt neergezet.

### Ingang B — upload via de browser

`POST /api/documents/upload`, multipart: het bestand plus `course_slug`, `doc_kind`
en optioneel `week`. De route:

1. controleert grootte en magic bytes (`%PDF-` of `PK\x03\x04`) vóór er iets naar
   schijf gaat;
2. bepaalt het doelpad `corpus/<vak>/<soort>/[week-NN/]<veilige-bestandsnaam>` en
   controleert dat dat pad binnen `corpus/` valt;
3. weigert bij een botsing tenzij `overwrite=true` is meegegeven;
4. schrijft het bestand en draait daarna exact dezelfde stappen 4–6 als `sync` voor
   dat ene bestand.

De upload-UI zet dus bestanden *in* de mapstructuur. Het pad blijft de enige bron van
waarheid: wat je uploadt, vind je in Finder terug, en een `sync` erna verandert niets.

`DELETE /api/documents/{id}` verwijdert de rij, de chunks en de Qdrant-punten, en
**verplaatst** het bestand naar `corpus/.trash/<vak>/…` in plaats van het te wissen.
Hard wissen zou onherstelbaar zijn en alleen verplaatsen-naar-prullenbak houdt de
volgende `sync` eerlijk: een bestand dat er nog staat, komt anders gewoon terug.
`corpus/.trash/` wordt bij het scannen overgeslagen.

---

## 5. Chunking per documentsoort

Eén interface, drie strategieën. De keuze volgt uit `doc_kind`.

**Boeken en papers** — de bestaande venster-chunker (425 woorden, 75 overlap) met één
wijziging: `section_path` wordt **hiërarchisch**. De chunker houdt een koppenstapel
bij op basis van genummerde secties, waarbij de diepte volgt uit het aantal punten in
het nummer (`5` → diepte 1, `5.3` → diepte 2). Resultaat:
`"5 Neural Networks › 5.3 Error Backpropagation"`. Zonder die hiërarchie is een
citaat in een boek van 800 bladzijden niet na te slaan.

**Slides** — één slide is één chunk. Slides met minder dan 25 woorden worden met de
volgende samengevoegd (titelslides, "Questions?"). `section_path` wordt de decktitel,
`page_start = page_end = slidenummer`. Vensters van 425 woorden slaan hier nergens op:
een slide bevat één idee, en dat idee moet als geheel terugkomen.

**Opgaven, uitwerkingen en eigen inzendingen** — knippen op opgave-eenheden waar die
herkenbaar zijn (`Exercise N`, `Question N`, `Opgave N`, `Problem N`), zodat een
opgave met zijn uitwerking in één chunk blijft. Geen match, dan de gewone
venster-chunker.

**Aantekeningen** — gewone venster-chunker.

---

## 6. Retrieval

Hybride standaard: dense (Qdrant) en BM25, samengevoegd met RRF, precies zoals in het
healthcare-project. Twee wijzigingen.

**Filterbewuste sparse index.** De bestaande implementatie laat sparse-kandidaten
vallen zodra er een filter actief is, omdat de BM25-index geen metadata kent. In deze
toepassing staat er vrijwel altijd een vakfilter aan, dus zou hybrid stil terugvallen
op dense-only. De BM25-index krijgt daarom per chunk de metadata mee
(`course_slug`, `week`, `doc_kind`, `assignment_status`) en filtert de kandidatenlijst
vóór het scoren. Juist bij notatie-achtige termen (ELBO, L1, bias-variance) draagt
BM25 hier de halve kwaliteit.

**Filters als eersteklas begrip.** `QueryFilters` wordt:
`course_slug`, `week`, `doc_kind` (meervoudig), `assignment_status`. De UI zet
`course_slug` standaard op het gekozen vak.

Payload in Qdrant per chunk: `document_id`, `document_title`, `source_path`,
`course_slug`, `week`, `doc_kind`, `assignment_status`, `section_path`, `page_start`,
`page_end`, `text`, `chunk_metadata`. Payload-indexen op `course_slug`, `week`,
`doc_kind`, `assignment_status`.

`top_k` standaard 8; over-fetch 30 per ranker vóór fusie, zoals nu.

---

## 7. Gesprek en antwoord

**Meerdere beurten.** Twee tabellen, `Conversation` en `Message`. Bij een vervolgvraag
wordt de vraag eerst herschreven tot een zelfstandige zoekvraag: een korte LLM-aanroep
met de laatste beurten plus de nieuwe vraag ("en waarom is dat convex dan?" →
"waarom is de loss-functie van logistische regressie convex?"). De herschreven vraag
gaat naar retrieval; de oorspronkelijke vraag plus de laatste beurten gaan naar het
antwoordmodel. Bij de eerste beurt wordt de herschrijfstap overgeslagen. De herschreven
vraag wordt gelogd, zodat je kunt zien wanneer de herschrijving ernaast zat.

**Antwoordcontract.** Gestructureerde uitvoer zoals in het healthcare-project:
`answer` (markdown met inline `[n]`-verwijzingen), `citations[]` (chunk-id plus
ondersteunend citaat), `abstained`, `confidence` en `confidence_reasons`. Verzonnen
chunk-id's worden weggegooid — die invariant blijft, met test.

Twee verschillen met het beleidsdomein:

- **Vindplaats, geen bewijslast.** De verwijzing dient om na te slaan, niet om te
  bewijzen. Er wordt alleen geabstineerd als retrieval leeg is of alle scores onder de
  drempel liggen. Een copilot die bij twijfel zwijgt, is bij studeren onbruikbaar.
- **Twee antwoordstijlen**, als schakelaar in de UI: *kort* (direct antwoord, enkele
  regels) en *uitleg* (opbouw vanaf de basis, met voorbeeld). Twee prompts, één veld
  in het verzoek.

Vertrouwen wordt afgeleid uit het bewijs (`evidence_confidence`) en gecombineerd met
de zelfrapportage van het model door het minimum te nemen — ongewijzigd overgenomen.

Streamen via SSE, met de bestaande `AnswerFieldStreamer`.

**Logging.** Elke vraag levert een `QueryLog`-rij: oorspronkelijke vraag, herschreven
vraag, filters, retrievalmodus, opgehaalde chunk-id's met scores, antwoordmodel,
vertrouwen, of er geabstineerd is, en de duur. Dit is fase 4's eval-dataset; hij moet
er vanaf dag één zijn.

---

## 8. API

| Methode | Pad | Doel |
|---|---|---|
| GET | `/api/health` | statuscheck |
| GET | `/api/courses` | vakken met documentaantallen, weken, open opdrachten |
| GET | `/api/documents` | corpusoverzicht, filterbaar op vak en soort |
| POST | `/api/documents/upload` | bestand + vak/soort/week → schrijft in `corpus/` en indexeert |
| POST | `/api/documents/{id}/index` | opnieuw indexeren |
| DELETE | `/api/documents/{id}` | rij, chunks en vectoren weg; bestand naar `corpus/.trash/` |
| POST | `/api/query` | alleen retrieval (debug en evidence-paneel) |
| POST | `/api/chat` | antwoord, niet-streamend |
| POST | `/api/chat/stream` | antwoord, SSE |
| GET | `/api/conversations` | lijst |
| GET | `/api/conversations/{id}` | beurten van één gesprek |

Elke schrijfroute komt uit op dezelfde pijplijn als `sync`; er is geen tweede
ingest-pad om uit de pas te lopen.

---

## 9. Datamodel

- `Document` — `id`, `source_path` (uniek), `checksum`, `title`, `course_slug`,
  `doc_kind`, `week`, `assignment_status`, `page_count`, `chunk_count`,
  `indexed_at`, `ingestion_status`, `parse_error`.
- `Chunk` — `id`, `document_id` (cascade), `chunk_index`, `section_path`,
  `page_start`, `page_end`, `token_count`, `text`, `normalized_text`,
  `chunk_metadata`.
- `Course` — `slug` (sleutel), `name`, `period`, `lecturer`. Aangemaakt bij `sync`,
  verrijkt uit `course.yml`.
- `Conversation` — `id`, `course_slug`, `title`, `created_at`.
- `Message` — `id`, `conversation_id`, `role`, `content`, `rewritten_query`,
  `citations_json`, `created_at`.
- `QueryLog` — zoals §7.
- `IndexCollection` — provider/model/dimensie-stempel, ongewijzigd overgenomen.

SQLite op `data/app.db`. Qdrant embedded op `data/qdrant/`.

---

## 10. Frontend

Eén pagina. Links een vakkiezer met weekfilter, midden de gespreksdraad, rechts een
bronpaneel dat de aangehaalde chunk toont met de vindplaats en het citaat gemarkeerd.

Hergebruikt: `app-shell`, `nav`, `ui/*`, `citation-chip`, `evidence-panel`,
`confidence-chip`, `answer-with-citations`, `lib/api.ts:streamAnswer`.
Nieuw: `chat/thread.tsx` (beurten), `chat/composer.tsx` (vraag, stijlschakelaar,
filters), `chat/course-picker.tsx`.

Een tweede pagina `/corpus` toont wat er geïndexeerd is, per vak en week, met de
opdrachtstatus — zodat je ziet of de import heeft gedaan wat je dacht. Daar zit ook
het uploadformulier (bestand kiezen, vak, soort, week) en de verwijderdialoog.
Overgenomen uit `library-console.tsx`, met de beleidsvelden vervangen door
vak/soort/week.

---

## 11. Testen

TDD, pytest. De tests die de kern bewaken:

| Test | Bewaakt |
|---|---|
| `test_path_metadata` | pad → metadata voor elke `doc_kind`; weigering bij onbekende vorm; weekherkenning uit map en bestandsnaam |
| `test_corpus_sync` | idempotentie (tweede `sync` wijzigt niets), gewijzigde hash herindexeert, verdwenen bestand ruimt chunks én vectoren op |
| `test_assignment_status` | status volgt uit aanwezigheid van inzendingen, en wordt bij `sync` herberekend |
| `test_slide_chunking` | één slide per chunk, korte slides samengevoegd, slidenummer als paginaspan |
| `test_section_hierarchy` | genummerde koppen leveren een hiërarchisch `section_path` |
| `test_assignment_chunking` | knippen op opgave-eenheden, terugval op vensters |
| `test_hybrid_filters` | sparse-kandidaten overleven een actief vakfilter; sparse-only treffer buiten het filter wordt geweerd |
| `test_upload` | doelpad volgt uit vak/soort/week, blijft binnen `corpus/`, weigert bij verkeerde magic bytes en bij botsing zonder `overwrite` |
| `test_delete_moves_to_trash` | bestand belandt in `corpus/.trash/`, vectoren zijn weg, volgende `sync` haalt het niet terug |
| `test_query_rewrite` | vervolgvraag wordt zelfstandig; eerste beurt wordt niet herschreven |
| `test_answering` | geen verzonnen citaties, abstineren alleen bij leeg of onder de drempel, beide antwoordstijlen |
| `test_chat_stream` | SSE-vorm |
| `test_query_logs` | herschreven vraag en filters worden vastgelegd |

Frontend: `tsc --noEmit` schoon.

---

## 12. Risico's en beslispunten

**Extractie van formules.** `pypdf` maakt van wiskundige notatie soms soep, en een
DS-master staat er vol mee. De parser blijft daarom achter één interface
(`parse_document(path) -> list[ParsedPage]`). Beslispunt: na de eerste echte
boekimport de tekst van drie formulezware bladzijden bekijken; is die onbruikbaar,
dan `pdfplumber` erachter zetten. Niet vooraf gokken.

**Omvang.** Een boek van 800 bladzijden levert grofweg 2000 chunks; een semester met
vijf vakken blijft ruim onder 50.000 chunks. Embedded Qdrant en SQLite volstaan; het
embedden van een heel boek kost enkele centen. Geen reden voor Postgres in fase 1.

**Slides zonder tekstlaag.** Gescande of volledig als afbeelding geëxporteerde slides
leveren nul tekst. `sync` markeert die als `failed` met een leesbare reden in plaats
van ze stil over te slaan. OCR is fase-4-materiaal of later.

**Scope-drift naar fase 2.** De verleiding is groot om de coach-modus er alvast in te
bouwen. Fase 1 slaat `assignment_status` op en filtert er desgevraagd op, maar bevat
geen coach-prompt en geen spoiler-onderdrukking.

**Auteursrecht.** `corpus/` wordt nooit gecommit. Het portfolioverhaal gaat over de
code, niet over de inhoud.

---

## 13. Definitie van klaar

- `sync` indexeert een echt vak (boek, slides van drie weken, twee opgavenbladen, één
  eigen uitwerking) zonder handmatige correctie.
- Een vraag over dat vak levert een antwoord met een vindplaats die klopt bij naslag.
- Een vervolgvraag zonder onderwerp ("en waarom werkt dat?") haalt de juiste stof op.
- Een vraag buiten het corpus levert een expliciete "dit staat niet in je materiaal".
- Vakfilter aan en toch treffers uit de BM25-tak (aantoonbaar via `/api/query`).
- `pytest` groen, `tsc --noEmit` schoon.
