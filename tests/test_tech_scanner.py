import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from requests.structures import CaseInsensitiveDict

from analysis import tech_scanner


URL = "https://test.invalid/"


def test_wappalyzer_backend_loads():
    assert tech_scanner._WAPPALYZER_FLAVOUR == "python-Wappalyzer"


def test_importing_the_scanner_prints_no_library_warnings():
    result = subprocess.run(
        [sys.executable, "-c", "import analysis.tech_scanner"],
        cwd=Path(tech_scanner.__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Warning" not in result.stderr


def test_wappalyzer_sends_browser_headers_and_detects_stack(monkeypatch):
    calls = []
    html = '<html><script src="/js/jquery-1.8.2.min.js"></script></html>'

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        headers = CaseInsensitiveDict({"Server": "nginx"})
        return SimpleNamespace(url=url, text=html, headers=headers)

    monkeypatch.setattr(tech_scanner.requests, "get", fake_get)

    detected = {name: version for name, version, _ in tech_scanner._detect_wappalyzer(URL)}

    assert calls[0][0] == URL
    assert calls[0][1]["headers"] == tech_scanner._HEADERS
    assert "Nginx" in detected
    assert detected["jQuery"] == "1.8.2"


def test_webtech_is_asked_for_json_and_its_report_is_parsed(monkeypatch):
    seen = {}

    class FakeWebTech:
        def __init__(self, options):
            seen["options"] = options

        def start_from_url(self, url, timeout):
            return {
                "tech": [{"name": "Nginx", "version": None}, {"name": "PHP", "version": "8.3"}],
                "headers": [{"name": "x-custom", "value": "1"}],
            }

    monkeypatch.setattr(tech_scanner, "WebTech", FakeWebTech)

    assert tech_scanner._detect_webtech(URL) == [
        ("Nginx", "", "Web Server"),
        ("PHP", "8.3", "Programming Language"),
    ]
    assert seen["options"]["json"] is True


def test_legacy_webtech_dict_report_is_still_parsed():
    assert tech_scanner._parse_webtech_report({"WordPress": "6.5"}) == [
        ("WordPress", "6.5", "CMS"),
    ]


def test_falls_back_to_webtech_when_wappalyzer_finds_nothing(monkeypatch):
    found = [("Nginx", "", "Web Server")]
    monkeypatch.setattr(tech_scanner, "_detect_wappalyzer", lambda url: [])
    monkeypatch.setattr(tech_scanner, "_detect_webtech", lambda url: found)

    assert tech_scanner.detect_technologies(URL) == ("WebTech", found)
