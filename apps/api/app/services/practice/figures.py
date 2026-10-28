"""Een figuur is code die draait, net als een referentieantwoord.

Waarom zo. Een model kan een plaatje overtuigend *beschrijven* zonder dat het
klopt, en een plaatje dat niet klopt is erger dan geen plaatje — je onthoudt
het beeld. Daarom levert het model geen beschrijving maar matplotlib-code, die
hier wordt uitgevoerd. Komt er geen tekening uit, dan is er geen figuur.

Dezelfde grens als om de opzetcode van een oefenkaart: de code komt van een
model en draait zonder dat iemand hem leest, dus geen imports, geen bestanden,
en alleen aanroepen op `ax`, `np` en `stats`. Dit is geen beveiligingslaag —
het is een lokale tool voor één gebruiker — maar wel een grens tegen ongelukken.

Zonder matplotlib werkt alles gewoon door; er komen dan alleen geen figuren.
"""
from __future__ import annotations

import ast
import subprocess
import sys
import textwrap

from app.core.config import settings


class FigureRejected(ValueError):
    """Deze code levert geen bruikbare figuur op."""


# Wat de tekencode mag aanraken. `ax` is de assen die klaarstaan, `fig` de
# figuur eromheen; verder rekenen met numpy en scipy.stats.
ALLOWED_MODULES = ("ax", "fig", "np", "stats")
ALLOWED_BUILTINS = frozenset(
    {"range", "list", "tuple", "dict", "set", "len", "str", "int", "float", "bool", "sorted", "zip", "enumerate", "min", "max", "abs", "round", "sum"}
)

TIMEOUT_SECONDS = 20


def validate_figure_code(code: str) -> None:
    """Weiger alles wat een tekening niet nodig heeft."""
    try:
        tree = ast.parse(code or "", mode="exec")
    except SyntaxError as exc:
        raise FigureRejected(f"de tekencode is geen geldige Python ({exc.msg})") from None
    except ValueError:
        # Een nulbyte in de bron: dan gooit ast.parse geen SyntaxError maar een
        # ValueError, en die liet eerst het hele verzoek omvallen.
        raise FigureRejected("de tekencode bevat een nulbyte") from None

    toegekend: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise FigureRejected("de tekencode mag niets importeren")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            raise FigureRejected("de tekencode definieert geen functies of klassen")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise FigureRejected("de tekencode gebruikt geen global of nonlocal")
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    toegekend.add(target.id)
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            toegekend.add(node.target.id)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            wortel = node
            while isinstance(wortel, ast.Attribute):
                wortel = wortel.value
            if isinstance(wortel, ast.Name) and wortel.id not in ALLOWED_MODULES and wortel.id not in toegekend:
                raise FigureRejected(f"'{wortel.id}' mag niet in de tekencode; alleen {', '.join(ALLOWED_MODULES)}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in ALLOWED_BUILTINS and node.func.id not in toegekend:
                raise FigureRejected(f"'{node.func.id}' mag niet aangeroepen worden in de tekencode")


def matplotlib_available() -> bool:
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return False
    return True


# Draait in een eigen proces: Agg (geen scherm), vaste stijl, en daarna kijken
# of er iets getekend is. Een lege assenset is geen figuur.
_HARNESS = '''
import sys, json, io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
try:
    from scipy import stats
except Exception:
    stats = None

code = sys.stdin.read()
fig, ax = plt.subplots(figsize=(5.2, 3.2), dpi=110)
try:
    exec(compile(code, "<figuur>", "exec"), {"ax": ax, "fig": fig, "np": np, "stats": stats})
except Exception as exc:
    print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
    sys.exit(0)

getekend = bool(
    ax.lines or ax.patches or ax.collections or ax.images or ax.texts or ax.containers
)
if not getekend:
    print(json.dumps({"error": "de code tekent niets"}))
    sys.exit(0)

ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.tight_layout()
buffer = io.StringIO()
fig.savefig(buffer, format="svg", bbox_inches="tight", transparent=True)
print(json.dumps({"svg": buffer.getvalue()}))
'''


def render_figure(code: str, *, timeout: int | None = None) -> str:
    """De SVG van deze tekencode, of een `FigureRejected` met de reden."""
    if not matplotlib_available():
        raise FigureRejected("matplotlib is niet geïnstalleerd; zonder plotbibliotheek geen figuren")

    validate_figure_code(code)

    try:
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(_HARNESS)],
            input=code,
            capture_output=True,
            text=True,
            timeout=timeout or TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise FigureRejected("het tekenen duurde te lang") from None

    if result.returncode != 0:
        raise FigureRejected(f"het tekenen mislukte: {(result.stderr or '').strip()[:200]}")

    import json

    try:
        payload = json.loads((result.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise FigureRejected("het tekenen leverde geen leesbaar resultaat op") from None

    if payload.get("error"):
        raise FigureRejected(payload["error"])

    svg = payload.get("svg") or ""
    if "<svg" not in svg:
        raise FigureRejected("het resultaat is geen svg")
    # De XML-kop en de doctype hoeven niet mee; dit gaat rechtstreeks de pagina in.
    start = svg.find("<svg")
    return svg[start:]


__all__ = [
    "FigureRejected",
    "matplotlib_available",
    "render_figure",
    "validate_figure_code",
    "TIMEOUT_SECONDS",
]
