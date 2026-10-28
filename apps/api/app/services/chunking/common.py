from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.services.parsing import normalize_text


TARGET_WORDS = 425
OVERLAP_WORDS = 75
SECTION_SEPARATOR = " › "

# Een genummerde kop is "5.3 Error Backpropagation": hooguit twee cijfers per
# niveau, en er volgt een lettwoord. Zonder die twee eisen slikt de regex ook
# "170 4. Classification" (een kopregel mét paginanummer), "0 20 40 60 80"
# (de asverdeling van een figuur) en "116117 116419" (een tabelrij).
_NUMBERED_HEADING_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\.?[\s:–-]+(?=[A-Za-z])")

# Een regel met een vergelijkingsteken is een formule, geen kop. Zonder deze
# uitzondering wordt "AIC =1" een sectiepad omdat het uit hoofdletters bestaat.
_FORMULA_CHARS = frozenset("=<>≤≥≠")


@dataclass
class ChunkDraft:
    chunk_index: int
    section_path: str | None
    page_start: int
    page_end: int
    token_count: int
    text: str
    normalized_text: str
    chunk_metadata: dict

    def to_payload(self) -> dict:
        return asdict(self)


def tokens(entry: str) -> list[str]:
    """De woorden van een regel tekst — of een codeblok in zijn geheel.

    Beide chunkers werken met losse woorden die ze met spaties weer aan elkaar
    zetten. Voor proza is dat prima; voor code verdwijnen zo de regeleinden en
    de inspringing. Een codeblok is daarom één ondeelbaar woord, met een
    regeleinde ervoor en erna zodat de fence op een eigen regel begint.

    Een codeblok is te herkennen aan een regeleinde: een genormaliseerde regel
    proza heeft er nooit een.

    Wat dit kost: de chunker telt zo'n blok als één woord, dus een fragment met
    veel code wordt groter dan het doel van 425 woorden. Een codecel in de
    aantekeningen is tien tot dertig regels; dat past ruim.
    """
    return [f"\n{entry}\n"] if "\n" in entry else entry.split()


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def heading_level(heading: str) -> int | None:
    """Diepte uit de nummering: '5' → 1, '5.3' → 2, '5.3.1' → 3. Geen nummer → None."""
    match = _NUMBERED_HEADING_RE.match(normalize_text(heading))
    if not match:
        return None
    return len(match.group(1).split("."))


MAX_HEADING_WORDS = 10
_NUMERIC_TOKEN_RE = re.compile(r"^[\d.,%()\[\]/-]+$")


def _mostly_numeric(tokens: list[str]) -> bool:
    if not tokens:
        return True
    numeric = sum(1 for token in tokens if _NUMERIC_TOKEN_RE.match(token))
    return numeric / len(tokens) > 0.4


def looks_like_heading(block: str) -> bool:
    """Streng, want een valse kop is duurder dan een gemiste.

    Elke valse kop knipt de tekst op een willekeurige plek in tweeën en zet er
    een onzinnige vindplaats boven. Een gemiste kop kost alleen precisie: de
    chunk erft dan de kopregel van de pagina, en die klopt meestal.
    """
    compact = normalize_text(block)
    words = compact.split()
    if not compact or len(words) > MAX_HEADING_WORDS:
        return False
    # Een kop eindigt niet op zinsleestekens. Zonder deze regel wordt "1998 was
    # een druk jaar." een kop, alleen omdat de zin met een getal begint.
    if compact.endswith((".", ",", ";", "?", "!")):
        return False
    # Vraagtekens en formules horen bij lopende tekst, niet bij een kop.
    if "?" in compact or "!" in compact or (_FORMULA_CHARS & set(compact)):
        return False
    # Een kop bevat een woord, geen losse letters of cijfers. Dit weert
    # "265-266", "AIC" en de asverdelingen van figuren.
    if not any(len(word) >= 3 and word.isalpha() for word in words):
        return False

    numbering = _NUMBERED_HEADING_RE.match(compact)
    if numbering:
        rest = compact[numbering.end() :].strip()
        # "2 NaN 4.0 6.0 6.0" is een tabelrij, geen sectie; en een punt midden
        # in de rest verraadt een gewone zin die toevallig genummerd begint.
        return bool(rest) and "." not in rest and not _mostly_numeric(rest.split())

    # De regel "eindigt op een dubbele punt is een kop" is bewust weg: in een
    # statistiekboek eindigt élke aanloop naar een formule zo, en dat leverde
    # een kwart van alle sectiepaden op.
    #
    # De hoofdletterregel geldt pas vanaf vier tekens en verdraagt geen cijfers:
    # "INTRODUCTION" is een kop, "PRCP -665 62" en "LSTM RNN,426" zijn een
    # tabelrij en een indexregel.
    if len(compact) < 4 or any(char.isdigit() for char in compact):
        return False
    letters = sum(1 for char in compact if char.isalpha())
    uppercase = sum(1 for char in compact if char.isupper())
    return letters > 0 and uppercase / letters > 0.7


def join_sections(stack: list[str]) -> str | None:
    return SECTION_SEPARATOR.join(stack) if stack else None


def push_heading(stack: list[str], heading: str) -> list[str]:
    """Plaats een kop op de juiste diepte in de stapel.

    Een genummerde kop vervangt alles op zijn eigen diepte en dieper; een kop
    zonder nummer vervangt alleen de laatste ongenummerde laag. Zonder dit
    onderscheid zou '5.4' de '5' van zijn eigen hoofdstuk wegduwen.
    """
    level = heading_level(heading)
    if level is None:
        return [*stack[:-1], heading] if stack else [heading]
    return [*stack[: level - 1], heading]
