"""Which media download failures are worth another attempt."""

from types import SimpleNamespace

import pytest
import requests

import utils.media_downloader as md


URL = "https://site.test/photo.jpg"


@pytest.fixture
def server(monkeypatch):
    """Answers each request from a list, recording the calls and the waits."""
    state = SimpleNamespace(answers=[], calls=0, waits=[])

    def fake_get(url, **kwargs):
        answer = state.answers[min(state.calls, len(state.answers) - 1)]
        state.calls += 1
        if isinstance(answer, Exception):
            raise answer

        def raise_for_status():
            if answer >= 400:
                raise requests.HTTPError(f"HTTP {answer}")

        return SimpleNamespace(status_code=answer, raise_for_status=raise_for_status)

    monkeypatch.setattr(md.requests, "get", fake_get)
    monkeypatch.setattr(md.time, "sleep", state.waits.append)
    return state


def test_success_needs_one_request(server):
    server.answers = [200]

    assert md._fetch_with_retry(URL, {}).status_code == 200
    assert server.calls == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 501])
def test_permanent_status_fails_at_once(server, status):
    server.answers = [status]

    with pytest.raises(requests.HTTPError):
        md._fetch_with_retry(URL, {})

    assert server.calls == 1
    assert server.waits == []


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_temporary_status_is_tried_again(server, status):
    server.answers = [status, 200]

    assert md._fetch_with_retry(URL, {}).status_code == 200
    assert server.calls == 2


def test_network_failure_is_tried_again(server):
    server.answers = [requests.ConnectionError("reset"), 200]

    assert md._fetch_with_retry(URL, {}).status_code == 200
    assert server.calls == 2


def test_exhausted_status_retries_raise_after_backing_off(server):
    server.answers = [503]

    with pytest.raises(requests.HTTPError):
        md._fetch_with_retry(URL, {})

    assert server.calls == 4
    assert server.waits == [1.0, 2.0, 4.0]


def test_exhausted_network_retries_raise_the_last_failure(server):
    server.answers = [requests.ConnectionError("reset")]

    with pytest.raises(requests.ConnectionError):
        md._fetch_with_retry(URL, {}, max_retries=1)

    assert server.calls == 2
