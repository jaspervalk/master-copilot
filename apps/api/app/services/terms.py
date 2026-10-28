"""Vaktermen in Nederlandse tekst.

Wat de app zelf schrijft is Nederlands; de stof is grotendeels Engels. Met
alleen "schrijf in het Nederlands" vertaalde het model de vaktermen mee: de
weekkaart van FDS week 4 sprak van "ongesuperviseerd leren" en "ongecontroleerd
leren", terwijl college, boek en tentamen "unsupervised learning" zeggen. Een
term die je op het tentamen niet terugziet, leer je voor niets.

Eén regel voor elke generator die Nederlands schrijft, zodat ze niet uiteen
gaan lopen; tests/test_keep_terms.py houdt bij dat hij overal staat.
"""

import re
from typing import Any

KEEP_TERMS = (
    "Vertaal geen vaktermen: een begrip heet zoals de stof het noemt, meestal Engels, "
    "ook midden in een Nederlandse zin. Dus 'unsupervised learning', niet 'ongesuperviseerd "
    "leren' of 'ongecontroleerd leren'; 'dimensionality reduction', niet 'dimensiereductie'. "
    "Alleen de zinnen eromheen zijn Nederlands."
)


# De regel alleen hield het niet tegen: na de regel stond in dezelfde weekkaart
# nog "dezelfde ongesuperviseerde ideeën". Deze lijst zet de vertalingen terug
# die echt voorkwamen, in Python en dus zonder tweede aanroep; hij is niet
# volledig en hoeft dat niet te zijn, de instructie dekt de rest. Volgorde
# telt: "ongesuperviseerd leren" moet weg zijn voordat "gesuperviseerd" kijkt.
# "gecontroleerd" telt alleen vóór "leren": een gecontroleerd experiment is
# gewoon Nederlands.
_CALQUES = [
    (re.compile(pattern, re.IGNORECASE), english)
    for pattern, english in (
        (r"\b(?:niet-|on)ge(?:superviseerd|controleerd)e? leren\b", "unsupervised learning"),
        (r"\bge(?:superviseerd|controleerd)e? leren\b", "supervised learning"),
        (r"\b(?:niet-|on)gesuperviseerde?\b", "unsupervised"),
        (r"\bgesuperviseerde?\b", "supervised"),
        (r"\bdimensi(?:e|onaliteits)reductie\b", "dimensionality reduction"),
    )
]


def keep_terms(text: str) -> str:
    """Zet bekende vertalingen van vaktermen terug naar de Engelse term."""
    for pattern, english in _CALQUES:
        text = pattern.sub(
            lambda match: english[0].upper() + english[1:] if match.group(0)[0].isupper() else english,
            text,
        )
    return text


def keep_terms_in(value: Any) -> Any:
    """`keep_terms` op elke tekst in een structuur van dicts en lijsten."""
    if isinstance(value, str):
        return keep_terms(value)
    if isinstance(value, list):
        return [keep_terms_in(item) for item in value]
    if isinstance(value, dict):
        return {key: keep_terms_in(item) for key, item in value.items()}
    return value
