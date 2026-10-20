from __future__ import annotations

import httpx
import pytest

from kessler.http import ERROR_BUDGET, USER_AGENT, HttpStop, PoliteClient
from tests.conftest import Router

URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=CSV"


class Clock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def make(tmp_path, router, clock=None):
    return PoliteClient(tmp_path, transport=router.transport(), now=clock or Clock())


def test_cache_prevents_second_request_within_ttl(tmp_path):
    r = Router({"gp.php": (200, "OBJECT_NAME\nX\n")})
    clock = Clock()
    c = make(tmp_path, r, clock)
    assert not c.get(URL).from_cache
    clock.t += 3600  # 1 h later: still cached
    assert c.get(URL).from_cache
    assert len(r.calls) == 1
    clock.t += 3601  # > 2 h: refetch allowed
    assert not c.get(URL).from_cache
    assert len(r.calls) == 2


def test_cache_shared_between_client_instances(tmp_path):
    r = Router({"gp.php": (200, "body")})
    clock = Clock()
    make(tmp_path, r, clock).get(URL)
    c2 = make(tmp_path, r, clock)
    c2.get(URL)
    assert len(r.calls) == 1 and c2.network_calls() == 0


def test_403_stops_after_one_request(tmp_path):
    r = Router({"celestrak.org": (403, "Forbidden")})
    c = make(tmp_path, r)
    with pytest.raises(HttpStop) as e:
        c.get(URL)
    assert e.value.status == 403
    with pytest.raises(HttpStop):
        c.get(URL.replace("25544", "100472"))
    assert len(r.calls) == 1, "must never retry or continue after a non-200"


def test_redirect_is_an_error_not_followed(tmp_path):
    r = Router({"celestrak.org": (301, "")})
    c = make(tmp_path, r)
    with pytest.raises(HttpStop):
        c.get(URL)
    assert len(r.calls) == 1


def test_forbidden_and_unknown_hosts_refused_without_network(tmp_path):
    r = Router({})
    c = make(tmp_path, r)
    for bad in [
        "https://celestrak.com/NORAD/elements/gp.php?CATNR=1",
        "http://celestrak.org/x",
        "https://example.org/x",
    ]:
        with pytest.raises(HttpStop):
            c.get(bad)
    assert r.calls == []


def test_error_budget_persists_across_clients(tmp_path):
    clock = Clock()
    for i in range(ERROR_BUDGET):
        c = make(tmp_path, Router({"celestrak.org": (404, "")}), clock)
        with pytest.raises(HttpStop):
            c.get(URL + f"&n={i}")
    r = Router({"celestrak.org": (200, "ok")})
    with pytest.raises(HttpStop, match="budget"):
        make(tmp_path, r, clock).get(URL + "&fresh=1")
    assert r.calls == []
    clock.t += 2 * 3600 + 1  # ledger window expires
    assert make(tmp_path, r, clock).get(URL + "&fresh=1").text == "ok"


def test_user_agent_has_contact_url(tmp_path):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["ua"] = req.headers["user-agent"]
        return httpx.Response(200, text="x")

    PoliteClient(tmp_path, transport=httpx.MockTransport(handler)).get(URL)
    assert seen["ua"] == USER_AGENT and "+https://github.com/" in USER_AGENT
