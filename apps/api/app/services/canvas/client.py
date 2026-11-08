"""Een alleen-lezende client voor de Canvas REST-API.

Alleen `GET`: er is geen parameter voor een andere methode, dus naar Canvas
schrijven kan niet, ook niet per ongeluk. Het token gaat als header mee en
komt nergens anders terecht — niet in een foutmelding, niet in een log. Een
fout noemt de status en het pad; dat is genoeg om te zien wat er mis is.

Stdlib `urllib` met een injecteerbare `opener`, zoals `app/eval/search.py`:
tests geven een stub mee en raken geen netwerk.
"""
from __future__ import annotations

import html
import http.client
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

from app.core.config import settings


class CanvasError(Exception):
    """Canvas gaf geen bruikbaar antwoord. Kent status en pad, nooit de header."""

    def __init__(self, status: int | None, path: str, hint: str = "") -> None:
        self.status = status
        self.path = path
        if status is None:
            message = f"Canvas onbereikbaar ({path})" + (f": {hint}" if hint else "")
        else:
            message = f"Canvas antwoordde {status} op {path}" + (f": {hint}" if hint else "")
        super().__init__(message)


class CanvasNotConfigured(CanvasError):
    def __init__(self) -> None:
        self.status = None
        self.path = "instellingen"
        Exception.__init__(self, "Canvas is niet geconfigureerd: zet CANVAS_BASE_URL en CANVAS_ACCESS_TOKEN in .env")


def _ssl_context() -> ssl.SSLContext:
    # De python.org-build op macOS heeft geen CA-bundel; certifi als die er is,
    # anders die van het systeem.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        cafile = "/etc/ssl/cert.pem"
        return ssl.create_default_context(cafile=cafile if os.path.exists(cafile) else None)


def _default_opener(request: urllib.request.Request, timeout: int | None = None):
    return urllib.request.urlopen(request, timeout=timeout, context=_ssl_context())


_NEXT_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="next"')
_DOWNLOAD_CHUNK = 1 << 16


