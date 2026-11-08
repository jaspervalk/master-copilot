# Master Copilot

Een lokale RAG-copilot over je eigen studiemateriaal. Je legt boeken, slides,
opgavenbladen en je eigen uitwerkingen in een mapstructuur; het systeem
indexeert ze en beantwoordt vragen met een vindplaats die je kunt naslaan —
"Bishop §5.3", "week 4, slide 12".

Gebouwd voor een master Data Science, als werktuig eerst.

## Zelf gebruiken

De repo bevat alleen de app. Je materiaal, je database en je sleutels staan er
niet in en komen er ook niet in (`.gitignore`): `corpus/*`, `data/`, `.env`.

1. Python 3.11 en Node 18 of nieuwer; installeer zoals onder [Draaien](#draaien).
2. `cp .env.example .env` en zet je `OPENAI_API_KEY` erin. Zonder sleutel draait
   alles, maar op een hash-embedder met extractieve antwoorden.
3. Maak per vak een map `corpus/<vak>/` met een `course.yml`; het voorbeeld en de
   regels staan in [corpus/README.md](corpus/README.md). Zet er
   `study.assessment` in, één zin over hoe het vak getoetst wordt: daarop
   schrijven de generators hun oefenvragen en voorbeelden.
4. Leg je materiaal in de mappen (`books/`, `slides/week-03/`, …) of upload het
   op `/corpus`, en draai `sync` (zie hieronder).
5. Optioneel: Canvas voor de agenda (zie [Agenda en Canvas](#agenda-en-canvas)),
   en een bijschrift rechts in de kop met `NEXT_PUBLIC_APP_SUBTITLE` in
   `apps/web/.env.local`.

De vakken waarmee de app gebouwd is (FDS, SSO, AFCS) komen in commentaar en
tests terug als voorbeeld; de code zelf hangt van geen enkel vak af.
`eval/cases.yml` is de evalset van die vakken: vervang hem door vragen over je
eigen boeken.

## Wat fase 1 doet

- Corpus uit een mapstructuur: vak, soort en week volgen uit het pad.
- Upload via de browser, die het bestand ín die mapstructuur zet.
- PDF en PPTX, met een chunkstrategie per documentsoort:
  - boeken en papers: vensters van ~425 woorden met hiërarchische sectiepaden
    (`5 Neural Networks › 5.3 Error Backpropagation`);
  - slides: één slide is één chunk;
  - opgaven en uitwerkingen: geknipt op `Exercise N` / `Opgave N`.
- Hybride retrieval: dense (Qdrant) en BM25, samengevoegd met RRF. Beide takken
  kennen dezelfde filters, dus een vakfilter schakelt de BM25-tak niet uit.
- Gesprekken met vervolgvragen: een vraag als "en waarom werkt dat?" wordt eerst
  herschreven tot een zelfstandige zoekvraag.
- Antwoorden met inline verwijzingen, citaties naar de brontekst en een
  vertrouwensindicatie die uit het bewijs volgt, niet uit wat het model over
  zichzelf zegt.
- Elke vraag wordt gelogd — dat wordt later de eval-dataset.

## Fase 2: huiswerkcoach

- `exercises/week-NN/` voor oefenopgaven die je niet inlevert, naast
  `assignments/week-NN/` voor beoordeelde opdrachten.
- Deadlines in `course.yml` (`assignments: [{week, deadline}]`) sluiten een
  opdracht na de datum, ook zonder inzending — bij groepswerk levert een
  teamgenoot in.
- Uitwerkingen (`solutions/`, `submissions/`) van een week met een open
  beoordeelde opdracht komen in geen enkel antwoord terug; altijd, in beide
  retrievaltakken.
- Coachmodus in de chat: kies een opdracht, en het model geeft hints met
  vindplaats in plaats van het antwoord. Bij oefenopgaven geeft *Laat de
  uitwerking zien* alsnog de volledige uitwerking.
- `eval/cases.yml` kent `must_not_mention` en `coach`, zodat lekkage van het
  eindantwoord meetbaar is met `eval --answers`.

## Wat fase 1 niet doet

Geen notebooks of losse code (exporteer uitwerkingen als PDF), geen URL-ingest
van webboeken, geen OCR voor gescande pagina's, geen eval-dashboard, geen
huiswerk-coach of tentamentrainer, geen multi-user of authenticatie.

## Mapstructuur

```
corpus/<vak>/{books,papers,slides,assignments,submissions,solutions,notes}/[week-NN/]
```

Zie [corpus/README.md](corpus/README.md) voor de regels. Kort: het pad is de
enige bron van metadata, en een onbekende mapnaam levert een foutmelding op in
plaats van een stille aanname.

## Draaien

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r apps/api/requirements.txt

# Backend (vanuit de repo-root, zodat .env gevonden wordt)
uvicorn app.main:app --reload --app-dir apps/api          # http://localhost:8000

# Frontend
cd apps/web && npm install && npm run dev                  # http://localhost:3000
```

Materiaal indexeren:

```bash
PYTHONPATH=apps/api python -m app.cli sync
PYTHONPATH=apps/api python -m app.cli sync --dry-run       # eerst kijken
PYTHONPATH=apps/api python -m app.cli sync --course <vak>
```

`sync` is idempotent: twee keer draaien verandert niets. Bestanden worden op
sha256 vergeleken, verdwenen bestanden worden opgeruimd.

## Oefenen en studeren

`/oefenen` begint met "Vandaag": kies hoeveel tijd je hebt en er staat een
ronde klaar uit je eigen stof. Wat je vorige keer miste gaat voorop, een deel
blijft gereserveerd voor nieuwe stof, en geen twee kaarten over dezelfde toets
staan achter elkaar — dat laatste is precies wat een schriftelijk tentamen van
je vraagt. De herhaalafstand krimpt mee met de dagen tot je tentamen.

Daaronder staat per week hoeveel stof er is, hoeveel je ervan beheerst, en
welke onderwerpen uit `course.yml` nog geen kaart hebben, met een knop om die
te maken. Bij elk onderwerp kan een uitgewerkt voorbeeld staan: één situatie
met getallen, stappen met formules, en een figuur die door matplotlib is
getekend — wat niet tekent, komt er niet in.

`/bronnen` legt uit waarom het oefenen zo werkt, met de studies erbij, en
koppelt gratis uitleg (StatQuest, Seeing Theory, OpenIntro, ISLR) aan de
onderwerpen van je weken. Die lijst staat in `resources/library.yml`.

## Agenda en Canvas

`/agenda` toont alle deadlines, quizzen en tentamens van je vakken op één
plek, met je eigen taken ertussen, en linkt door naar de coach, de
oefententamens en de weken. De gegevens komen uit Canvas, alleen lezend:

1. Maak in Canvas een access token aan (Account → Settings → New access token)
   en geef hem een vervaldatum.
2. Zet `CANVAS_BASE_URL` en `CANVAS_ACCESS_TOKEN` in `.env`.
3. Zet `canvas_id` in de `course.yml` van elk vak (het getal uit
   `canvas.uva.nl/courses/<id>`), en eventueel `exams:`.

De pagina ververst zelf als de gegevens ouder zijn dan een half uur. Vanaf de
commandoregel:

```bash
PYTHONPATH=apps/api python -m app.cli canvas-sync --dry-run   # tellen, niets schrijven
PYTHONPATH=apps/api python -m app.cli canvas-sync
```

Onder elk vak staat wat er nieuw op Canvas staat — bestanden en pagina's — met
een voorgestelde plek in het corpus. *Haal op* downloadt en indexeert het;
zonder zeker voorstel kies je zelf soort en week. Een opdracht zonder pdf (FDS)
kan als tekst het corpus in, zodat de coach de opgave kent. Canvas past
`course.yml` nooit aan: waar de deadlines verschillen, zegt de agenda dat.

### Deadlines op je telefoon

`notify` haalt Canvas op en stuurt één bericht met wat er de komende drie
dagen af moet, via [ntfy](https://ntfy.sh) (gratis app, geen account): opdrachten,
quizzen, tentamens en je eigen taken met een datum, geen colleges. Lukt Canvas
niet, dan gaat de laatste momentopname uit; lukt versturen niet, dan probeert hij
het nog twee keer en eindigt hij met exitcode 1. Installeer de app, abonneer op
een lange willekeurige topicnaam en zet die als `NTFY_TOPIC` in `.env`: wie de
naam kent, leest mee.

```bash
PYTHONPATH=apps/api python -m app.cli notify --dry-run   # bericht tonen, niets sturen
PYTHONPATH=apps/api python -m app.cli notify --days 3
```

Dagelijks draaien op een Mac: een launchd-job met `StartCalendarInterval`
(08:00) en `WorkingDirectory` op de repo-root; slaapt de Mac, dan draait hij bij
het wakker worden.

## Tests

```bash
pytest                                                     # 1077 tests
cd apps/web && npx tsc --noEmit && npx next build
```

## Eval

```bash
PYTHONPATH=apps/api python -m app.cli eval --api http://localhost:8000
PYTHONPATH=apps/api python -m app.cli eval --compare data/eval/runs/<vorige>.json
```

De evalset staat in `eval/cases.yml`; zie `eval/README.md` voor de regels.
Zonder draaiende app werkt `eval` ook in-process (laat `--api` weg).

## Omgevingsvariabelen

Zie `.env.example`. De belangrijkste:

| Variabele | Betekenis |
|---|---|
| `OPENAI_API_KEY` | Zet echte embeddings en het antwoordmodel aan. Zonder sleutel draait alles op een lokale hash-embedder plus een extractief antwoord — bruikbaar om de pijplijn te testen, niet om echt mee te studeren. |
| `OPENAI_ANSWER_MODEL` | Standaard `gpt-4.1-mini`. |
| `OPENAI_EMBEDDING_MODEL` | Standaard `text-embedding-3-large` (1024 dims). |
| `QDRANT_URL` | Leeg = embedded Qdrant in `data/qdrant/`. |
| `DATABASE_URL` | Standaard SQLite in `data/app.db`. |
| `CANVAS_BASE_URL` | Bijvoorbeeld `https://canvas.uva.nl`. Samen met het token nodig voor de agenda. |
| `CANVAS_ACCESS_TOKEN` | Je persoonlijke Canvas-token. De app leest alleen; zonder token werkt de agenda op eigen taken en `course.yml`. |
| `NTFY_TOPIC` | De topicnaam voor deadlines op je telefoon (`notify`). Wie hem kent, leest mee; leeg = geen meldingen. |

## Opbouw

```
apps/api/app/
  services/path_metadata.py   pad ⇄ metadata
  services/parsing/           pdf, pptx en markdown achter één ingang
  services/chunking/          prose | slides | assignments + dispatcher
  services/corpus_sync.py     scan, diff, indexeren, opruimen
  services/documents.py       atomaire ingestpijplijn
  services/hybrid_index.py    filterbewuste BM25 + RRF
  services/retrieval.py       dense | hybrid
  services/answering.py       gestructureerd antwoord, twee stijlen
  services/answer_stream.py   SSE-statemachine
  services/conversations.py   gesprekken + herschrijven van vervolgvragen
  services/canvas/            Canvas-client, momentopname, agenda, materiaal
  services/study/             beheersing, dekking per week, de ronde van nu,
                              voorbeelden met figuren, externe bronnen
apps/web/
  app/agenda/page.tsx         deadlines, tentamens, nieuw materiaal
  app/oefenen/page.tsx        de ronde van vandaag, dekking per week
  app/bronnen/page.tsx        de methode met bronnen, uitleg per onderwerp
  app/page.tsx                chat
  app/corpus/page.tsx         corpusbeheer
```

De ontwerpen per fase staan in `docs/ontwerp/`.

## Licentie

MIT, zie [LICENSE](LICENSE).
