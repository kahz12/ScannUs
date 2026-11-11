"""Holehe email enumeration, with the holehe process and the cache replaced by fakes."""

import csv
import os

import pytest

from core import planner, throttle
from core.findings import FindingsHub
from search import email_enum as ee


EMAIL = "alice@acme-corp.io"
FIELDS = ["name", "domain", "method", "frequent_rate_limit", "rateLimit", "exists",
          "emailrecovery", "phoneNumber", "others"]


def row(name, exists=False, rate_limit=False):
    return {"name": name, "domain": f"{name}.com", "method": "register",
            "frequent_rate_limit": "False", "rateLimit": str(rate_limit),
            "exists": str(exists), "emailrecovery": "", "phoneNumber": "", "others": ""}


MIXED = [row("twitter", exists=True), row("amazon"), row("instagram", rate_limit=True)]
NONE_CHECKED = [row("twitter", rate_limit=True), row("amazon", rate_limit=True)]


class FakeCache:
    def __init__(self):
        self.store = {}

    @staticmethod
    def make_key(*parts):
        return "|".join(str(p) for p in parts)

    def get(self, namespace, key):
        return self.store.get((namespace, key))

    def set(self, namespace, key, value, ttl=None):
        self.store[(namespace, key)] = value


class NoWait:
    def wait(self):
        pass


@pytest.fixture
def holehe(monkeypatch, tmp_path):
    """Fakes the holehe process; set ``.rows`` to the CSV rows it writes."""
    runs = []

    def run(cmd, cwd, **kwargs):
        runs.append(cmd)
        if runs.rows is not None:
            path = os.path.join(cwd, f"holehe_1_{EMAIL}_results.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(runs.rows)

    runs = type("Runs", (list,), {})()
    runs.rows = MIXED
    runs.cache = FakeCache()
    monkeypatch.setattr(ee.subprocess, "run", run)
    monkeypatch.setenv("SCANNUS_CACHE_DISABLE", "1")
    monkeypatch.setattr(ee, "get_cache", lambda: runs.cache, raising=False)
    monkeypatch.setattr(ee, "HOLEHE_AVAILABLE", True)
    monkeypatch.setattr(ee, "_HOLEHE_BIN", "holehe")
    monkeypatch.setattr(ee, "DIR_REPORTS", str(tmp_path))
    monkeypatch.setattr(throttle, "get_bucket", lambda namespace, rate=None: NoWait())
    return runs


def test_holehe_runs_without_its_timeout_flag(holehe):
    ee.enumerate_email(EMAIL)

    assert holehe[0] == ["holehe", EMAIL, "--csv", "--no-color", "--no-clear"]


def test_each_service_is_claimed_available_or_unchecked(holehe):
    rows = ee.enumerate_email(EMAIL)

    assert {r["service"]: r["status"] for r in rows} == {
        "twitter": "claimed", "amazon": "available", "instagram": "unchecked",
    }
    assert [r["service"] for r in rows if r["rate_limited"]] == ["instagram"]


def test_only_used_still_returns_every_service(holehe):
    rows = ee.email_enum(EMAIL, only_used=True, save_json=False)

    assert len(rows) == 3


def test_saved_report_holds_the_shown_rows(holehe, tmp_path):
    ee.email_enum(EMAIL, only_used=True)

    saved = (tmp_path / "email_alice_acme_corp_io.json").read_text(encoding="utf-8")
    assert '"twitter"' in saved
    assert '"amazon"' not in saved


@pytest.mark.parametrize("rows", [NONE_CHECKED, None])
def test_no_service_checked_is_a_failure(holehe, rows):
    holehe.rows = rows

    assert ee.email_enum(EMAIL, save_json=False) is None


def test_runs_where_no_service_answered_are_not_cached(holehe):
    holehe.rows = NONE_CHECKED
    ee.enumerate_email(EMAIL)
    ee.enumerate_email(EMAIL)

    assert len(holehe) == 2
    assert holehe.cache.store == {}


def test_answered_runs_are_cached(holehe):
    first = ee.enumerate_email(EMAIL)
    second = ee.enumerate_email(EMAIL)

    assert len(holehe) == 1
    assert second == first


def test_hub_takes_only_the_services_where_the_email_is_registered(holehe):
    hub = FindingsHub()

    added = hub.ingest_email_enum(ee.enumerate_email(EMAIL))

    assert added == 1
    assert [f.value for f in hub.of_kind("domain")] == ["twitter.com"]


class TestPlannerTool:
    @pytest.fixture(autouse=True)
    def own_hub(self, monkeypatch):
        monkeypatch.setattr(planner, "get_hub", FindingsHub)

    def test_summary_counts_the_unchecked_services(self, holehe):
        result = planner.TOOL_DISPATCH["email_enum"]({"email": EMAIL}, None)

        assert result["status"] == "ok"
        assert result["summary"].startswith(f"email_enum: 1 service registration(s) found for {EMAIL}")
        assert "1 of 3 service(s) could not be checked" in result["summary"]
        assert result["data"]["unchecked"] == 1
        assert [r["service"] for r in result["data"]["records"]] == ["twitter"]

    def test_no_service_checked_is_reported_as_a_failure(self, holehe):
        holehe.rows = NONE_CHECKED

        result = planner.TOOL_DISPATCH["email_enum"]({"email": EMAIL}, None)

        assert result["status"] == "error"
        assert "could not check any service" in result["summary"]
