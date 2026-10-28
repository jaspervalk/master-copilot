"""Grens om de opzetcode die een taalmodel verzint.

De opzet draait automatisch, bij het genereren, zonder dat iemand hem leest.
Daarom mag hij weinig: alleen namen toekennen, alleen `np` en `pd` en een
handvol ingebouwde functies aanroepen, geen imports, geen attribuutketen naar
iets anders.

Jouw eigen uitdrukking wordt hier níet doorheen gehaald. Die typ je zelf op je
eigen machine; dat is een REPL, en er een hek omheen zetten zou theater zijn.
"""
from __future__ import annotations

import ast


ALLOWED_MODULES = ("np", "pd")
ALLOWED_BUILTINS = frozenset(
    {"range", "list", "tuple", "dict", "set", "len", "str", "int", "float", "bool", "sorted", "zip"}
)


class SetupRejected(ValueError):
    """De opzetcode doet iets wat een fixture niet hoort te doen."""


def _assigned_names(setup: str) -> set[str]:
    try:
        tree = ast.parse(setup or "", mode="exec")
    except (SyntaxError, ValueError):
        return set()
    return {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def giveaway_terms(reference_answer: str, setup: str = "") -> set[str]:
    """De woorden die het antwoord verraden als ze in de vraag staan.

    "Wat geeft `np.sort(x)` terug?" met antwoord `np.sort(x)` is geen oefening
    maar overtypen. De namen van de fixture (`x`, `df`) mogen wél in de vraag
    staan — die moet je juist noemen — dus die vallen af.
    """
    try:
        tree = ast.parse(reference_answer, mode="eval")
    except (SyntaxError, ValueError):
        return set()

    terms: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            terms.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            terms.add(node.arg)
        elif isinstance(node, ast.Name):
            terms.add(node.id)

    # `np` en `pd` zeggen niets weg: die staan in elke vraag over numpy.
    return {term for term in terms - _assigned_names(setup) if term not in ALLOWED_MODULES}


def computes_nothing(reference_answer: str) -> bool:
    """Is dit antwoord een kale naam of een letterlijke waarde?

    `x` als antwoord op "geef het aantal waarnemingen boven 0" terwijl de opzet
    `x = 18` zegt, is geen opgave: het staat er al. Hetzelfde voor `18`.
    """
    try:
        tree = ast.parse(reference_answer.strip(), mode="eval")
    except (SyntaxError, ValueError):
        return False
    body = tree.body
    if isinstance(body, ast.UnaryOp):  # -18 telt ook als letterlijk
        body = body.operand
    if isinstance(body, ast.Constant) and body.value is None:
        # `None` als antwoord wordt een regel verderop afgekeurd, met een
        # melding die uitlegt wat eraan mankeert: elk ander antwoord dat None
        # oplevert zou ook goed gerekend worden.
        return False
    return isinstance(body, (ast.Name, ast.Constant))


def _root_name(node: ast.AST) -> str | None:
    """De naam waar een keten op begint: np.arange(12).reshape(3, 4) → 'np'."""
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def validate_setup(setup: str) -> None:
    """Gooi SetupRejected als de opzet meer doet dan een fixture bouwen."""
    if not setup.strip():
        return
    try:
        tree = ast.parse(setup, mode="exec")
    except SyntaxError as exc:
        raise SetupRejected(f"geen geldige Python: {exc.msg}") from exc
    except ValueError:
        # Nulbyte in de bron; zie figures.validate_figure_code.
        raise SetupRejected("de opzetcode bevat een nulbyte") from None

    # Imports eerst, anders krijgt `import os` de melding "alleen toewijzingen"
    # en dat zegt niet waar het echt op vastloopt.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise SetupRejected("importeren mag niet; np en pd staan al klaar")

    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            raise SetupRejected(
                f"alleen toewijzingen zijn toegestaan, geen {type(statement).__name__.lower()}"
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise SetupRejected(f"'{node.attr}' mag niet")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise SetupRejected(f"'{node.id}' mag niet")
        if isinstance(node, ast.Call):
            root = _root_name(node.func)
            if root is None:
                raise SetupRejected("aanroep op iets wat geen naam is")
            if root in ALLOWED_MODULES:
                continue
            # Een aanroep op een naam die hierboven is toegekend (x2.reshape())
            # kan niet vooraf worden goedgekeurd, dus die eis is: het is een
            # methode op een lokale naam, geen los ingebouwd ding.
            if isinstance(node.func, ast.Attribute):
                continue
            if root not in ALLOWED_BUILTINS:
                raise SetupRejected(f"'{root}' aanroepen mag niet")
