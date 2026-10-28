"""Een figuur is code die draait. Doet hij dat niet, dan is er geen figuur.

Dezelfde afspraak als bij de oefenkaarten: het model stelt voor, een
interpreter beslist. Een plaatje dat het model beschrijft maar niet kan
tekenen, is een plaatje dat niet klopt.
"""
import pytest

from app.services.practice.figures import (
    FigureRejected,
    matplotlib_available,
    render_figure,
    validate_figure_code,
)


# Alleen het echte tekenen heeft matplotlib nodig; de grens eromheen niet.
tekent = pytest.mark.skipif(not matplotlib_available(), reason="matplotlib niet geïnstalleerd")


GOED = """
x = np.linspace(-4, 4, 200)
y = 1 / (1 + np.exp(-x))
ax.plot(x, y)
ax.set_xlabel("lineaire voorspeller")
ax.set_ylabel("kans")
"""


@tekent
def test_a_drawing_becomes_svg():
    svg = render_figure(GOED)

    assert svg.lstrip().startswith("<svg") or "<svg" in svg[:400]
    assert "</svg>" in svg


@tekent
def test_code_that_draws_nothing_is_refused():
    with pytest.raises(FigureRejected) as caught:
        render_figure("x = np.linspace(0, 1, 10)")

    assert "niets" in str(caught.value)


@tekent
def test_broken_code_names_the_error():
    with pytest.raises(FigureRejected) as caught:
        render_figure("ax.plot(onbekend, 1)")

    assert "NameError" in str(caught.value)


@tekent
def test_an_endless_loop_does_not_hold_the_app():
    with pytest.raises(FigureRejected) as caught:
        render_figure("while True:\n    pass")

    assert "lang" in str(caught.value)


def test_imports_and_files_are_refused_before_running():
    """De code komt van een model en draait zonder dat iemand hem leest.
    Dezelfde grens als bij de opzetcode van een oefenkaart."""
    for code in ("import os", "open('/etc/passwd')", "__import__('os').system('ls')"):
        with pytest.raises(FigureRejected):
            validate_figure_code(code)


def test_the_allowed_names_cover_a_normal_plot():
    validate_figure_code(GOED)
    validate_figure_code("ax.hist(stats.norm.rvs(size=100, random_state=1), bins=20)")


def test_code_with_a_null_byte_is_refused_not_a_crash():
    """Het model leverde een keer tekencode met een nulbyte erin. `ast.parse`
    gooit dan een ValueError in plaats van een SyntaxError, en die liet het
    hele verzoek omvallen in plaats van alleen de figuur."""
    with pytest.raises(FigureRejected):
        validate_figure_code("ax.plot([1, 2])\x00")
