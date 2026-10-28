
    
  
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api


class FakeRedis:
    """Small fake for testing the rate-limit helper without a Redis server."""

    def __init__(self, window=60):
        self.window = window
        self.counts = {}
        self.fail = False

    def eval(self, script, numkeys, key, window_seconds):
        if self.fail:
            raise ConnectionError("Redis unavailable")
        assert numkeys == 1
        count = self.counts.get(key, 0) + 1
        self.counts[key] = count
        return [count, self.window]


def request_from(ip="192.0.2.10"):
    return SimpleNamespace(client=SimpleNamespace(host=ip))


def test_allows_requests_within_limit(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setitem(api.R, "redis", fake)

    for _ in range(3):
        api.enforce_rate_limit(request_from(), "messages", limit=3)


def test_rejects_request_over_limit_with_429_and_retry_after(monkeypatch):
    fake = FakeRedis(window=37)
    monkeypatch.setitem(api.R, "redis", fake)

    for _ in range(2):
        api.enforce_rate_limit(request_from(), "messages", limit=2)

    with pytest.raises(HTTPException) as exc_info:
        api.enforce_rate_limit(request_from(), "messages", limit=2)

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "37"
    assert exc_info.value.detail["error"] == "rate_limit_exceeded"


def test_limits_are_separate_per_client_ip(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setitem(api.R, "redis", fake)

    api.enforce_rate_limit(request_from("192.0.2.10"), "messages", limit=1)
    api.enforce_rate_limit(request_from("192.0.2.11"), "messages", limit=1)


def test_limits_are_separate_per_endpoint_bucket(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setitem(api.R, "redis", fake)

    api.enforce_rate_limit(request_from(), "messages", limit=1)
    api.enforce_rate_limit(request_from(), "create_game", limit=1)


def test_fails_open_when_redis_is_not_configured(monkeypatch):
    monkeypatch.delitem(api.R, "redis", raising=False)
    api.enforce_rate_limit(request_from(), "messages", limit=1)


def test_fails_open_when_redis_raises(monkeypatch):
    fake = FakeRedis()
    fake.fail = True
    monkeypatch.setitem(api.R, "redis", fake)

    # Redis errors are logged and do not break the app's request handling.
    api.enforce_rate_limit(request_from(), "messages", limit=1)

