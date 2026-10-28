"""Een stub-`opener` voor de Canvas-client: pad → antwoord, zonder netwerk.

Wat een route mag zijn:
- een dict of list: JSON-antwoord;
- bytes: een ruwe download;
- een int: die HTTP-status als fout;
- `Paged([...])`: een gepagineerde lijst; de stub zet zelf de Link-header.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from email.message import Message
from typing import Any


@dataclass
class Paged:
    pages: list[list]


@dataclass
class Call:
    path: str
    params: dict[str, list[str]]
    header: str | None


@dataclass
class _Response:
    body: bytes
    link: str = ""

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if not hasattr(self, "_stream"):
            self._stream = io.BytesIO(self.body)
        return self._stream.read(size)

    @property
    def headers(self) -> Message:
        message = Message()
        if self.link:
            message["Link"] = self.link
        return message


@dataclass
class CanvasStub:
    routes: dict[str, Any]
    calls: list[Call] = field(default_factory=list)

    def __call__(self, request, timeout=None):
        parsed = urllib.parse.urlsplit(request.full_url)
        path = parsed.path.split("/api/v1/", 1)[1] if "/api/v1/" in parsed.path else parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        self.calls.append(Call(path, params, request.get_header("Authorization")))

        if path not in self.routes:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", Message(), None)
        route = self.routes[path]
        if isinstance(route, int):
            raise urllib.error.HTTPError(request.full_url, route, "error", Message(), None)
        if isinstance(route, bytes):
            return _Response(route)
        if isinstance(route, Paged):
            page = int(params.get("page", ["1"])[0])
            body = route.pages[page - 1]
            link = ""
            if page < len(route.pages):
                query = dict(urllib.parse.parse_qsl(parsed.query))
                query["page"] = str(page + 1)
                next_url = urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))
                link = f'<{next_url}>; rel="next", <{request.full_url}>; rel="current"'
            return _Response(json.dumps(body).encode(), link)
        return _Response(json.dumps(route).encode())

    def paths(self) -> list[str]:
        return [call.path for call in self.calls]


def canvas_opener(routes: dict[str, Any]) -> CanvasStub:
    return CanvasStub(routes)
