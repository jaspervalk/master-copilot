"""Code uitvoeren en twee uitkomsten vergelijken.

Weet niets van kaarten: het krijgt opzetcode en een of twee uitdrukkingen, en
zegt wat eruit komt. Dat is bewust: de nakijklaag erboven kan zo ook een
tweede vorm krijgen (begripsvragen via een model) zonder dat hier iets aan
verandert.

Dit is géén beveiligingssandbox. Het is een lokale tool voor één gebruiker;
de code die draait is code die jij of jouw model schreef. Wat er wel omheen
staat is een subprocess met een timeout, zodat een oneindige lus de app niet
vasthoudt.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass

from app.core.config import settings


MAX_REPR = 500

# Een toetskaart reken je met de hand uit en rond je af. t = 2,31 tegenover
# 2,3138 is goed; 2,4 niet. Eén procent relatief laat precies de tweede
# decimaal los en houdt de derde vast.
HAND_COMPUTATION_RTOL = 0.01


def tolerance_for(kind: str) -> float | None:
    """De marge waarmee een antwoord van deze kaartsoort wordt nagekeken.

    Codekaarten leveren de waarde die de interpreter zelf uitrekent, dus daar
    is elke marge te veel. Toetskaarten typ je in als afgerond getal.
    """
    return HAND_COMPUTATION_RTOL if kind == "stats" else None


@dataclass
class EvalResult:
    value_repr: str
    error: str | None
    # Voor het keuren van een kaart: een uitdrukking die None teruggeeft én de
    # fixture ongemoeid laat toetst niets.
    returns_none: bool = False
    changed_state: bool = False
    # Een toetskaart moet één eindig getal opleveren; een array of een
    # scipy-resultaatobject is geen antwoord dat je op een tentamen opschrijft.
    returns_number: bool = False
    # Datzelfde getal, om mee te rekenen. None zodra returns_number onwaar is.
    number: float | None = None
    # De uitkomst is gelijk aan een getal dat al in de opzet staat. `np.sum([1]*T)`
    # ontwijkt een controle op de vórm van de uitdrukking, maar niet deze.
    matches_fixture: str | None = None


@dataclass
class CompareResult:
    equal: bool
    expected_repr: str
    given_repr: str
    # Gescheiden gehouden: een kapotte referentie betekent dat de kaart niet
    # deugt, een kapotte kandidaat dat het antwoord niet deugt.
    reference_error: str | None
    candidate_error: str | None


# Draait in het subprocess. Leest {setup, reference, candidate, tolerance} van
# stdin en schrijft het oordeel als JSON naar stdout.
_HARNESS = r'''
import json, sys

MAX_REPR = %d
payload = json.load(sys.stdin)
tolerance = payload.get("tolerance")
out = {"expected_repr": "", "given_repr": "", "reference_error": None,
       "candidate_error": None, "equal": False, "changed_state": False,
       "returns_none": False, "returns_number": False, "number": None,
       "matches_fixture": None}

def short(value):
    text = repr(value)
    return text if len(text) <= MAX_REPR else text[:MAX_REPR] + "…"

def fail(exc):
    return f"{type(exc).__name__}: {exc}"

try:
    import numpy as np
except Exception as exc:  # pragma: no cover
    print(json.dumps({**out, "reference_error": fail(exc)})); sys.exit(0)

# pandas en scipy kosten elk een seconde of meer om te laden; de meeste
# kaarten hebben er geen van beide nodig. Alleen importeren als de code de
# naam noemt.
source = payload["setup"] + payload["reference"] + (payload["candidate"] or "")
pd = None
if "pd" in source:
    try:
        import pandas as pd
    except Exception:
        pd = None
stats = None
if "stats" in source:
    try:
        from scipy import stats
    except Exception:
        stats = None
# Voor het narekenen van SSO deel 2: een LP of ILP (optimize.linprog, milp) en
# een kortste pad of maximale stroom (csgraph.dijkstra, maximum_flow). Ook alleen
# als de code ze noemt.
optimize = csgraph = sparse = None
if "optimize" in source:
    try:
        from scipy import optimize
    except Exception:
        optimize = None
if "csgraph" in source or "sparse" in source:
    try:
        from scipy import sparse
        from scipy.sparse import csgraph
    except Exception:
        sparse = csgraph = None
import math

MODULES = ("np", "pd", "stats", "optimize", "csgraph", "sparse", "math")

def fresh():
    """Een eigen naamruimte per uitdrukking.

    Anders muteert `x.sort()` als referentie de fixture voordat het antwoord
    van de student hem te zien krijgt.
    """
    namespace = {"np": np, "pd": pd, "stats": stats, "optimize": optimize, "csgraph": csgraph, "sparse": sparse, "math": math}
    if payload["setup"].strip():
        exec(payload["setup"], namespace)
    return namespace

def fixture_state(namespace):
    return {
        name: value for name, value in namespace.items()
        if not name.startswith("__") and name not in MODULES
    }

try:
    baseline = fixture_state(fresh())
except Exception as exc:
    out["reference_error"] = fail(exc)
    print(json.dumps(out)); sys.exit(0)

def close(a, b):
    """Elementsgewijs; de aanroeper vouwt het samen. Bij arrays dus een array."""
    if tolerance is None:
        return np.isclose(a, b, equal_nan=True)
    # atol=0: bij een marge die "twee decimalen" moet betekenen mag een
    # antwoord van 0 niet gelijk zijn aan 1e-8.
    return np.isclose(a, b, rtol=tolerance, atol=0.0, equal_nan=True)

def same(a, b):
    if type(a).__module__.split(".")[0] == "pandas" or type(b).__module__.split(".")[0] == "pandas":
        try:
            return bool(a.equals(b))
        except Exception:
            return False
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        left, right = np.asarray(a), np.asarray(b)
        if left.shape != right.shape:
            return False
        if left.dtype.kind in "fc" or right.dtype.kind in "fc":
            try:
                return bool(np.all(close(left, right)))
            except Exception:
                return False
        return bool(np.array_equal(left, right))
    if isinstance(a, (float, np.floating)) or isinstance(b, (float, np.floating)):
        try:
            return bool(close(a, b))
        except Exception:
            return False
    # Gehele getallen met een marge: 39 tegenover 38 vrijheidsgraden is fout,
    # maar np.int64(38) en 38 zijn hetzelfde antwoord.
    try:
        return bool(a == b)
    except Exception:
        return False

def same_state(left, right):
    return set(left) == set(right) and all(same(left[name], right[name]) for name in left)

def is_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        return False
    return bool(np.isfinite(value))

try:
    reference_ns = fresh()
    reference = eval(payload["reference"], reference_ns)
    reference_state = fixture_state(reference_ns)
    out["expected_repr"] = short(reference)
except Exception as exc:
    out["reference_error"] = fail(exc)
    print(json.dumps(out)); sys.exit(0)

# Een uitdrukking die None teruggeeft én niets aan de fixture verandert
# toetst niets: elk ander None-antwoord zou ook goed gerekend worden.
out["changed_state"] = not same_state(baseline, reference_state)
out["returns_none"] = reference is None
out["returns_number"] = is_number(reference)
# Als getal mee terug, zodat de aanroeper het niet uit de repr hoeft te vissen
# ("np.float64(0.04)" begint met een 64).
if out["returns_number"]:
    out["number"] = float(reference)
    for naam, waarde in sorted(baseline.items()):
        if is_number(waarde) and same(reference, waarde):
            out["matches_fixture"] = naam
            break

if payload["candidate"] is None:
    out["equal"] = True
    print(json.dumps(out)); sys.exit(0)

try:
    candidate_ns = fresh()
    candidate = eval(payload["candidate"], candidate_ns)
    out["given_repr"] = short(candidate)
except Exception as exc:
    out["candidate_error"] = fail(exc)
    print(json.dumps(out)); sys.exit(0)

# Zowel de teruggegeven waarde als wat er met de fixture gebeurde: zo is
# `x.sort()` te onderscheiden van elke andere uitdrukking die None oplevert.
out["equal"] = same(reference, candidate) and same_state(reference_state, fixture_state(candidate_ns))
print(json.dumps(out))
''' % MAX_REPR


def _run(setup: str, reference: str, candidate: str | None, tolerance: float | None) -> dict:
    payload = json.dumps(
        {"setup": setup, "reference": reference, "candidate": candidate, "tolerance": tolerance}
    )
    try:
        finished = subprocess.run(
            [sys.executable, "-c", _HARNESS],
            input=payload,
            capture_output=True,
            text=True,
            timeout=settings.practice_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {"timeout": True}

    if finished.returncode != 0 or not finished.stdout.strip():
        detail = (finished.stderr or "onbekende fout").strip().splitlines()[-1:]
        return {"crash": detail[0] if detail else "onbekende fout"}
    return json.loads(finished.stdout)


def evaluate(setup: str, expression: str, tolerance: float | None = None) -> EvalResult:
    """Draai de opzet en één uitdrukking. Gebruikt om een kaart te keuren."""
    raw = _run(setup, expression, None, tolerance)
    if raw.get("timeout"):
        return EvalResult("", f"duurde langer dan {settings.practice_timeout_seconds} seconden")
    if raw.get("crash"):
        return EvalResult("", raw["crash"])
    return EvalResult(
        raw["expected_repr"],
        raw["reference_error"],
        returns_none=bool(raw.get("returns_none")),
        changed_state=bool(raw.get("changed_state")),
        returns_number=bool(raw.get("returns_number")),
        number=raw.get("number"),
        matches_fixture=raw.get("matches_fixture"),
    )


def compare(
    setup: str, reference: str, candidate: str, tolerance: float | None = None
) -> CompareResult:
    """Draai beide uitdrukkingen, elk in een eigen naamruimte, en vergelijk.

    Op waarde, niet op tekst: `x2.mean(axis=0)` en `np.mean(x2, axis=0)` zijn
    hetzelfde antwoord, en dat hoort de interpreter te bepalen — niet een
    model dat twee strings naast elkaar legt. Naast de teruggegeven waarde
    telt ook wat er met de fixture gebeurde, zodat `x.sort()` te
    onderscheiden is van elke andere uitdrukking die None oplevert.

    `tolerance` is de relatieve marge voor kommagetallen. Zonder marge moet
    het exact kloppen; met marge mag je een handberekening afronden.
    """
    raw = _run(setup, reference, candidate, tolerance)
    if raw.get("timeout"):
        melding = f"duurde langer dan {settings.practice_timeout_seconds} seconden"
        return CompareResult(False, "", "", None, melding)
    if raw.get("crash"):
        return CompareResult(False, "", "", raw["crash"], None)
    return CompareResult(
        equal=bool(raw["equal"]),
        expected_repr=raw["expected_repr"],
        given_repr=raw["given_repr"],
        reference_error=raw["reference_error"],
        candidate_error=raw["candidate_error"],
    )
