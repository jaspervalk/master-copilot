from __future__ import annotations

import http.client
import urllib.error
from datetime import datetime

import pytest
from tests.canvas_stub import Paged, canvas_opener

from app.core.config import settings
from app.services.canvas.client import (
    CanvasClient,
    CanvasError,
    CanvasNotConfigured,
    client_from_settings,
    file_ids_in_html,
    html_to_markdown,
    parse_timestamp,
    strip_html,
)


def _client(routes: dict, **overrides) -> tuple[CanvasClient, object]:
    stub = canvas_opener(routes)
    return CanvasClient(base_url="https://canvas.test", token="geheim-token", opener=stub, **overrides), stub


def test_get_sends_the_bearer_header_and_asks_for_full_pages():
    client, stub = _client({"courses": [{"id": 1}]})

    assert client.get("courses") == [{"id": 1}]
    call = stub.calls[0]
    assert call.header == "Bearer geheim-token"
    assert call.params["per_page"] == ["100"]


def test_list_parameters_are_repeated_the_way_canvas_wants_them():
    """`include[]=term&include[]=total_scores`, niet één komma-lijst."""
    client, stub = _client({"courses": []})

    client.get("courses", {"include[]": ["term", "total_scores"], "enrollment_state": "active"})

    params = stub.calls[0].params
    assert params["include[]"] == ["term", "total_scores"]
    assert params["enrollment_state"] == ["active"]


def test_pagination_follows_the_link_header():
    client, stub = _client({"courses": Paged([[{"id": 1}, {"id": 2}], [{"id": 3}]])})

    assert client.get("courses") == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert len(stub.calls) == 2


def test_a_dict_body_is_returned_as_is():
    client, stub = _client({"courses/59831": {"id": 59831, "name": "FDS"}})

    assert client.get("courses/59831") == {"id": 59831, "name": "FDS"}
    assert len(stub.calls) == 1


def test_paginate_false_stops_after_the_first_page():
    client, stub = _client({"courses": Paged([[{"id": 1}], [{"id": 2}]])})

    assert client.get("courses", paginate=False) == [{"id": 1}]
    assert len(stub.calls) == 1


def test_an_http_error_carries_status_and_path_but_never_the_token():
    client, _ = _client({"courses/59863/files": 403})

    with pytest.raises(CanvasError) as caught:
        client.get("courses/59863/files")

    assert caught.value.status == 403
    assert "403" in str(caught.value)
    assert "courses/59863/files" in str(caught.value)
    assert "geheim-token" not in str(caught.value)


def test_a_network_error_has_no_status_and_names_the_cause():
    def refused(request, timeout=None):
        raise urllib.error.URLError("Connection refused")

    client = CanvasClient(base_url="https://canvas.test", token="geheim-token", opener=refused)

    with pytest.raises(CanvasError) as caught:
        client.get("courses")

    assert caught.value.status is None
    assert "Connection refused" in str(caught.value)
    assert "geheim-token" not in str(caught.value)


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("timed out"), http.client.RemoteDisconnected("closed"), http.client.IncompleteRead(b"")],
    ids=["time-out", "verbroken", "half antwoord"],
)
def test_a_connection_that_breaks_after_the_request_is_a_canvas_error(failure):
    """Alleen `URLError` werd omgezet. Een time-out tijdens het lezen is er geen,
    en liet de terugval op de laatste momentopname (`cli notify`) omvallen."""

    def broken(request, timeout=None):
        raise failure

    client = CanvasClient(base_url="https://canvas.test", token="geheim-token", opener=broken)

    with pytest.raises(CanvasError) as caught:
        client.get("courses")

    assert caught.value.status is None
    assert "geheim-token" not in str(caught.value)
    assert caught.value.__suppress_context__ is True


