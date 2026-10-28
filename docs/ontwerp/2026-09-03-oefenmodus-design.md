# Oefenmodus — Design (Fase 3, eerste plak)

Datum: 2026-09-03. Bouwt op fase 1 (corpus, retrieval), 2 (coach) en 4
(eval-harness). Vervangt "tentamentrainer" uit het fase-1-ontwerp door iets
concreters.

## 1. Waarom

Het corpus beantwoordt vragen over NumPy en pandas al goed:

```
> slicing van een tweedimensionale numpy array
  0.557 p64  Chapter 2 › The Basics of NumPy Arrays › Array Slicing: Accessing Subarrays
> verschil tussen loc en iloc
  0.580 p128 Chapter 3 › Data Indexing and Selection › Data Selection in Series
```

Als naslagwerk is het klaar. Maar syntaxis leer je niet door hem op te zoeken;
je leert hem door hem te produceren met het boek dicht. Dat is wat ontbreekt.

Twee soorten kaarten, in deze volgorde gebouwd:

| soort | vraag | nakijken |
|---|---|---|
| **code** (nu) | "Gegeven `x2` van 3×4 — het gemiddelde per kolom" | uitvoeren en uitkomsten vergelijken |
| **concept** (later) | "Wanneer `loc` en wanneer `iloc`?" | model toetst aan het materiaal |

De nakijklaag is daarom verwisselbaar ontworpen: `check(card, answer) ->
CheckResult`, met nu één implementatie en later een tweede.

## 2. Beslissingen

### 2.1 Kaarten blijven bestaan, per sectie

Genereren is een aparte handeling, oefenen is gratis. Een deck hoort bij één
sectiepad — en die zijn sinds de chunkingfix bruikbaar:
`Chapter 2. Introduction to NumPy › The Basics of NumPy Arrays › Array
Slicing: Accessing Subarrays`. Dat is precies de eenheid waarin een boek zelf
is ingedeeld, dus ook de eenheid waarin je oefent.

Stabiele kaart-identiteit is bovendien de voorwaarde voor herhaling-in-de-tijd
(een latere plak): zonder vaste kaarten valt er niets te plannen.

Een slechte kaart kun je weggooien (`disabled`), niet stilzwijgend overslaan.

### 2.2 Uitvoeren is de scheidsrechter, niet een model

Een codekaart bestaat uit **opzet** (`x2 = np.arange(12).reshape(3, 4)`), een
**vraag** en een **referentie-uitdrukking** (`x2.mean(axis=0)`). Nakijken:
draai de opzet, evalueer de referentie én jouw uitdrukking in dezelfde
naamruimte, vergelijk de twee waarden.

Dat lost het meerdere-goede-antwoorden-probleem op: `x2.mean(axis=0)` en
`np.mean(x2, axis=0)` leveren dezelfde array, dus allebei goed. Een model dat
tekst vergelijkt zou hierover moeten oordelen; de interpreter weet het.

Vergelijken gebeurt op waarde, niet op tekst: `np.array_equal` voor arrays
(met `allclose` voor floats), `.equals` voor pandas-objecten, `==` voor de
rest.

### 2.3 De generator controleert zichzelf

Het model verzint kaarten; die worden **direct uitgevoerd** voordat ze worden
opgeslagen. Draait de opzet niet, of levert de referentie-uitdrukking een
fout, dan gaat de kaart weg vóór jij hem ziet. Een gehallucineerd antwoord
lekt zo niet je oefenset in — dezelfde redenering als de evalset: twintig
kaarten die kloppen verslaan tweehonderd die niemand heeft gezien.

Het rapport na genereren noemt hoeveel kaarten zijn afgekeurd en waarom.

### 2.4 De opzetcode wordt gecontroleerd, jouw uitdrukking niet

De opzet komt van een taalmodel en draait **automatisch**, zonder dat jij hem
leest. Daar hoort een grens omheen: de opzet wordt met `ast` gecontroleerd —
alleen toewijzingen, alleen aanroepen op `np` en `pd` en een handvol
ingebouwde functies, geen imports, geen attribuutketen buiten die twee. Wat
daar niet in past wordt afgekeurd als kaart.

Jouw uitdrukking wordt **niet** gecontroleerd. Die typ je zelf, op je eigen
machine, in je eigen venv — dat is een REPL, en doen alsof het een sandbox is
zou theater zijn. Wat er wel omheen staat: een subprocess met een timeout van
vijf seconden, zodat een oneindige lus de app niet vasthoudt.

Dit is expliciet geen beveiligingsgrens. Het is een lokale tool voor één
gebruiker; de code die draait is code die jij of jouw model schreef.

### 2.5 Een eigen pagina

`/oefenen`, naast Vragen en Corpus. Een drilronde is geen gesprek: je wil een
vraag, een invoerveld, een oordeel en meteen de volgende. Dat past niet in de
chat-UI en zou hem ook vertroebelen.

## 3. Datamodel

