# Evalset

`cases.yml` is de meetlat voor retrieval. Elke case is een vraag met de
pagina's waar het antwoord in het materiaal staat.

## Regels

- **Verwachtingen wijzen naar `source_path` + paginabereik**, nooit naar een
  chunk-id. Chunk-ids veranderen bij elke herindexering.
- **De verwachting komt uit de inhoudsopgave**, niet uit wat retrieval
  teruggaf. Kijk in het boek; neem het bereik van de sectie over.
- **`unverified: true` betekent: nog niet nagekeken.** Zulke cases draaien
  niet mee. `eval-seed` maakt ze aan; jij haalt het veld weg.
- Meerdere `expected`-items: elk ervan telt als treffer.
- `expect_abstain: true`: er hoort niets relevants te zijn. Gebruik
  onderwerpen die aantoonbaar niet in het corpus zitten.
- `must_mention`: letterlijke woorden die in het antwoord moeten staan;
  alleen gebruikt met `--answers`.
- `must_not_mention`: woorden die er níet in mogen staan — het eindantwoord
  van een opdracht. Meet of de coach dichthoudt; alleen met `--answers`.
- `coach: {document: <source_path>, reveal: false}`: stel de vraag in
  coachmodus op die opdracht. Het pad wordt per run naar een id vertaald.

## Draaien

```bash
PYTHONPATH=apps/api python -m app.cli eval                       # in-process
PYTHONPATH=apps/api python -m app.cli eval --api http://localhost:8000
PYTHONPATH=apps/api python -m app.cli eval --compare data/eval/runs/<run>.json
PYTHONPATH=apps/api python -m app.cli eval --answers             # ook het model
PYTHONPATH=apps/api python -m app.cli eval-seed >> eval/cases.yml
```

Runs staan in `data/eval/runs/` (niet in git). Bewaar de run van vóór een
retrievalwijziging en zet de nieuwe ertegen af met `--compare`.