def test_a_download_that_breaks_while_reading_is_a_canvas_error():
    def broken(request, timeout=None):
        raise TimeoutError("timed out")

    client = CanvasClient(base_url="https://canvas.test", token="geheim-token", opener=broken)

    with pytest.raises(CanvasError) as caught:
        client.download("https://canvas.test/files/9001/download", max_bytes=10)

    assert caught.value.status is None


def test_a_body_that_is_not_json_is_a_canvas_error():
    """Een inlogpagina of proxy antwoordt 200 met html."""
    client, _ = _client({"courses": b"<html>log in</html>"})

    with pytest.raises(CanvasError) as caught:
        client.get("courses")

    assert "geen JSON" in str(caught.value)


def test_get_optional_swallows_only_the_tolerated_statuses():
    client, _ = _client({"courses/1/folders": 403, "courses/1/front_page": 404, "courses/1/broken": 500})

    assert client.get_optional("courses/1/folders") is None
    assert client.get_optional("courses/1/front_page") is None
    with pytest.raises(CanvasError):
        client.get_optional("courses/1/broken")


def test_download_returns_the_bytes():
    client, stub = _client({"/files/9001/download": b"%PDF-1.4 inhoud"})

    assert client.download("https://canvas.test/files/9001/download?verifier=x", max_bytes=1000) == b"%PDF-1.4 inhoud"
    assert stub.calls[0].header == "Bearer geheim-token"


def test_download_refuses_a_file_above_the_limit():
    client, _ = _client({"/files/9001/download": b"x" * 50})

    with pytest.raises(CanvasError) as caught:
        client.download("https://canvas.test/files/9001/download", max_bytes=10)

    assert "groter" in str(caught.value)


def test_strip_html_keeps_line_breaks_and_unescapes():
    text = strip_html("<p>Hallo &amp; welkom</p><ul><li>een</li><li>twee</li></ul><br>einde")

    assert text == "Hallo & welkom\neen\ntwee\neinde"


def test_parse_timestamp_gives_naive_utc():
    """Opslag is naïef UTC, zoals `utcnow()` overal; de Z valt eraf."""
    assert parse_timestamp("2026-09-28T21:59:00Z") == datetime(2026, 9, 28, 21, 59)
    assert parse_timestamp("2026-09-28T23:59:00+02:00") == datetime(2026, 9, 28, 21, 59)
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None


def test_file_ids_in_html_finds_every_link_shape_once():
    html = (
        '<a href="https://canvas.uva.nl/courses/59863/files/15767543/download?wrap=1">a</a>'
        '<a href="/courses/59863/files/15767543?wrap=1">b</a>'
        '<a href="https://canvas.uva.nl/api/v1/files/15767394">c</a>'
        '<img src="/files/15925157/preview">'
    )

    assert file_ids_in_html(html) == [15767543, 15767394, 15925157]
    assert file_ids_in_html(None) == []


def test_client_from_settings_is_none_without_configuration():
    assert client_from_settings() is None


def test_client_from_settings_strips_the_trailing_slash(monkeypatch):
    monkeypatch.setattr(settings, "canvas_base_url", "https://canvas.uva.nl/")
    monkeypatch.setattr(settings, "canvas_access_token", "abc")

    client = client_from_settings()

    assert client is not None
    assert client.base_url == "https://canvas.uva.nl"
    assert client.token == "abc"


def test_an_empty_token_counts_as_unconfigured(monkeypatch):
    """`.env` met `CANVAS_ACCESS_TOKEN=` zet een lege string, geen None."""
    monkeypatch.setattr(settings, "canvas_base_url", "https://canvas.uva.nl")
    monkeypatch.setattr(settings, "canvas_access_token", "")

    assert client_from_settings() is None


def test_not_configured_is_a_canvas_error_with_a_readable_hint():
    error = CanvasNotConfigured()

    assert isinstance(error, CanvasError)
    assert "CANVAS_ACCESS_TOKEN" in str(error)


