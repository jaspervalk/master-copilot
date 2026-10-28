"""De sandbox is het hart van de oefenmodus: als uitvoeren-en-vergelijken niet
deugt, deugt de rest ook niet. Deze tests draaien een echt subprocess."""
import pytest

from app.services.practice.sandbox import compare, evaluate


SETUP = "x2 = np.arange(12).reshape(3, 4)"


def test_evaluate_returns_the_value_of_a_working_expression():
    result = evaluate(SETUP, "x2.mean(axis=0)")

    assert result.error is None
    assert "4." in result.value_repr


def test_evaluate_reports_a_broken_setup():
    result = evaluate("x2 = np.arange(", "x2")

    assert result.error is not None
    assert "Syntax" in result.error or "syntax" in result.error


def test_evaluate_reports_a_broken_expression():
    result = evaluate(SETUP, "x2.gemiddelde()")

    assert result.error is not None
    assert "gemiddelde" in result.error


def test_two_spellings_of_the_same_thing_are_equal():
    """Precies waarom de interpreter de scheidsrechter is en geen model."""
    result = compare(SETUP, "x2.mean(axis=0)", "np.mean(x2, axis=0)")

    assert result.equal
    assert result.reference_error is None
    assert result.candidate_error is None


def test_a_different_answer_is_not_equal():
    result = compare(SETUP, "x2.mean(axis=0)", "x2.mean(axis=1)")

    assert not result.equal
    assert result.expected_repr != result.given_repr


def test_floats_are_compared_with_a_tolerance():
    result = compare("", "1/3", "0.3333333333333333")

    assert result.equal


def test_nan_equals_nan():
    result = compare("", "np.array([1.0, np.nan])", "np.array([1.0, float('nan')])")

    assert result.equal


def test_pandas_objects_are_compared_with_equals():
    result = compare(
        "s = pd.Series([1, 2, 3], index=list('abc'))",
        "s[s > 1]",
        "s.loc[['b', 'c']]",
    )

    assert result.equal


def test_shape_difference_is_not_equal():
    result = compare(SETUP, "x2", "x2.ravel()")

    assert not result.equal


def test_a_broken_candidate_is_wrong_not_a_crash():
    """Een SyntaxError lezen hoort bij het leren; de app valt er niet over om."""
    result = compare(SETUP, "x2.mean(axis=0)", "x2.mean(axis=")

    assert not result.equal
    assert result.candidate_error is not None
    assert result.reference_error is None


def test_a_broken_reference_is_reported_separately():
    result = compare(SETUP, "x2.onzin()", "x2.mean(axis=0)")

    assert not result.equal
    assert result.reference_error is not None


def test_an_endless_loop_is_stopped(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "practice_timeout_seconds", 2)

    result = evaluate("", "[x for x in iter(int, 1)]")

    assert result.error is not None
    assert "lang" in result.error.lower() or "timeout" in result.error.lower()


def test_the_value_repr_is_truncated():
    result = evaluate("", "list(range(10000))")

    assert result.error is None
    assert len(result.value_repr) <= 520


def test_the_candidate_never_sees_a_fixture_the_reference_mutated():
    """`x.sort()` als referentie sorteerde x, waarna het antwoord een al
    gesorteerde array zag. Elke uitdrukking krijgt nu een eigen naamruimte."""
    result = compare(SETUP + "\nv = np.array([3, 1, 2])", "np.sort(v)", "np.sort(v)")

    assert result.equal


def test_an_in_place_operation_is_recognised_by_its_effect():
    result = compare("v = np.array([3, 1, 2])", "v.sort()", "v.sort()")

    assert result.equal


def test_another_none_returning_expression_is_not_the_same_answer():
    """Zonder de fixture te vergelijken zou elk None-antwoord goed zijn."""
    result = compare("v = np.array([3, 1, 2])", "v.sort()", "v.fill(0)")

    assert not result.equal


def test_evaluate_reports_a_no_op_expression():
    leeg = evaluate("v = np.array([3, 1, 2])", "None")
    sorteert = evaluate("v = np.array([3, 1, 2])", "v.sort()")

    assert leeg.returns_none and not leeg.changed_state
    assert sorteert.returns_none and sorteert.changed_state


# --- marge voor handberekeningen -------------------------------------------


def test_tolerance_is_only_for_stats_cards():
    from app.services.practice.sandbox import HAND_COMPUTATION_RTOL, tolerance_for

    assert tolerance_for("stats") == HAND_COMPUTATION_RTOL
    assert tolerance_for("code") is None


def test_a_rounded_hand_computation_counts_as_correct():
    from app.services.practice.sandbox import tolerance_for

    setup = "n = 40\nxbar = 12.3\nmu = 11.0\ns = 2.1"
    reference = "(xbar - mu) / (s / np.sqrt(n))"  # 3.9152…

    assert compare(setup, reference, "3.92", tolerance_for("stats")).equal
    assert compare(setup, reference, "3.9", tolerance_for("stats")).equal


def test_the_margin_does_not_stretch_to_the_wrong_answer():
    from app.services.practice.sandbox import tolerance_for

    setup = "n = 40\nxbar = 12.3\nmu = 11.0\ns = 2.1"
    reference = "(xbar - mu) / (s / np.sqrt(n))"

    assert not compare(setup, reference, "3.8", tolerance_for("stats")).equal
    # Zonder marge — een codekaart — telt afronden niet als goed.
    assert not compare(setup, reference, "3.92").equal


def test_zero_is_not_close_to_a_tiny_number():
    """atol=0: anders zou elk antwoord bij een verwachte 0 goed zijn."""
    assert not compare("", "0.0", "1e-9", 0.01).equal


def test_scipy_is_available_when_the_expression_asks_for_it():
    result = evaluate("", "stats.t.ppf(0.975, df=39)")

    assert result.error is None
    assert result.returns_number
    assert "2.0226" in result.value_repr  # t_{0,975; 39}


def test_an_array_is_not_a_number():
    assert not evaluate("", "np.arange(3)").returns_number
    assert evaluate("", "float(np.mean(np.arange(3)))").returns_number
