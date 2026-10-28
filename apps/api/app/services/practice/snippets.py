"""Codefragmenten uitvoeren, en een voorspelde uitvoer nakijken.

Het tentamen van SSO deel 2 kan een fragment laten zien en vragen wat het
print. Het goede antwoord komt hier niet van een model maar van het uitvoeren:
wat het fragment print, ís de sleutel. Dezelfde afspraak als bij de
oefenkaarten met code — het model stelt voor, de interpreter beslist.

Twee controles die bij het uitvoeren horen:

* **Twee keer draaien.** Verschilt de uitvoer, dan hangt hij af van toeval of
  tijd, en dan kun je hem niet voorspellen. Dan is het ook geen vraag. Dit vangt
  meteen een solver die zijn log naar het scherm schrijft (met tijden erin).
* **Een grens om de code**, net als om de opzetcode van een oefenkaart: het
  fragment komt van een model en draait zonder dat iemand het leest. Alleen de
  bibliotheken van de cursus, geen bestanden, geen processen. Geen
  beveiligingslaag — een lokale tool voor één gebruiker — wel een grens tegen
  ongelukken.

Het nakijken is mild waar de docent mild is. Bij college 8 zei hij over
schrijven: een vergeten komma, maak je geen zorgen. Bij voorspellen betekent
dat: 4 of 4.0, enkele of dubbele aanhalingstekens, een spatie meer — telt
niet. Een ander getal, een ander woord of een regel te weinig telt wél.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import textwrap


class SnippetRejected(ValueError):
    """Dit fragment is geen bruikbare vraag."""


# De bibliotheken van de cursus, plus de standaardmodules die een voorbeeld
# redelijkerwijs nodig heeft.
ALLOWED_IMPORTS = frozenset(
    {
        "pulp", "numpy", "scipy", "math", "random", "itertools", "collections",
        "statistics", "functools", "heapq", "operator", "fractions", "decimal",
        "string", "dataclasses", "typing",
    }
)
FORBIDDEN_CALLS = frozenset({"open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals", "locals", "vars"})

TIMEOUT_SECONDS = 20

# Een uitvoer die je met de hand moet voorspellen, is kort. Een dataframe van
# veertig regels is geen tentamenvraag.
MAX_OUTPUT_LINES = 12
MAX_OUTPUT_CHARS = 500


def pulp_available() -> bool:
    try:
        import pulp  # noqa: F401
    except ImportError:
        return False
    return True


def validate_snippet(code: str) -> None:
    """Weiger wat een fragment voor een tentamenvraag niet nodig heeft."""
    try:
        tree = ast.parse(code or "", mode="exec")
    except SyntaxError as exc:
        raise SnippetRejected(f"het fragment is geen geldige Python ({exc.msg}, regel {exc.lineno})") from None
    except ValueError:
        # Nulbyte in de bron; zie figures.validate_figure_code.
        raise SnippetRejected("het fragment bevat een nulbyte") from None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                wortel = alias.name.split(".")[0]
                if wortel not in ALLOWED_IMPORTS:
                    raise SnippetRejected(f"'import {alias.name}' mag niet; alleen {', '.join(sorted(ALLOWED_IMPORTS))}")
        elif isinstance(node, ast.ImportFrom):
            wortel = (node.module or "").split(".")[0]
            if wortel not in ALLOWED_IMPORTS:
                raise SnippetRejected(f"'from {node.module} import …' mag niet")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            raise SnippetRejected(f"'{node.func.id}(…)' mag niet in een fragment")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_CALLS:
            raise SnippetRejected(f"'{node.id}' mag niet in een fragment")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            raise SnippetRejected(f"'{node.attr}' mag niet in een fragment")


# Waarmee de harness op stderr meldt hoe groot de opgeloste modellen waren.
# Stderr, want stdout is precies wat de student moet voorspellen.
_SIZES_MARKER = "__OPGELOSTE_MODELLEN__"

# Draait in een eigen proces. `getSolver("COIN_CMD")` — zo staat het in de
# aantekeningen — vraagt een losse cbc die hier niet is; de meegeleverde
# PULP_CBC_CMD is dezelfde solver. Die wordt dan gebruikt, zodat code uit de
# stof draait zoals hij in de stof staat.
#
# `LpProblem.solve` telt mee hoeveel variabelen elk opgelost model heeft. Dat
# is de eerlijke maat voor "kun je dit met de hand": `LpVariable.dicts` over
# een lijst is in de code één regel en in het model zoveel variabelen als de
# lijst lang is.
_HARNESS = """
import json
import sys

