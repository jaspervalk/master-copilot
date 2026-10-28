# Eval-harness — Design (Fase 4, klein)

Datum: 2026-09-02. Bewust klein: één dag werk, gericht op één vraag — *haalt
retrieval de juiste passage op?* Alles wat verder gaat (antwoordkwaliteit met
een LLM-rechter, dashboards) is uitdrukkelijk later.

## 1. Waarom nu

De retrieval-audit van 1 september repareerde een chunker die er 40× naast zat.
Dat lukte met vijf handgekozen vragen, omdat de fout enorm was. De keuzes die
nu nog open staan zijn subtiel — reranking, de `min_evidence_score`-drempel die
sinds de nieuwe chunks niets meer doet, modelkeuze, straks of de huiswerkcoach
écht geen antwoorden lekt — en die zijn zonder meetlat niet te nemen. Elke
keuze op gevoel kan net zo goed 3% schaden als helpen.

## 2. Wat het is

Een set vragen met een verwachte vindplaats, een runner die retrieval erop
loslaat, en een rapport dat over runs heen te vergelijken is.

```
eval/cases.yml                 de vragen, in git
data/eval/runs/<tijd>.json     elke uitvoering, niet in git
python -m app.cli eval         draaien
python -m app.cli eval-seed    skelet maken uit de echte query-log
```

## 3. Beslissingen

### 3.1 Verwachtingen wijzen naar pagina's, niet naar chunks

`chunk_id` is een UUID die bij elke herindexering verandert. Een evalset die
daarop leunt is na één `sync` waardeloos. De stabiele ankers in dit corpus zijn
`source_path` en paginanummer. Een treffer telt als het paginabereik van de
chunk het verwachte bereik overlapt.

```yaml
- id: islr-kfold
  course_slug: sso
  question: hoe werkt k-fold cross-validation?
  expected:
    - source_path: sso/books/ISLRv2_corrected_June_2023.pdf
      pages: [214, 216]
```

Meerdere `expected`-items betekenen: elk ervan telt. Zo kan een vraag over
bias-variance zowel het boek als de slides van week 3 als goed rekenen.

### 3.2 De verwachting komt uit de inhoudsopgave, niet uit het systeem

De eerste set (~20 vragen) wordt geschreven met paginabereiken uit de
bladwijzers van de PDF's — dezelfde bladwijzers die de chunker nu als
sectiepad gebruikt, maar hier als *onafhankelijke* waarheid: waar zegt de
uitgever dat k-fold staat? Verwachtingen overnemen uit wat retrieval toevallig
teruggeeft zou de meetlat aan het gemetene ijken.

`eval-seed` helpt bij uitbreiden: het dumpt de laatste onderscheidende vragen
uit `query_logs` als YAML-skelet mét de toen opgehaalde toppagina als
*kandidaat*, gemarkeerd als `unverified: true`. De runner slaat onbevestigde
cases over. Bevestigen is een bewuste handeling: het veld weghalen.

### 3.3 Retrieval-metrics standaard, antwoorden opt-in

Standaard draait alleen retrieval: één query-embedding per case, een paar cent
voor de hele set, seconden werk. Metrics:

| metric | betekenis |
|---|---|
| `hit@1`, `hit@3`, `hit@5`, `hit@k` | verwachte pagina zit in de top-n |
| `mrr` | 1 / positie van de eerste goede treffer |
| `abstain_ok` | voor cases met `expect_abstain: true`: kwam er niets relevants |

Met `--answers` draait ook het antwoordmodel en komen erbij: `confidence`,
`abstained`, `latency_ms`, en een simpele `mentions`-check voor cases met een
`must_mention`-lijst (letterlijke substrings, hoofdletterongevoelig). Geen
LLM-rechter in deze fase.

### 3.4 Twee manieren om te zoeken

Embedded Qdrant is single-process: de runner kan niet naast de draaiende API
werken. Daarom neemt de runner een zoekfunctie, met twee adapters:

- in-process (`RetrievalService`), standaard, zoals `sync`;
- `--api http://localhost:8000`, via `POST /api/query` — voor als de app
  aanstaat. Zelfde code, zelfde filters.

## 4. Onderdelen

```
apps/api/app/eval/
  cases.py      laden en valideren van eval/cases.yml (pydantic)
  metrics.py    pure functies: overlap, hit@k, mrr — geen I/O
  runner.py     cases × zoekfunctie → per-case-resultaat → rapport
  seed.py       query_logs → skelet-YAML
  report.py     tabel naar stdout, JSON naar data/eval/runs/, --compare
```

`cli.py` krijgt `eval` en `eval-seed`. `core/config.py` krijgt `eval_dir`
(`ROOT_DIR / "eval"`) en `eval_runs_dir` (`DATA_DIR / "eval" / "runs"`).

### Rapport

```
eval  2026-09-02T14:03  22 cases  hybrid  top_k=8
                        hit@1   hit@3   hit@5   hit@8   mrr
sso            (12)     0.83    0.92    1.00    1.00    0.88
fundamentals   (10)     0.70    0.90    0.90    1.00    0.79
totaal         (22)     0.77    0.91    0.95    1.00    0.84

gemist in top-3:
  fds-groupby-agg   verwacht p179-181   kreeg p177 p183 p160
```

`--compare data/eval/runs/<vorige>.json` zet de delta ernaast. Dat is de hele
reden van het JSON-bestand: een verandering aan retrieval moet in één regel te
beoordelen zijn.

## 5. Fouten

- Een case zonder geldige `source_path` in de database faalt de run met een
  duidelijke melding, niet stil als "miss": een verhuisd bestand is een
  evalset-fout, geen retrievalfout.
- `unverified` cases worden geteld en gemeld, niet gedraaid.
- Faalt één zoekopdracht (netwerk, model), dan wordt die case als `error`
  gerapporteerd en loopt de run door.

## 6. Testen

- `cases.py`: geldige en ongeldige YAML, `unverified` overslaan.
- `metrics.py`: overlap op grenzen, hit@k, mrr — allemaal puur, allemaal snel.
- `runner.py`: met een nep-zoekfunctie die vaste resultaten teruggeeft;
  controleert het rapport en de foutafhandeling.
- `seed.py`: tegen een SQLite met een paar `QueryLog`-rijen.
- Geen tests die OpenAI of Qdrant nodig hebben.

## 7. Wat dit niet doet

Geen LLM-rechter voor antwoordkwaliteit, geen dashboard, geen CI-integratie,
geen automatische verwachtingen. Twintig vragen die iemand heeft nagekeken
verslaan tweehonderd die niemand heeft gezien.

## 8. Definitie van klaar

- `eval/cases.yml` met ≥ 20 bevestigde cases over sso en fundamentals-of-ds,
  waarvan ≥ 2 met `expect_abstain`.
- `python -m app.cli eval` draait in-process én via `--api`, schrijft JSON,
  en `--compare` toont een delta.
- `eval-seed` maakt een skelet uit een echte query-log.
- `pytest` groen; geen test raakt het netwerk.