```python
class PracticeCard(Base):
    id: str                      # uuid
    course_slug: str             # index
    document_id: str             # waar hij vandaan komt
    chunk_id: str                # de chunk die het bewijs is
    section_path: str | None     # het deck waar hij bij hoort (index)
    page_start: int
    page_end: int
    kind: str                    # "code" | "concept"
    setup: str                   # code die de fixture bouwt ("" bij concept)
    question: str
    reference_answer: str        # uitdrukking (code) of modelantwoord (concept)
    disabled: bool = False       # weggegooid door de gebruiker
    created_at: datetime

class PracticeAttempt(Base):
    id: str
    card_id: str                 # index
    given_answer: str
    correct: bool
    detail: str                  # verwachte en gegeven waarde, of de foutmelding
    created_at: datetime         # index
```

Pogingen worden vastgelegd om drie redenen: je ziet wat je fout deed, een
latere plak kan er herhaling op plannen, en het is meetbaar of de kaarten
deugen (een kaart die iedereen fout heeft is waarschijnlijk zelf fout).

## 4. Onderdelen

```
apps/api/app/services/practice/sandbox.py    uitvoeren en vergelijken
apps/api/app/services/practice/validation.py ast-controle op de opzetcode
apps/api/app/services/practice/generation.py chunks → kaarten, zelfcontrolerend
apps/api/app/services/practice/checking.py   check(card, answer) -> CheckResult
apps/api/app/services/practice/decks.py      decks tellen, kaarten opvragen
apps/api/app/models.py                       PracticeCard, PracticeAttempt
apps/api/app/schemas.py                      de bijbehorende schema's
apps/api/app/api/routes/practice.py          de endpoints
apps/web/app/oefenen/page.tsx                de pagina
apps/web/components/practice/*               deck-keuze en drilronde
```

`sandbox.py` weet niets van kaarten; `checking.py` weet niets van subprocessen.
Zo is de tweede nakijklaag (concept, via een model) straks een tweede
implementatie naast `checking.check_code`, zonder de rest aan te raken.

## 5. API

| endpoint | doet |
|---|---|
| `GET /api/practice/decks?course_slug=` | sectiepaden met kaartaantallen |
| `POST /api/practice/decks/generate` | `{course_slug, section_path, count}` → nieuwe kaarten + afkeurrapport |
| `GET /api/practice/cards?course_slug=&section_path=` | de kaarten van een deck |
| `POST /api/practice/cards/{id}/attempt` | `{answer}` → oordeel + bron |
| `DELETE /api/practice/cards/{id}` | zet `disabled` (weggooien, niet wissen) |

Genereren gebruikt de bestaande retrieval met een `section_path`-filter, zodat
de kaarten uit precies die sectie komen. De chunks van die sectie worden
letterlijk aan het model gegeven; het mag alleen vragen maken over wat er
staat.

## 6. Fouten

- Opzetcode die de ast-controle niet haalt: kaart afgekeurd, reden in het
  rapport.
- Referentie-uitdrukking die faalt of niets teruggeeft: kaart afgekeurd.
- Jouw uitdrukking faalt: geen crash, maar "fout" met de foutmelding erbij —
  een `SyntaxError` lezen hoort bij het leren.
- Timeout: "fout", met de melding dat het te lang duurde.
- Een deck zonder kaarten: de UI zegt dat, en biedt genereren aan.

## 7. Testen

- `sandbox`: uitvoeren van een geldige opzet + uitdrukking; gelijkwaardige
  maar verschillend geschreven antwoorden zijn gelijk; floats via `allclose`;
  pandas via `.equals`; een fout in de kandidaat geeft `correct=False` met de
  melding; een timeout stopt.
- `validation`: `np.arange(12).reshape(3,4)` mag; `import os`,
  `__import__("os")`, `open("x")` en een aanroep buiten `np`/`pd` niet.
- `generation`: met een nepmodel dat één goede en één kapotte kaart oplevert
  blijft er precies één over, met de reden van afkeuring in het rapport.
- `checking`: het contract `check(card, answer) -> CheckResult`.
- API: genereren, opvragen, een poging doen, een kaart weggooien.
- Geen test raakt OpenAI; het subprocess draait wel echt — dat is de kern.

## 8. Wat dit niet doet

Geen herhaling-in-de-tijd (volgende plak). Geen begripsvragen (die komen na
de audit van deze). Geen notebooks uitvoeren, geen meerregelige oplossingen —
een kaart vraagt om één uitdrukking. Geen beveiligingssandbox.

## 9. Definitie van klaar

- `POST /api/practice/decks/generate` maakt uit "Chapter 2 › Array Slicing"
  tien kaarten waarvan de referentie-antwoorden aantoonbaar draaien.
- `x2.mean(axis=0)` en `np.mean(x2, axis=0)` worden allebei goed gerekend.
- Een fout getypte uitdrukking geeft de foutmelding terug, geen crash.
- Een kaart weggooien haalt hem uit de ronde.
- `/oefenen` draait een ronde van begin tot eind met de bron erbij.
- `pytest` groen, `tsc --noEmit` schoon.