_groottes = []
try:
    import pulp

    _orig = pulp.getSolver

    def _get(name, *args, **kwargs):
        if name == "COIN_CMD":
            name = "PULP_CBC_CMD"
        kwargs.setdefault("msg", False)
        return _orig(name, *args, **kwargs)

    pulp.getSolver = _get
    pulp.COIN_CMD = pulp.PULP_CBC_CMD

    _orig_solve = pulp.LpProblem.solve

    def _solve(self, *args, **kwargs):
        _groottes.append(len(self.variables()))
        return _orig_solve(self, *args, **kwargs)

    pulp.LpProblem.solve = _solve
except Exception:
    pass

code = sys.stdin.read()
exec(compile(code, "<fragment>", "exec"), {"__name__": "__main__"})
print("__OPGELOSTE_MODELLEN__" + json.dumps(_groottes), file=sys.stderr)
"""


def _run_once(code: str, timeout: int) -> tuple[str, list[int]]:
    try:
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(_HARNESS)],
            input=code,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise SnippetRejected("het fragment draaide te lang") from None
    if result.returncode != 0:
        laatste = [line for line in (result.stderr or "").strip().splitlines() if line.strip()]
        raise SnippetRejected(f"het fragment geeft een fout: {laatste[-1] if laatste else 'onbekend'}")

    groottes: list[int] = []
    for line in (result.stderr or "").splitlines():
        # rpartition: schreef het fragment zelf zonder regeleinde naar stderr,
        # dan plakt de melding aan die tekst vast.
        if _SIZES_MARKER in line:
            groottes = json.loads(line.rpartition(_SIZES_MARKER)[2])
    uitvoer = "\n".join(line.rstrip() for line in (result.stdout or "").strip("\n").splitlines())
    return uitvoer, groottes


def run_snippet_measured(code: str, *, timeout: int | None = None) -> tuple[str, list[int]]:
    """Wat dit fragment print, plus hoeveel variabelen elk opgelost model had.

    Lost het fragment niets op, dan is de lijst leeg.
    """
    validate_snippet(code)
    wacht = timeout or TIMEOUT_SECONDS
    eerste, groottes = _run_once(code, wacht)
    if not eerste.strip():
        raise SnippetRejected("het fragment print niets")
    tweede, _ = _run_once(code, wacht)
    if eerste != tweede:
        raise SnippetRejected("de uitvoer verschilt per keer draaien, dus die valt niet te voorspellen")
    return eerste, groottes


def run_snippet(code: str, *, timeout: int | None = None) -> str:
    """Wat dit fragment print, of een `SnippetRejected` met de reden."""
    return run_snippet_measured(code, timeout=timeout)[0]


def output_problem(output: str) -> str | None:
    """Is dit een uitvoer die je met de hand kunt voorspellen?"""
    regels = output.splitlines()
    if len(regels) > MAX_OUTPUT_LINES:
        return f"de uitvoer is {len(regels)} regels; met de hand voorspelbaar is hooguit {MAX_OUTPUT_LINES}"
    if len(output) > MAX_OUTPUT_CHARS:
        return "de uitvoer is te lang om met de hand te voorspellen"
    return None


# --- nakijken -----------------------------------------------------------------

_TOKEN_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|'[^'\n]*'|\"[^\"\n]*\"|[A-Za-z_]\w*|\S")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$")


def _tokens(line: str) -> list[str]:
    return _TOKEN_RE.findall(line)


def _same_number(expected: str, given: str) -> bool:
    """Het verwachte getal, zoals de student het opschreef.

    Met decimalen: goed als het op dat aantal decimalen klopt (3.33 voor
    3.3333). Zonder decimalen: alleen goed als het verwachte getal geheel is —
    '4' voor 4.0 wel, '3' voor 3.33 niet.
    """
    a, b = float(expected), float(given)
    if "e" in given.lower():
        return abs(a - b) <= 1e-9 * max(1.0, abs(a))
    decimalen = len(given.split(".")[1]) if "." in given else 0
    if decimalen == 0:
        return a == round(a) and a == b
    return abs(a - b) <= 0.5 * 10 ** (-decimalen) + 1e-12


def _same_token(expected: str, given: str) -> bool:
    if _NUMBER_RE.match(expected) and _NUMBER_RE.match(given):
        return _same_number(expected, given)
    if expected[:1] in "'\"" and given[:1] in "'\"":
        return expected[1:-1] == given[1:-1]
    return expected == given


def outputs_match(expected: str, given: str) -> bool:
    """Klopt de voorspelde uitvoer met de echte?"""
    verwacht = [line for line in expected.strip().splitlines() if line.strip()]
    gegeven = [line for line in given.strip().splitlines() if line.strip()]
    if not gegeven or len(verwacht) != len(gegeven):
        return False
    for links, rechts in zip(verwacht, gegeven):
        a, b = _tokens(links), _tokens(rechts)
        if len(a) != len(b) or not all(_same_token(x, y) for x, y in zip(a, b)):
            return False
    return True