def test_html_to_markdown_keeps_the_structure_of_an_assignment():
    """De koppen worden de opgaven in de chunker; zonder structuur wordt een
    opdracht van twaalf pagina's één lange lap."""
    html = (
        "<h2>Part 1: Data</h2><p>Load the <strong>UN</strong> corpus.</p>"
        "<ul><li>Clean the text</li><li>Count words</li></ul>"
        "<ol><li>First</li><li>Second</li></ol>"
        "<h3>Question 1.1</h3><p>What is <code>df.shape</code>?</p>"
        "<pre>import pandas as pd\ndf = pd.read_csv('x.csv')</pre>"
        '<p>See <a href="https://example.org/docs">the docs</a>.</p>'
        "<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>"
        "<p>Tekst&nbsp;met &amp; entiteiten</p>"
    )

    markdown = html_to_markdown(html)

    assert "## Part 1: Data" in markdown
    assert "Load the UN corpus." in markdown
    assert "- Clean the text\n- Count words" in markdown
    assert "1. First\n2. Second" in markdown
    assert "### Question 1.1" in markdown
    assert "`df.shape`" in markdown
    assert "```\nimport pandas as pd\ndf = pd.read_csv('x.csv')\n```" in markdown
    assert "the docs (https://example.org/docs)" in markdown
    assert "a | b" in markdown and "1 | 2" in markdown
    assert "Tekst met & entiteiten" in markdown
    assert "\n\n\n" not in markdown


def test_a_paragraph_of_only_bold_text_becomes_a_heading():
    """De opdrachten van FDS gebruiken `<p><strong>Deadline</strong></p>` als kop.
    Als echte kop worden het secties waarop de chunker knipt."""
    markdown = html_to_markdown(
        "<p>Intro met <strong>nadruk</strong> in de zin.</p>"
        "<p><strong>Datasets</strong></p><p>Gebruik de UN-data.</p>"
        "<p><strong>&nbsp;</strong></p>"
    )

    assert "## Datasets\n\nGebruik de UN-data." in markdown
    assert "Intro met nadruk in de zin." in markdown
    assert "## \n" not in markdown and not markdown.endswith("##")


def test_canvas_file_links_lose_their_verifier():
    """Een verifier geeft iedereen met de link toegang tot het bestand. Hij hoort
    niet in het corpus, en dus niet in een embedding bij OpenAI."""
    markdown = html_to_markdown(
        '<p>Lees <a href="https://canvas.uva.nl/courses/59831/files/15868331?verifier=32c45dc1&amp;wrap=1">de pdf</a>.</p>'
    )

    assert "verifier" not in markdown
    assert "de pdf (https://canvas.uva.nl/courses/59831/files/15868331)" in markdown


def test_lists_inside_a_table_cell_stay_in_the_cell():
    """Het rooster van SSO is een tabel met lijstjes in de cellen. Zonder dit
    vielen de punten als losse streepjes buiten de rij, en plakten de
    onderwerpen aan elkaar ("Recap probability distributionsWhat is statistics?")."""
    html = (
        "<table><tr><th>Lecture</th><th>Material</th></tr>"
        "<tr><td>1</td><td><ul><li>Recap</li><li>What is statistics?</li></ul></td></tr>"
        "<tr><td>2</td><td><p>Datasets:</p><ul><li>amsterdam.txt</li></ul></td></tr></table>"
    )

    markdown = html_to_markdown(html)

    assert "Lecture | Material" in markdown
    assert "1 | Recap; What is statistics?" in markdown
    assert "2 | Datasets: amsterdam.txt" in markdown
    assert "\n-" not in markdown


def test_a_link_without_text_adds_nothing():
    """Een downloadicoontje is een link zonder tekst; de url stond al bij de naam."""
    markdown = html_to_markdown(
        '<p><a href="https://x.test/a">data.txt</a><a href="https://x.test/a"><img src="i.png"></a></p>'
    )

    assert markdown == "data.txt (https://x.test/a)"