@dataclass(frozen=True)
class CanvasClient:
    base_url: str
    token: str
    opener: Callable = field(default=_default_opener, repr=False)
    timeout: int = 30

    def get(self, path: str, params: dict | None = None, *, paginate: bool = True) -> Any:
        """Eén pad; een lijstantwoord wordt via de Link-header volledig gemaakt."""
        query = {"per_page": 100, **(params or {})}
        url = f"{self.base_url}/api/v1/{path.lstrip('/')}?{urllib.parse.urlencode(query, doseq=True)}"
        body, link = self._request(url, path)
        if not isinstance(body, list) or not paginate:
            return body
        results = list(body)
        while (match := _NEXT_LINK_RE.search(link)) is not None:
            body, link = self._request(match.group(1), path)
            results.extend(body)
        return results

    def get_optional(self, path: str, params: dict | None = None, *, tolerate: tuple[int, ...] = (403, 404)) -> Any | None:
        """Voor hulpendpoints die een student niet altijd mag zien."""
        try:
            return self.get(path, params)
        except CanvasError as exc:
            if exc.status in tolerate:
                return None
            raise

    def download(self, url: str, *, max_bytes: int) -> bytes:
        """De inhoud van een bestand. De URL komt uit `files/{id}` en verloopt;
        hij wordt daarom nooit bewaard."""
        path = urllib.parse.urlsplit(url).path
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"}, method="GET")
        chunks: list[bytes] = []
        size = 0
        try:
            with self.opener(request, timeout=self.timeout) as response:
                while chunk := response.read(_DOWNLOAD_CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise CanvasError(None, path, f"bestand is groter dan {max_bytes} bytes")
                    chunks.append(chunk)
        except urllib.error.HTTPError as exc:
            raise CanvasError(exc.code, path) from None
        except urllib.error.URLError as exc:
            raise CanvasError(None, path, str(exc.reason)) from None
        except (OSError, http.client.HTTPException) as exc:
            raise CanvasError(None, path, str(exc) or type(exc).__name__) from None
        return b"".join(chunks)

    def _request(self, url: str, path: str) -> tuple[Any, str]:
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"}, method="GET")
        try:
            with self.opener(request, timeout=self.timeout) as response:
                body = response.read()
                link = response.headers.get("Link", "") or ""
        except urllib.error.HTTPError as exc:
            # `from None`: de oorspronkelijke fout draagt het verzoek, mét header.
            raise CanvasError(exc.code, path) from None
        except urllib.error.URLError as exc:
            raise CanvasError(None, path, str(exc.reason)) from None
        except (OSError, http.client.HTTPException) as exc:
            # Een time-out of verbroken verbinding tijdens het lezen is geen URLError.
            raise CanvasError(None, path, str(exc) or type(exc).__name__) from None
        try:
            return json.loads(body), link
        except ValueError:
            # Een inlogpagina of proxy antwoordt 200 met html.
            raise CanvasError(None, path, "het antwoord was geen JSON") from None


def client_from_settings() -> CanvasClient | None:
    """None zonder configuratie. Een lege string telt als leeg: `.env` met
    `CANVAS_ACCESS_TOKEN=` zet geen None."""
    if not settings.canvas_base_url or not settings.canvas_access_token:
        return None
    return CanvasClient(
        base_url=settings.canvas_base_url.rstrip("/"),
        token=settings.canvas_access_token,
        timeout=settings.canvas_timeout_seconds,
    )


def strip_html(text: str | None) -> str:
    """Platte tekst met één regeleinde per blok. Geen lege regels: `</li><br>`
    zou er anders twee geven, en een aankondiging leest ook zonder witregels."""
    text = re.sub(r"<(br|/p|/div|/li|/h\d|/tr)[^>]*>", "\n", text or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def parse_timestamp(value: str | None) -> datetime | None:
    """Canvas geeft `2026-09-28T21:59:00Z`; opslag is naïef UTC."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


_FILE_ID_RE = re.compile(r"/files/(\d+)")


def file_ids_in_html(text: str | None) -> list[int]:
    """Bestand-ids uit de links in een pagina of beschrijving, elk één keer, in
    volgorde van voorkomen. Vangt `/courses/x/files/123`, `/files/123/download`
    en de API-vorm."""
    seen: list[int] = []
    for match in _FILE_ID_RE.finditer(text or ""):
        file_id = int(match.group(1))
        if file_id not in seen:
            seen.append(file_id)
    return seen


# Langer dan dit is een vetgedrukte zin, geen kop.
_HEADING_MAX_CHARS = 80


def _clean_href(href: str) -> str:
    """Zonder `verifier`: die geeft iedereen met de link toegang tot het bestand,
    en hoort dus niet in het corpus of in een embedding. Bij een Canvas-bestand
    gaat de hele query weg (`wrap=1` zegt niets)."""
    if not href:
        return href
    parts = urllib.parse.urlsplit(href)
    query = [(key, value) for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if key != "verifier"]
    if _FILE_ID_RE.search(parts.path):
        query = []
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


class _MarkdownWriter(HTMLParser):
    """Canvas-HTML naar markdown: koppen, lijsten, code en tabellen blijven
    herkenbaar. De koppen worden in de chunker de opgaven; zonder structuur is
    een opdracht van twaalf pagina's één lange lap."""

    _BLOCKS = frozenset({"p", "div", "section", "article", "blockquote", "hr", "figure"})
    _SKIP = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.lists: list[list] = []  # [soort, teller]
        self.href: str | None = None
        self.link_text: list[str] = []
        self.in_pre = False
        self.skipping = 0
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.after_bullet = False
        # Een alinea met alleen vette tekst is in Canvas een kop
        # (`<p><strong>Deadline</strong></p>`). Bijgehouden: waar hij begon en
        # of er tekst buiten het vet stond.
        self.bold = 0
        self.paragraph_start: int | None = None
        self.paragraph_bold_only = False

    def _write(self, text: str) -> None:
        if self.cell is not None:
            self.cell.append(text)
        else:
            self.parts.append(text)
        if self.href is not None:
            self.link_text.append(text)

    def _block(self) -> None:
        # Een alinea binnen een lijstpunt begint niet op een nieuwe regel.
        if not self.after_bullet:
            self.parts.append("\n\n")

    # Wat binnen een tabelcel een nieuwe regel of een lijstpunt zou zijn. Een
    # markdownrij is één regel; het rooster van SSO heeft lijstjes in de cellen.
    _CELL_BREAKS = frozenset({"p", "div", "br", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6"})

    def _cell_break(self, tag: str) -> None:
        text = "".join(self.cell or []).rstrip()
        if not text:
            return
        # Lijstpunten gescheiden door een puntkomma, behalve na "Datasets:".
        separator = "; " if tag == "li" and not text.endswith(":") else " "
        self.cell.append(separator)

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if self.cell is not None and tag in self._CELL_BREAKS:
            self._cell_break(tag)
            return
        if tag in self._SKIP:
            self.skipping += 1
        elif tag in self._BLOCKS:
            self._block()
            if tag == "p" and not self.lists:
                self.paragraph_start = len(self.parts)
                self.paragraph_bold_only = True
        elif tag in {"strong", "b"}:
            self.bold += 1
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
            self.after_bullet = False
        elif tag == "br":
            self._write("\n")
        elif tag in {"ul", "ol"}:
            self.lists.append([tag, 0])
            if len(self.lists) == 1:
                self._block()
        elif tag == "li":
            depth = max(len(self.lists), 1)
            kind = self.lists[-1] if self.lists else ["ul", 0]
            kind[1] += 1
            marker = f"{kind[1]}." if kind[0] == "ol" else "-"
            self.parts.append("\n" + "  " * (depth - 1) + marker + " ")
            self.after_bullet = True
        elif tag == "pre":
            self.parts.append("\n\n```\n")
            self.in_pre = True
        elif tag == "code" and not self.in_pre:
            self._write("`")
        elif tag == "a":
            self.href = attributes.get("href")
            self.link_text = []
        elif tag == "img" and attributes.get("alt"):
            self._write(f"[{attributes['alt']}]")
        elif tag == "table":
            self._block()
        elif tag == "tr":
            self.row = []
        elif tag in {"td", "th"}:
            self.cell = []

    def handle_endtag(self, tag: str) -> None:
        if self.cell is not None and tag in self._CELL_BREAKS:
            if tag in {"p", "div"}:
                self.cell.append(" ")
            return
        if tag in self._SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in {"strong", "b"}:
            self.bold = max(0, self.bold - 1)
        elif tag == "p" and self.paragraph_start is not None:
            start, self.paragraph_start = self.paragraph_start, None
            title = " ".join("".join(self.parts[start:]).split())
            if self.paragraph_bold_only and title and len(title) <= _HEADING_MAX_CHARS:
                self.parts[start:] = ["## " + title]
            self.parts.append("\n\n")
        elif tag in self._BLOCKS or tag in {"h1", "h2", "h3", "h4", "h5", "h6", "table"}:
            self.parts.append("\n\n")
        elif tag in {"ul", "ol"}:
            if self.lists:
                self.lists.pop()
            if not self.lists:
                self.parts.append("\n\n")
        elif tag == "pre":
            self.parts.append("\n```\n\n")
            self.in_pre = False
        elif tag == "code" and not self.in_pre:
            self._write("`")
        elif tag == "a":
            text = "".join(self.link_text).strip()
            href = _clean_href(self.href or "")
            # Zonder tekst (een downloadicoon) stond de url al bij de vorige link.
            if text and href and not href.startswith(("#", "javascript:", "mailto:")) and href != text:
                self._write(f" ({href})")
            self.href = None
        elif tag in {"td", "th"} and self.cell is not None:
            cell = " ".join("".join(self.cell).split())
            self.cell = None
            if self.row is not None:
                self.row.append(cell)
        elif tag == "tr" and self.row is not None:
            self.parts.append("\n" + " | ".join(self.row))
            self.row = None

    def handle_data(self, data: str) -> None:
        if self.skipping:
            return
        if self.in_pre:
            self.parts.append(data)
            return
        text = re.sub(r"\s+", " ", data.replace("\xa0", " "))
        if text.strip() and self.bold == 0:
            self.paragraph_bold_only = False
        if not text.strip() and (not self.parts or self.parts[-1].endswith((" ", "\n"))):
            return
        if self.after_bullet:
            text = text.lstrip()
            self.after_bullet = not text
        self._write(text)


_NESTED_ITEM_RE = re.compile(r"^\s+(?:-|\d+\.)\s")


def html_to_markdown(html_text: str | None) -> str:
    writer = _MarkdownWriter()
    writer.feed(html_text or "")
    writer.close()

    lines: list[str] = []
    in_code = False
    for line in "".join(writer.parts).splitlines():
        line = line.rstrip()
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and not _NESTED_ITEM_RE.match(line):
            # Een spatie vooraan is een restant van inline-opmaak, behalve bij
            # code en bij een ingesprongen lijstpunt.
            line = line.lstrip()
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
