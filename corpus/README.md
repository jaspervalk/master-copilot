# De mapstructuur van je corpus

Het pad van een bestand is de enige bron van metadata. Er is geen aparte
administratie: waar je een bestand neerzet, bepaalt bij welk vak, welke week en
welk soort het hoort.

```
corpus/
  <vak-slug>/                     kleine letters, cijfers, koppeltekens
    course.yml                    optioneel
    books/                        tekstboeken
    papers/                       losse artikelen
    slides/week-03/               collegeslides
    assignments/week-03/          beoordeelde opdrachten die je inlevert
    exercises/week-03/            oefenopgaven die je niet inlevert
    submissions/week-03/          jouw ingeleverde uitwerkingen
    solutions/week-03/            officiële uitwerkingen
    notes/                        eigen aantekeningen
```

## Regels

- **Vaknaam**: kleine letters, cijfers en koppeltekens (`statistical-learning`).
- **Mapnaam**: precies een van `books, papers, slides, assignments, exercises,
  submissions, solutions, notes`. Een andere naam wordt bij `sync` geweigerd met een
  foutmelding — nooit stil op een default gezet, want een verkeerd gelabeld
  document verpest je zoekresultaten zonder dat je het merkt.
- **Week**: een submap `week-NN` (twee cijfers). Staat die er niet, dan wordt een
  `week-NN` of `wNN` in de bestandsnaam gebruikt. Boeken en papers hoeven geen
  week te hebben.
- **Diepte**: `<vak>/<map>/<bestand>` of `<vak>/<map>/week-NN/<bestand>`. Dieper
  nesten wordt geweigerd.
- **Bestandstypen**: `.pdf`, `.pptx`, `.md` en `.ipynb`. De rest wordt genegeerd, net als
  een `README.md`. In markdown zijn de koppen de structuur: bij opgaven en
  quizzen is elke kop een eigen opgave.

## Opdrachtstatus

Een opdracht in `assignments/week-03/` geldt als **ingeleverd** zodra er iets in
`submissions/week-03/` van hetzelfde vak staat. Anders is hij **open**. Je hoeft
dus niets bij te houden: zet je uitwerking neer en de status volgt.

Een opdracht is **gesloten** zodra de deadline uit `course.yml` is verstreken,
ook zonder inzending — bij groepswerk levert een teamgenoot in. Oefenopgaven
(`exercises/`) hebben geen status.

Zolang een beoordeelde opdracht open staat, komen `solutions/` en
`submissions/` van die week in geen enkel antwoord terug. Uitwerkingen van
oefenopgaven worden nooit verborgen.

## course.yml

Optioneel. De naamvelden zijn voor de weergave; `assignments` bepaalt wanneer
een opdracht dichtgaat.

```yaml
name: Statistical Learning
period: 2026-1
lecturer: ...
canvas_id: 12345           # canvas.<jouw-uni>.nl/courses/12345 — koppelt de agenda

study:                     # hoe dit vak getoetst wordt
  code: read               # none: geen code · read: fragment lezen, uitvoer voorspellen
  # Eén zin: waarvoor je leert. De generators schrijven hun vragen en
  # voorbeelden daarvoor; zonder staat er "het tentamen van dit vak".
  assessment: het schriftelijke tentamen, twee uur zonder boek, meerkeuze en open vragen

exams:                     # tentamens die Canvas niet als opdracht kent
  - name: Tentamen
    date: 2026-10-21

assignments:
  - name: Assignment 1     # dezelfde naam als in Canvas: daarop vergelijkt de agenda
    week: 3                # de map assignments/week-03/
    due_date: 2026-09-21   # of: deadline
    available_date: 2026-09-09
    points: 10

weeks:
  - week: 2
    lectures: [3, 4]       # wijst lecture3.pdf en lecture4.pdf uit Canvas aan week 2 toe
    topics: [...]
    reading: [...]
```

Zonder dit bestand wordt de vaknaam afgeleid uit de slug.

**Canvas overschrijft dit bestand nooit.** Zegt Canvas iets anders over een
deadline of tentamendatum, dan staat dat als melding op `/agenda`; de deadline
hier stuurt de spoilerfilter, en die verandert alleen als jij hem aanpast.

**`week` is de koppeling.** Het verwijst naar de map waar het opgavenblad
staat, niet naar de week waarin het af moet. Staat Assignment 1 in
`assignments/week-03/`, dan hoort er `week: 3`. Klopt dat getal niet, dan
vindt de statusberekening de deadline niet en blijft de opdracht `open`.

Een regel zonder `week` én zonder datum is een aantekening voor jezelf — een
tentamendatum bijvoorbeeld — en wordt overgeslagen. Alles wat wél half is
ingevuld komt als regel in het `sync`-rapport te staan en zet de exitcode op
1; een deadline die stil wegvalt zou een uitwerking te vroeg vrijgeven.

## Prullenbak

`corpus/.trash/` bevat bestanden die je via de corpuspagina hebt verwijderd. Die
map wordt bij het scannen overgeslagen, dus wat daar staat komt niet terug in de
index. Je kunt er handmatig uit terugzetten.

## Bijwerken

```bash
python -m app.cli sync            # nieuw en gewijzigd materiaal indexeren
python -m app.cli sync --dry-run  # eerst kijken wat er zou gebeuren
```

Materiaal dat op Canvas verschijnt staat op `/agenda` onder "Nieuw op Canvas",
met een voorgestelde plek in deze mapstructuur. *Haal op* zet het daar neer en
indexeert het, via dezelfde weg als uploaden.
