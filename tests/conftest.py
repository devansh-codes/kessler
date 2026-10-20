from __future__ import annotations

from pathlib import Path

import httpx
import pytest

FIX = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIX / name).read_text()


class Router:
    """Recorded-fixture transport: maps URL substrings to (status, body). Counts calls."""

    def __init__(self, routes: dict[str, tuple[int, str]]):
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        for frag, (status, body) in self.routes.items():
            if frag in url:
                return httpx.Response(status, text=body)
        return httpx.Response(404, text="not found")

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIX
