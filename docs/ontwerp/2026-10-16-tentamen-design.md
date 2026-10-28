# Tentamen — alles voor de voorbereiding op één pagina

16 oktober 2026. FDS-tentamen woensdag 21 oktober, SSO vrijdag 23 oktober.

## Waarom

Wat je voor een tentamen nodig hebt, staat nu verspreid. De opbouw zit in
`exams/opbouw.yml`, de oefententamens staan op `/oefenen`, de tentameninformatie
is een notitie in het corpus, en wat de oude tentamens gemeen hebben staat
nergens. De wens: één tab, *Tentamen*, met alles om zo hoog mogelijk te
scoren:

- de oefententamens;
- de patronen die sowieso terugkomen;
- vragen die je uit de colleges en Canvas kunt voorspellen;
- de manieren om punten te halen.

## Keuze: nu met de hand analyseren, later genereren (aanpak C)

De analyse (patronen, voorspelde vragen, tactieken) komt per vak in
`corpus/<vak>/exams/voorbereiding.yml`. Dit keer wordt dat bestand met de hand
gevuld uit de oude tentamens, college 13 en Canvas. Later kan een generator
hetzelfde formaat vullen. De pagina hangt alleen van het formaat af.

Mechanisch blijft wel: **elke bewering draagt een bron**, dat wil zeggen een
pad met een letterlijk citaat, of een Canvas-aankondiging met een citaat. De
server loopt die bronnen bij elke aanvraag na tegen de geïndexeerde tekst. Dat
gebeurt met dezelfde `squash` als de citaatcontrole van de generator. Een bron
die niet terug te vinden is, wordt op de pagina gemarkeerd en niet verborgen.
Zo zie je het als een bewering nergens op steunt, ook nadat het materiaal is
veranderd.

## Wat de pagina toont (per vak, met vakkeuze zoals de andere consoles)

1. **Het tentamen in één blik.** Datum en dagen te gaan (`horizon.next_exam`),
   duur, hulpmiddelen en praktische feiten (uit `voorbereiding.yml`), de opbouw
   per groep, en minuten per punt (duur gedeeld door `total_points`).
2. **Waar liggen je punten.** Per groep van de opbouw: wat hij waard is op het
   tentamen, wat je haalde bij je laatste poging op de tentamenkaarten van die
   groep, en wat er dus nog te winnen valt. Gesorteerd op dat laatste.
   - Een kaart hoort bij een groep via zijn vraag-id in `examples`, anders via
     de titel van zijn sectie.
   - Zo tellen het proeftentamen (vijf secties) en de oude oefententamens mee
     met de zes groepen van 2026.
   - Een groep zonder pogingen staat er als "nog niet geoefend", met zijn volle
     waarde.
3. **Oefententamens**: de bestaande voortgang (`exam_progress`), met een link
   naar `/oefenen?course=…&exam=…`.
4. **Wat zeker terugkomt**: patronen, met eventueel "4 van 4 tentamens" en hun
   groep.
5. **Voorspelde vragen**: vraag, waarom we denken dat hij komt, en het
   modelantwoord achter een klik (eerst zelf proberen).
6. **Zo haal je de punten**: tactieken.

## Bestand `voorbereiding.yml`

```yaml
exam: {duration_minutes, aids: [...], notes: [...]}
patterns:    [{id, title, detail, group?, seen?, of?, sources}]
predictions: [{id, group?, points?, question, answer, why, sources}]
tactics:     [{id, title, detail, sources}]
# source: {path, page?, quote} of {announcement, quote}
```

Het bestand wordt bij het laden nagelopen, en de problemen gaan mee in het
antwoord. Nagelopen wordt:

- onbekende sleutels;
- dubbele ids;
- een groep die niet in de opbouw staat;
- `seen` groter dan `of`;
- een item zonder bron.

Het bestand staat in `exams/`, maar is geen transcriptie. `transcription_paths`
slaat het over, net als `opbouw.yml`.

## College 13 van FDS

Bijna alle voorbeeldvragen in college 13 zijn schermafbeeldingen van het
proeftentamen. Er zijn zes nieuwe:

- drie meerkeuzevragen: regularization, precision en overfitting;
- drie formule- of tekenvragen: OLS, logistische likelihood en een scree plot.

Die zes komen als transcriptie `exams/voorbeelden-college-13.yml` en worden
daarmee kaarten. Ze gaan niet op de weekkaart: daar zou je ze lezen met het
antwoord ernaast.

`course_blueprint` kiest vanaf nu de transcriptie met de meeste punten. Tot nu
toe koos hij de eerste op naam, en een korte set voorbeeldvragen zou dan het
model voor elk oefententamen worden.

## Backend

- `services/study/exam_prep.py`: `load_prep`, `check_sources`, `standings`,
  `build_exam_prep`.
- `GET /api/exam-prep?course_slug=` levert `ExamPrepRead`.
- Zonder `voorbereiding.yml` werkt de pagina ook. Je ziet dan alleen de
  berekende blokken (één blik, punten, oefententamens).

## Frontend

- `/tentamen`, in de navigatiebalk tussen Oefenen en Bronnen.
- `components/exam/exam-console.tsx`, met de blokken als losse componenten.
- Diepe link `?course=`.
- De tentamenkaart op `/agenda` linkt naar de pagina.

## Tests

- **Laden en nalopen**: geldig bestand, onbekende groep, dubbele id, item
  zonder bron.
- **Bronnen**:
  - een citaat dat in een chunk staat is nagelopen;
  - een citaat met een verkeerde pagina niet;
  - een aankondiging wel.
- **Punten per groep**:
  - mapping via `examples` en via de titel;
  - de laatste poging telt;
  - een groep zonder pogingen.
- **Bestandsbeheer**: `transcription_paths` slaat `voorbereiding.yml` over, en
  `course_blueprint` kiest de grootste transcriptie.
- **Route**: met en zonder bestand.

## Buiten deze ronde

- Een generator die `voorbereiding.yml` vult (aanpak B).
- Een voorspelde vraag als kaart oefenen.
- Docentsignalen automatisch uit de slides halen.
