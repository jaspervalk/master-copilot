import pytest

from app.services.practice.validation import SetupRejected, validate_setup


@pytest.mark.parametrize(
    "setup",
    [
        "",
        "x2 = np.arange(12).reshape(3, 4)",
        "rng = np.random.default_rng(0)\nx = rng.normal(size=10)",
        "s = pd.Series([1, 2, 3], index=list('abc'))",
        "df = pd.DataFrame({'a': range(3), 'b': [1.0, 2.0, 3.0]})",
        "a = np.array([[1, 2], [3, 4]])\nb = a.T",
    ],
)
def test_a_normal_fixture_is_allowed(setup):
    validate_setup(setup)


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ("import os", "importeren"),
        ("from os import system", "importeren"),
        ("x = __import__('os')", "mag niet"),
        ("x = open('/etc/passwd').read()", "aanroepen mag niet"),
        ("x = eval('1+1')", "aanroepen mag niet"),
        ("x = np.arange(3).__class__", "mag niet"),
        ("print('hoi')", "alleen toewijzingen"),
        ("for i in range(3): pass", "alleen toewijzingen"),
        ("x = np.arange(", "geen geldige Python"),
    ],
)
def test_anything_beyond_building_a_fixture_is_rejected(setup, reason):
    with pytest.raises(SetupRejected, match=reason):
        validate_setup(setup)


def test_a_method_on_a_local_name_is_fine():
    """`x2.reshape(...)` is niet vooraf te keuren, maar hoort bij een fixture."""
    validate_setup("x2 = np.arange(12)\ny = x2.reshape(3, 4)")


def test_giveaway_terms_are_the_functions_and_parameters_in_the_answer():
    from app.services.practice.validation import giveaway_terms

    terms = giveaway_terms("np.sort(x, axis=0)", setup="x = np.array([1, 2])")

    # `sort` en `axis` verraden het antwoord; `x` is de fixture en `np` zegt niets.
    assert terms == {"sort", "axis"}


def test_the_fixture_name_may_appear_in_the_question():
    from app.services.practice.validation import giveaway_terms

    assert giveaway_terms("x[i]", setup="x = np.arange(5)\ni = np.argsort(x)") == set()


def test_a_method_call_gives_away_its_name():
    from app.services.practice.validation import giveaway_terms

    assert "mean" in giveaway_terms("x2.mean(axis=0)", setup="x2 = np.arange(12)")


def test_a_broken_expression_gives_no_terms():
    from app.services.practice.validation import giveaway_terms

    assert giveaway_terms("np.sort(") == set()
