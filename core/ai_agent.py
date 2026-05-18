"""
core/ai_agent.py — AI provider wrappers with streaming support.

Providers:
  - OpenAIGenerator  — OpenAI Chat Completions (streaming)
  - GeminiGenerator  — Google Gemini (streaming)

Both generators implement a consistent interface:
  generate(prompt)         → str   (full response, buffered)
  stream(prompt)           → Iterator[str] (token-by-token chunks)
"""

import os
import re
import json
import time
import random
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Iterator

from cli.ui import console, THEME


# ---------------------------------------------------------------------------
# Transient-failure retry helper (exponential backoff with jitter)
# ---------------------------------------------------------------------------

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_DELAY = 1.0
_DEFAULT_MAX_DELAY = 30.0


def _is_transient_error(exc: Exception) -> bool:
    """Best-effort detection of retryable provider errors across SDK variants."""
    msg = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status < 600):
        return True
    transient_markers = (
        "timeout", "timed out", "rate limit", "temporarily", "unavailable",
        "overloaded", "connection reset", "econnreset", "502", "503", "504",
    )
    return any(marker in msg for marker in transient_markers)


def _retry_with_backoff(
    fn: Callable,
    *args,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    base_delay: float = _DEFAULT_BASE_DELAY,
    max_delay: float = _DEFAULT_MAX_DELAY,
    label: str = "provider call",
    **kwargs,
):
    """
    Invokes ``fn(*args, **kwargs)`` with exponential-backoff retry on transient
    errors. Non-transient errors propagate immediately.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt >= max_retries or not _is_transient_error(e):
                raise
            delay = min(max_delay, base_delay * (2 ** attempt))
            delay += random.uniform(0, delay * 0.25)  # 0–25% jitter
            console.print(
                f"  [{THEME['DIM']}]↻ {label}: transient error "
                f"(attempt {attempt + 1}/{max_retries}) — retrying in {delay:.1f}s[/]"
            )
            time.sleep(delay)
    if last_exc:
        raise last_exc


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------

class OpenAIGenerator:
    """
    OpenAI Chat Completions wrapper.
    Supports both buffered and streaming generation.
    """

    def __init__(self, model_name: str = "gpt-4o", timeout: float = 60.0):
        self.model_name = model_name
        self.timeout = timeout
        from openai import OpenAI as _OpenAI
        self.client = _OpenAI(timeout=timeout)

    def _open_stream(self, prompt: str):
        return self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            timeout=self.timeout,
        )

    def generate(self, prompt: str) -> str:
        """Buffered call that internally streams + renders to the terminal."""
        return "".join(self.stream(prompt, render=True))

    def stream(self, prompt: str, render: bool = False) -> Iterator[str]:
        """
        Streams the model response token-by-token, with retry/backoff on
        transient provider errors.

        Args:
            prompt: The instruction for the model.
            render:  If True, tokens are printed live to the terminal.

        Yields:
            str: Individual text chunks as they arrive.
        """
        console.print(
            f"  [{THEME['DIM']}]⟳ Generating with OpenAI ({self.model_name})…[/]"
        )

        stream = _retry_with_backoff(
            self._open_stream, prompt, label=f"OpenAI {self.model_name}",
        )

        if render:
            console.print()
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                if render:
                    print(delta, end="", flush=True)
                yield delta
        if render:
            print()


# ---------------------------------------------------------------------------
# Gemini provider
# ---------------------------------------------------------------------------

class GeminiGenerator:
    """
    Google Gemini API wrapper via the `google-genai` SDK.
    Supports buffered and streaming generation.
    """

    def __init__(self, model_name: str = "gemini-2.0-flash", timeout: float = 60.0):
        self.model_name = model_name
        self.timeout = timeout
        self.client = None
        self._initialize_client()

    def _initialize_client(self):
        """Bootstrap the Gemini client from the environment API key."""
        api_key = os.getenv("GOOGLE_API_KEY_FOR_GEMINI")
        if api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=api_key)
            except Exception as e:
                console.print(f"  [{THEME['ERROR']}]✘[/]  Gemini init error: {e}")

    def _open_stream(self, prompt: str):
        return self.client.models.generate_content_stream(
            model=self.model_name,
            contents=prompt,
        )

    def generate(self, prompt: str) -> str:
        """Streams the response, rendering tokens live; returns full text."""
        return "".join(self.stream(prompt, render=True))

    def stream(self, prompt: str, render: bool = False) -> Iterator[str]:
        """
        Yields text chunks from the Gemini streaming API with retry/backoff.

        Args:
            prompt: Prompt text.
            render:  If True, tokens are printed live to the terminal.
        """
        if not self.client:
            self._initialize_client()
            if not self.client:
                yield "Error: Gemini client not initialized — check GOOGLE_API_KEY_FOR_GEMINI."
                return

        console.print(
            f"  [{THEME['DIM']}]⟳ Generating with Gemini ({self.model_name})…[/]"
        )

        try:
            stream = _retry_with_backoff(
                self._open_stream, prompt, label=f"Gemini {self.model_name}",
            )
        except AttributeError:
            try:
                response = _retry_with_backoff(
                    self.client.models.generate_content,
                    model=self.model_name, contents=prompt,
                    label=f"Gemini {self.model_name}",
                )
                text = response.text or ""
                if render:
                    print(text, flush=True)
                yield text
            except Exception as e:
                yield f"[Gemini error: {e}]"
            return
        except Exception as e:
            yield f"[Gemini error: {e}]"
            return

        if render:
            console.print()
        for chunk in stream:
            text = chunk.text or ""
            if text:
                if render:
                    print(text, end="", flush=True)
                yield text
        if render:
            print()


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------

class AnthropicGenerator:
    """
    Anthropic Claude wrapper via the ``anthropic`` Python SDK.

    Defaults to the latest Sonnet (claude-sonnet-4-6) for a good
    quality/cost balance. Override with the ``ANTHROPIC_MODEL`` env var or
    by passing ``model_name`` directly.
    """

    DEFAULT_MODEL    = "claude-sonnet-4-6"
    DEFAULT_MAX_TOK  = 4096

    def __init__(self, model_name: str | None = None, timeout: float = 60.0,
                 max_tokens: int = DEFAULT_MAX_TOK):
        self.model_name = (model_name
                           or os.getenv("ANTHROPIC_MODEL")
                           or self.DEFAULT_MODEL)
        self.timeout    = timeout
        self.max_tokens = max_tokens
        try:
            from anthropic import Anthropic as _Anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic SDK not installed — install with: pip install anthropic"
            ) from e
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set — run `python main.py -c` to configure."
            )
        self.client = _Anthropic(api_key=api_key, timeout=timeout)

    def generate(self, prompt: str) -> str:
        """Streams the response, rendering tokens live; returns full text."""
        return "".join(self.stream(prompt, render=True))

    def stream(self, prompt: str, render: bool = False) -> Iterator[str]:
        """Yields text chunks from Claude's streaming API with retry/backoff."""
        console.print(
            f"  [{THEME['DIM']}]⟳ Generating with Claude ({self.model_name})…[/]"
        )

        def _open():
            return self.client.messages.stream(
                model=self.model_name,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

        try:
            ctx = _retry_with_backoff(_open, label=f"Claude {self.model_name}")
        except Exception as e:
            yield f"[Claude error: {e}]"
            return

        if render:
            console.print()
        try:
            with ctx as stream:
                for text in stream.text_stream:
                    if not text:
                        continue
                    if render:
                        print(text, end="", flush=True)
                    yield text
        except Exception as e:
            yield f"[Claude stream error: {e}]"
        if render:
            print()


# ---------------------------------------------------------------------------
# Ollama provider — local inference, no API key required
# ---------------------------------------------------------------------------

class OllamaGenerator:
    """
    Ollama HTTP-API wrapper for local model inference.

    No SDK / API key required — talks straight to ``http://localhost:11434``
    (override with ``OLLAMA_HOST``). The model must already be pulled
    (``ollama pull <model>``); the default is ``llama3`` but any installed
    model works via ``OLLAMA_MODEL`` or the constructor.
    """

    DEFAULT_HOST  = "http://localhost:11434"
    DEFAULT_MODEL = "llama3"

    def __init__(self, model_name: str | None = None, host: str | None = None,
                 timeout: float = 120.0):
        self.model_name = (model_name
                           or os.getenv("OLLAMA_MODEL")
                           or self.DEFAULT_MODEL)
        self.host = (host or os.getenv("OLLAMA_HOST")
                     or self.DEFAULT_HOST).rstrip("/")
        self.timeout = timeout
        # Lazy import so the module load doesn't depend on `requests` here
        import requests as _requests
        self._requests = _requests

    def _ping(self) -> bool:
        """Quick health check; returns True if the daemon answers ``/api/tags``."""
        try:
            r = self._requests.get(f"{self.host}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def generate(self, prompt: str) -> str:
        """Streams the response, rendering tokens live; returns full text."""
        return "".join(self.stream(prompt, render=True))

    def stream(self, prompt: str, render: bool = False) -> Iterator[str]:
        """
        Streams from Ollama's ``/api/generate`` endpoint. Each line is a JSON
        object with a ``response`` token; the final object has ``done: true``.
        """
        if not self._ping():
            yield (f"[Ollama error: daemon not reachable at {self.host}. "
                   f"Start it with `ollama serve` or set OLLAMA_HOST.]")
            return

        console.print(
            f"  [{THEME['DIM']}]⟳ Generating with Ollama "
            f"({self.model_name} @ {self.host})…[/]"
        )

        try:
            response = _retry_with_backoff(
                self._requests.post,
                f"{self.host}/api/generate",
                json={"model": self.model_name, "prompt": prompt, "stream": True},
                timeout=self.timeout,
                stream=True,
                label=f"Ollama {self.model_name}",
            )
            response.raise_for_status()
        except Exception as e:
            yield f"[Ollama error: {e}]"
            return

        if render:
            console.print()
        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                try:
                    payload = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if "error" in payload:
                    yield f"[Ollama error: {payload['error']}]"
                    break
                text = payload.get("response", "")
                if text:
                    if render:
                        print(text, end="", flush=True)
                    yield text
                if payload.get("done"):
                    break
        except Exception as e:
            yield f"[Ollama stream error: {e}]"
        if render:
            print()


# ---------------------------------------------------------------------------
# Query Planner — dataclasses, tool catalog, dispatchers
# ---------------------------------------------------------------------------

@dataclass
class PlanStep:
    """One atomic step in an executable OSINT plan."""
    tool: str
    args: dict = field(default_factory=dict)
    rationale: str = ""
    expected: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PlanStep":
        return cls(
            tool=str(d.get("tool", "")).strip(),
            args=dict(d.get("args") or {}),
            rationale=str(d.get("rationale", "")).strip(),
            expected=str(d.get("expected", "")).strip(),
        )


@dataclass
class QueryPlan:
    """LLM-synthesised investigation plan for a natural-language goal."""
    goal: str
    summary: str = ""
    steps: list[PlanStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "goal":    self.goal,
            "summary": self.summary,
            "steps":   [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: dict, goal: str = "") -> "QueryPlan":
        steps_raw = d.get("steps") or []
        return cls(
            goal=d.get("goal") or goal or "",
            summary=str(d.get("summary", "")).strip(),
            steps=[PlanStep.from_dict(s) for s in steps_raw if isinstance(s, dict)],
        )


# Whitelisted, read-only OSINT tools the planner may choose from.
TOOL_CATALOG: dict[str, dict] = {
    "search": {
        "desc": "Run a SERP search and return the list of titles/URLs/snippets.",
        "args": {
            "query":  "str (required) — search string, Google-Dork operators welcome",
            "engine": "str — duckduckgo | google | brave (default: duckduckgo)",
            "pages":  "int — SERP pages to retrieve (default: 1)",
        },
    },
    "deep_search": {
        "desc": "Search, then crawl each URL and extract PII + leaked secrets "
                "(emails, phones, IBANs, credit cards, DNIs, CUITs, RFCs, SSNs, "
                "CPF, SIN, AWS/GitHub/Slack/Stripe/Google API keys, JWTs, "
                "private keys, BTC/ETH wallets, public IPs).",
        "args": {
            "query":  "str (required)",
            "engine": "str (default: duckduckgo)",
        },
    },
    "extract_pii": {
        "desc": "Fetch a single URL and extract identifiers + leaked secrets "
                "(emails, phones, IBANs, credit cards, DNIs, CUITs, RFCs, SSNs, "
                "CPF, SIN, AWS/GitHub/Slack/Stripe/Google API keys, JWTs, "
                "private keys, BTC/ETH wallets, public IPs).",
        "args": {"url": "str (required)"},
    },
    "tech_scan": {
        "desc": "Fingerprint the web-technology stack of a URL (CMS, frameworks, "
                "analytics, CDNs).",
        "args": {"url": "str (required)"},
    },
    "username_enum": {
        "desc": "Enumerate social-network accounts for a handle via Sherlock/Maigret "
                "(400+ sites).",
        "args": {
            "username": "str (required)",
            "backend":  "str — auto | sherlock | maigret (default: auto)",
        },
    },
    "screenshot": {
        "desc": "Capture a full-page screenshot of a URL using a headless browser.",
        "args": {"url": "str (required)"},
    },
    "wayback": {
        "desc": "Look up the URL's history on the Wayback Machine (CDX timeline).",
        "args": {"url": "str (required)"},
    },
    "wayback_fetch": {
        "desc": "Fetch the raw archived content of a URL at a specific Wayback "
                "snapshot. Returns the visible text along with status/MIME/size.",
        "args": {
            "url":       "str (required)",
            "timestamp": "str — CDX timestamp or 'latest'|'earliest'|YYYY|YYYY-MM",
        },
    },
    "wayback_extract": {
        "desc": "Fetch a Wayback snapshot and run the full PII/secret extractor "
                "on it. Surfaces identifiers/credentials that may have been "
                "scrubbed from the live site.",
        "args": {
            "url":       "str (required)",
            "timestamp": "str — CDX timestamp or 'latest'|'earliest'|YYYY|YYYY-MM",
        },
    },
    "wayback_diff": {
        "desc": "Diff two Wayback snapshots of a URL by their visible text. "
                "Returns added/removed line counts plus a unified diff.",
        "args": {
            "url":  "str (required)",
            "ts_a": "str (required) — CDX timestamp or fuzzy spec",
            "ts_b": "str (required) — CDX timestamp or fuzzy spec",
        },
    },
    "summarize_url": {
        "desc": "Fetch a URL's main content and ask the LLM to summarise it.",
        "args": {"url": "str (required)"},
    },
    "domain_recon": {
        "desc": "Full domain recon: WHOIS + DNS + email auth + TLS + HTTP "
                "security headers + subdomains (crt.sh) [+ Shodan if key set].",
        "args": {"target": "str (required) — domain or URL"},
    },
    "whois": {
        "desc": "WHOIS lookup: registrar, creation/expiry dates, nameservers, contacts.",
        "args": {"domain": "str (required)"},
    },
    "dns_records": {
        "desc": "DNS records (A, AAAA, MX, NS, TXT, SOA, CNAME, CAA).",
        "args": {"domain": "str (required)"},
    },
    "tls_certificate": {
        "desc": "Inspect the TLS certificate of a host: subject, SANs, validity.",
        "args": {"host": "str (required)", "port": "int (default 443)"},
    },
    "http_security_headers": {
        "desc": "Report which HTTP hardening headers are present/missing on a URL.",
        "args": {"url": "str (required)"},
    },
    "subdomains": {
        "desc": "Passive subdomain enumeration via Certificate Transparency (crt.sh).",
        "args": {"domain": "str (required)"},
    },
    "reverse_image": {
        "desc": "Multi-engine reverse image search (TinEye API + Bing Visual "
                "Search API + Yandex scraping + manual lookup URLs). Every "
                "engine is independent; the manual-URL tier always returns.",
        "args": {
            "url":     "str (required) — public URL of the target image",
            "engines": "list[str] — optional whitelist: tineye | bing | yandex | manual",
        },
    },
    # --- HIBP tools ----------------------------------------------------------
    # Have I Been Pwned (hibp_*) tools give the planner breach-intelligence
    # superpowers. Two are paid (need HIBP_API_KEY), two are free. All results
    # are cached so the planner can call them repeatedly without hammering Troy.
    "hibp_account": {
        "desc": "Have I Been Pwned: list every breach (and optionally pastes) "
                "containing a target email address. Requires HIBP_API_KEY.",
        "args": {
            "email":          "str (required)",
            "include_pastes": "bool — default true",
        },
    },
    "hibp_domain": {
        # Free endpoint — no API key needed. Great for a quick first recon step
        # before deciding whether to invest in the paid per-account lookup.
        "desc": "Have I Been Pwned: list breaches affecting a domain. "
                "Free endpoint, no API key required.",
        "args": {"domain": "str (required)"},
    },
    "hibp_breach": {
        # Useful as a follow-up after hibp_account surfaces a breach name —
        # drill into the full metadata (data classes, verification status, etc.)
        # to understand *what* was stolen and calibrate risk.
        "desc": "Have I Been Pwned: detailed metadata for a single named "
                "breach (size, data classes, verified flag, description).",
        "args": {"name": "str (required) — e.g. 'Adobe', 'LinkedIn'"},
    },
    "hibp_password": {
        # k-anonymity means the plaintext never leaves the process — safe to use
        # in automated investigation plans. Prefer 'sha1' arg in plan steps
        # so the raw password doesn't appear in execution logs.
        "desc": "Pwned Passwords k-anonymity lookup: returns how many times "
                "a password has been seen across known breaches. The plaintext "
                "never leaves the process — only the first 5 chars of its "
                "SHA-1 are sent.",
        "args": {
            "password": "str — cleartext password (mutually exclusive with sha1)",
            "sha1":     "str — pre-computed 40-char SHA-1 hex (alternative)",
        },
    },
}


def _truncate(value: Any, limit: int = 220) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _format_catalog_for_prompt() -> str:
    """Human-readable tool catalog embedded into the planner prompt."""
    lines: list[str] = []
    for name, meta in TOOL_CATALOG.items():
        lines.append(f"- {name}: {meta['desc']}")
        for arg_name, arg_desc in meta["args"].items():
            lines.append(f"    · {arg_name}: {arg_desc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool dispatchers — lazy imports to avoid circular deps at import-time
# ---------------------------------------------------------------------------

def _dispatch_search(args: dict, ia_agent) -> dict:
    from cli.actions import get_search_engine
    query = (args.get("query") or "").strip()
    if not query:
        return {"status": "error", "summary": "search: missing 'query'"}
    engine = (args.get("engine") or "duckduckgo").lower()
    try:
        pages = int(args.get("pages") or 1)
    except (TypeError, ValueError):
        pages = 1
    try:
        results = get_search_engine(engine, pages, 1, "lang_es", query)
    except Exception as e:
        return {"status": "error", "summary": f"search failed: {e}"}
    top = [r.get("title", "") for r in results[:5]]
    links = [r.get("link", "") for r in results[:5]]
    return {
        "status":  "ok",
        "summary": f"{len(results)} hits · top: " + " | ".join(_truncate(t, 60) for t in top),
        "data":    {"results": results, "top_links": links},
    }


def _dispatch_deep_search(args: dict, ia_agent) -> dict:
    from cli.actions import do_deep_search
    from core import state
    query = (args.get("query") or "").strip()
    if not query:
        return {"status": "error", "summary": "deep_search: missing 'query'"}
    engine = (args.get("engine") or "duckduckgo").lower()
    try:
        do_deep_search(query, engine, pages=1, start_page=1, lang="lang_es")
    except Exception as e:
        return {"status": "error", "summary": f"deep_search failed: {e}"}
    count = len(state.ULTIMOS_RESULTADOS or [])
    return {
        "status":  "ok",
        "summary": f"deep search over {count} URLs complete",
        "data":    {"count": count},
    }


def _dispatch_extract_pii(args: dict, ia_agent) -> dict:
    from analysis.web_analyzer import get_text_from_url
    from search.smart_search import extract_information
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "extract_pii: missing 'url'"}
    text = get_text_from_url(url)
    if not text:
        return {"status": "error", "summary": f"could not fetch {url}"}
    data = extract_information(text)
    if not data:
        return {"status": "ok", "summary": f"{url}: no identifiers found", "data": {}}
    counts = {k: len(v) for k, v in data.items()}
    return {
        "status":  "ok",
        "summary": "extracted: " + ", ".join(f"{k}×{n}" for k, n in counts.items()),
        "data":    {"by_category": data, "counts": counts},
    }


def _dispatch_tech_scan(args: dict, ia_agent) -> dict:
    from analysis.tech_scanner import tech_scan
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "tech_scan: missing 'url'"}
    try:
        tech_scan(url)
    except Exception as e:
        return {"status": "error", "summary": f"tech_scan failed: {e}"}
    return {"status": "ok", "summary": f"tech_scan executed for {url}", "data": {}}


def _dispatch_username_enum(args: dict, ia_agent) -> dict:
    from search.username_enum import username_enum
    username = (args.get("username") or "").strip()
    if not username:
        return {"status": "error", "summary": "username_enum: missing 'username'"}
    backend = (args.get("backend") or "auto").lower()
    try:
        username_enum(username, backend=backend)
    except Exception as e:
        return {"status": "error", "summary": f"username_enum failed: {e}"}
    return {"status": "ok", "summary": f"username_enum completed for @{username}", "data": {}}


def _dispatch_screenshot(args: dict, ia_agent) -> dict:
    from analysis.advanced_osint import take_screenshot
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "screenshot: missing 'url'"}
    try:
        take_screenshot(url)
    except Exception as e:
        return {"status": "error", "summary": f"screenshot failed: {e}"}
    return {"status": "ok", "summary": f"screenshot captured for {url}", "data": {}}


def _dispatch_wayback(args: dict, ia_agent) -> dict:
    from analysis.advanced_osint import check_wayback_machine
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "wayback: missing 'url'"}
    try:
        check_wayback_machine(url)
    except Exception as e:
        return {"status": "error", "summary": f"wayback failed: {e}"}
    return {"status": "ok", "summary": f"wayback lookup completed for {url}", "data": {}}


def _dispatch_domain_recon(args: dict, ia_agent) -> dict:
    from analysis.domain_osint import domain_recon
    target = (args.get("target") or args.get("domain") or args.get("url") or "").strip()
    if not target:
        return {"status": "error", "summary": "domain_recon: missing 'target'"}
    try:
        report = domain_recon(target)
    except Exception as e:
        return {"status": "error", "summary": f"domain_recon failed: {e}"}
    subs = len(report.get("subdomains") or [])
    hdr  = (report.get("headers") or {}).get("score", "?")
    return {
        "status":  "ok",
        "summary": f"recon complete · {subs} subdomains · headers {hdr}",
        "data":    report,
    }


def _dispatch_whois(args: dict, ia_agent) -> dict:
    from analysis.domain_osint import whois_lookup
    domain = (args.get("domain") or args.get("target") or "").strip()
    if not domain:
        return {"status": "error", "summary": "whois: missing 'domain'"}
    info = whois_lookup(domain)
    if not info:
        return {"status": "error", "summary": f"whois: no data for {domain}"}
    return {"status": "ok",
            "summary": f"whois {domain}: registrar={info.get('registrar') or '?'}, "
                       f"expires={info.get('expires') or '?'}",
            "data":    info}


def _dispatch_dns_records(args: dict, ia_agent) -> dict:
    from analysis.domain_osint import dns_records
    domain = (args.get("domain") or args.get("target") or "").strip()
    if not domain:
        return {"status": "error", "summary": "dns_records: missing 'domain'"}
    rec = dns_records(domain)
    if not rec:
        return {"status": "error", "summary": f"dns: no records for {domain}"}
    summary = "dns " + ", ".join(f"{k}×{len(v)}" for k, v in rec.items())
    return {"status": "ok", "summary": summary, "data": rec}


def _dispatch_tls_certificate(args: dict, ia_agent) -> dict:
    from analysis.domain_osint import tls_certificate
    host = (args.get("host") or args.get("domain") or "").strip()
    if not host:
        return {"status": "error", "summary": "tls_certificate: missing 'host'"}
    try:
        port = int(args.get("port") or 443)
    except (TypeError, ValueError):
        port = 443
    cert = tls_certificate(host, port=port)
    if not cert:
        return {"status": "error", "summary": f"tls: handshake failed for {host}:{port}"}
    return {"status":  "ok",
            "summary": f"tls {host}:{port} · expires in "
                       f"{cert.get('days_left')} days · {cert.get('tls_version')}",
            "data":    cert}


def _dispatch_http_security_headers(args: dict, ia_agent) -> dict:
    from analysis.domain_osint import http_security_headers
    url = (args.get("url") or args.get("target") or "").strip()
    if not url:
        return {"status": "error", "summary": "http_security_headers: missing 'url'"}
    data = http_security_headers(url)
    if not data:
        return {"status": "error", "summary": f"headers: request failed for {url}"}
    return {"status":  "ok",
            "summary": f"headers {data.get('score')} present",
            "data":    data}


def _dispatch_subdomains(args: dict, ia_agent) -> dict:
    from analysis.domain_osint import subdomains_crtsh
    domain = (args.get("domain") or args.get("target") or "").strip()
    if not domain:
        return {"status": "error", "summary": "subdomains: missing 'domain'"}
    subs = subdomains_crtsh(domain)
    return {"status":  "ok",
            "summary": f"{len(subs)} subdomain(s) from crt.sh",
            "data":    {"subdomains": subs}}


def _dispatch_wayback_fetch(args: dict, ia_agent) -> dict:
    from analysis.advanced_osint import wayback_fetch_snapshot
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "wayback_fetch: missing 'url'"}
    ts = (args.get("timestamp") or "latest").strip()
    snap = wayback_fetch_snapshot(url, ts)
    if not snap:
        return {"status": "error", "summary": f"wayback_fetch: no snapshot for {url}"}
    return {
        "status":  "ok",
        "summary": f"snapshot {snap['date']} · {snap['mime']} · {snap['size']} bytes",
        "data":    {
            "timestamp":   snap["timestamp"],
            "date":        snap["date"],
            "archive_url": snap["archive_url"],
            "mime":        snap["mime"],
            "size":        snap["size"],
            "text":        _truncate(snap.get("text") or "", 4000),
        },
    }


def _dispatch_wayback_extract(args: dict, ia_agent) -> dict:
    from analysis.advanced_osint import wayback_extract_pii
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "wayback_extract: missing 'url'"}
    ts = (args.get("timestamp") or "latest").strip()
    result = wayback_extract_pii(url, ts)
    if not result:
        return {"status": "error",
                "summary": f"wayback_extract: no content for {url} @ {ts}"}
    counts = result.get("counts") or {}
    summary = ("extracted from " + result["date"] + ": " +
               (", ".join(f"{k}×{v}" for k, v in counts.items()) or "no identifiers"))
    return {"status": "ok", "summary": summary, "data": result}


def _dispatch_wayback_diff(args: dict, ia_agent) -> dict:
    from analysis.advanced_osint import wayback_diff
    url = (args.get("url") or "").strip()
    ts_a = (args.get("ts_a") or "").strip()
    ts_b = (args.get("ts_b") or "").strip()
    if not (url and ts_a and ts_b):
        return {"status": "error",
                "summary": "wayback_diff: requires 'url', 'ts_a', 'ts_b'"}
    result = wayback_diff(url, ts_a, ts_b)
    if not result:
        return {"status": "error",
                "summary": "wayback_diff: could not fetch one or both snapshots"}
    return {
        "status":  "ok",
        "summary": f"{result['date_a']} -> {result['date_b']}: "
                   f"+{result['added_count']} -{result['removed_count']}"
                   + (" (identical)" if result["identical"] else ""),
        "data":    result,
    }


def _dispatch_reverse_image(args: dict, ia_agent) -> dict:
    from search.reverse_image_engines import reverse_image_aggregate
    url = (args.get("url") or args.get("image_url") or "").strip()
    if not url:
        return {"status": "error", "summary": "reverse_image: missing 'url'"}
    engines = args.get("engines")
    if isinstance(engines, str):
        engines = [e.strip() for e in engines.split(",") if e.strip()]
    try:
        results = reverse_image_aggregate(url, engines=engines)
    except Exception as e:
        return {"status": "error", "summary": f"reverse_image failed: {e}"}
    by_engine: dict[str, int] = {}
    for r in results:
        by_engine[r.get("engine", "?")] = by_engine.get(r.get("engine", "?"), 0) + 1
    breakdown = ", ".join(f"{k}×{v}" for k, v in by_engine.items()) or "no results"
    return {
        "status":  "ok",
        "summary": f"reverse_image: {len(results)} entries ({breakdown})",
        "data":    {"results": results, "by_engine": by_engine},
    }


def _dispatch_summarize_url(args: dict, ia_agent) -> dict:
    from analysis.web_analyzer import get_text_from_url, summarize_text_with_ia
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "summarize_url: missing 'url'"}
    if ia_agent is None:
        return {"status": "error", "summary": "summarize_url: no AI agent available"}
    text = get_text_from_url(url)
    if not text:
        return {"status": "error", "summary": f"could not fetch {url}"}
    try:
        summary = summarize_text_with_ia(text, ia_agent)
    except Exception as e:
        return {"status": "error", "summary": f"summarize failed: {e}"}
    return {"status": "ok", "summary": _truncate(summary, 240), "data": {"full": summary}}


def _dispatch_hibp_account(args: dict, ia_agent) -> dict:
    """AI plan dispatcher for the hibp_account tool.

    Validates args, calls the data + render functions, and packages
    the result into the standard {status, summary, data} shape that
    the ReAct executor expects. The ``include_pastes`` arg accepts
    truthy strings ("true", "yes", "1") as well as booleans because
    LLMs sometimes serialise booleans as strings. We handle both.
    """
    from analysis.hibp import (hibp_breached_account, hibp_pastes_for_account,
                               render_breached_account, render_pastes_for_account)
    email = (args.get("email") or "").strip()
    if not email:
        # Can't look up an account with no email. Tell the planner to retry.
        return {"status": "error", "summary": "hibp_account: missing 'email'"}
    include_pastes = args.get("include_pastes", True)
    # Handle the case where the LLM passes "false" as a string instead of False.
    if isinstance(include_pastes, str):
        include_pastes = include_pastes.strip().lower() not in ("0", "false", "no", "")
    breaches = hibp_breached_account(email)
    if breaches is None:
        # None means the API key is absent or the request failed — not just "no results".
        return {"status": "error",
                "summary": "hibp_account: API key missing or request failed"}
    render_breached_account(email, breaches)
    pastes: list[dict] = []
    if include_pastes:
        pastes_raw = hibp_pastes_for_account(email)
        if pastes_raw is None:
            pastes_raw = []  # API key issue for pastes; breaches still valid above
        render_pastes_for_account(email, pastes_raw)
        pastes = pastes_raw
    return {
        "status":  "ok",
        "summary": f"{email}: {len(breaches)} breach(es), {len(pastes)} paste(s)",
        "data":    {
            "email":        email,
            "breaches":     breaches,
            "pastes":       pastes,
            "breach_count": len(breaches),
            "paste_count":  len(pastes),
        },
    }


def _dispatch_hibp_domain(args: dict, ia_agent) -> dict:
    """AI plan dispatcher for the hibp_domain tool.

    The free HIBP domain endpoint, so no API key gating here.
    The planner can use this to check whether a target domain has
    ever suffered a recorded breach without needing credentials.
    """
    from analysis.hibp import hibp_breaches_for_domain, render_breaches_for_domain
    domain = (args.get("domain") or "").strip()
    if not domain:
        return {"status": "error", "summary": "hibp_domain: missing 'domain'"}
    breaches = hibp_breaches_for_domain(domain)
    render_breaches_for_domain(domain, breaches)
    return {
        "status":  "ok",
        "summary": f"{domain}: {len(breaches)} breach(es) recorded",
        "data":    {"domain": domain, "breaches": breaches},
    }


def _dispatch_hibp_breach(args: dict, ia_agent) -> dict:
    """AI plan dispatcher for the hibp_breach tool.

    Fetches the full metadata for a single named breach. Useful when
    the planner has spotted a breach name (e.g. from hibp_account results)
    and wants to understand what data classes were exposed before deciding
    the next investigation step.
    """
    from analysis.hibp import hibp_breach
    name = (args.get("name") or "").strip()
    if not name:
        return {"status": "error", "summary": "hibp_breach: missing 'name'"}
    info = hibp_breach(name)
    if not info:
        # 404 from HIBP — name doesn't match any known breach identifier
        return {"status": "error", "summary": f"hibp_breach: no record for '{name}'"}
    return {
        "status":  "ok",
        # Summary is concise for the ReAct log; full metadata lives in "data".
        "summary": (f"{info.get('Name')} ({info.get('BreachDate')}): "
                    f"{info.get('PwnCount', 0):,} accounts, "
                    f"data classes: {', '.join(info.get('DataClasses') or [])[:80]}"),
        "data":    info,
    }


def _dispatch_hibp_password(args: dict, ia_agent) -> dict:
    """AI plan dispatcher for the hibp_password tool.

    Accepts either a ``password`` (cleartext — will be hashed locally before
    any network call) or a pre-computed ``sha1`` hex string. The ``via`` field
    in the returned data records which path was taken, useful for audit logs.

    Reminder: this dispatcher should NOT be called with the user's actual
    password in a plan step that gets logged. Prefer the ``sha1`` arg in
    automated contexts where the hash can be computed upstream.
    """
    from analysis.hibp import (hibp_password_pwned, hibp_password_pwned_hash,
                               render_password_pwned)
    password = args.get("password") or ""
    sha1 = (args.get("sha1") or "").strip()
    if not (password or sha1):
        # Neither argument provided — tell the planner it needs one or the other.
        return {"status": "error",
                "summary": "hibp_password: provide either 'password' or 'sha1'"}
    # Prefer sha1 if supplied (avoids re-hashing and is safer in log contexts).
    count = (hibp_password_pwned_hash(sha1) if sha1
             else hibp_password_pwned(password))
    render_password_pwned(count)
    if count is None:
        return {"status": "error", "summary": "hibp_password: lookup failed"}
    return {
        "status":  "ok",
        "summary": (f"password seen {count:,} time(s) in HIBP corpus"
                    if count else "password not in any known HIBP breach"),
        "data":    {"count": count, "via": "sha1" if sha1 else "password"},
    }


TOOL_DISPATCH: dict[str, Callable[..., dict]] = {
    "search":                _dispatch_search,
    "deep_search":           _dispatch_deep_search,
    "extract_pii":           _dispatch_extract_pii,
    "tech_scan":             _dispatch_tech_scan,
    "username_enum":         _dispatch_username_enum,
    "screenshot":            _dispatch_screenshot,
    "wayback":               _dispatch_wayback,
    "wayback_fetch":         _dispatch_wayback_fetch,
    "wayback_extract":       _dispatch_wayback_extract,
    "wayback_diff":          _dispatch_wayback_diff,
    "summarize_url":         _dispatch_summarize_url,
    "domain_recon":          _dispatch_domain_recon,
    "whois":                 _dispatch_whois,
    "dns_records":           _dispatch_dns_records,
    "tls_certificate":       _dispatch_tls_certificate,
    "http_security_headers": _dispatch_http_security_headers,
    "subdomains":            _dispatch_subdomains,
    "reverse_image":         _dispatch_reverse_image,
    "hibp_account":          _dispatch_hibp_account,
    "hibp_domain":           _dispatch_hibp_domain,
    "hibp_breach":           _dispatch_hibp_breach,
    "hibp_password":         _dispatch_hibp_password,
}


# ---------------------------------------------------------------------------
# Strategy-based orchestrator
# ---------------------------------------------------------------------------

class IAAgent:
    """
    Orchestrator that wraps any text generator (Strategy Pattern) and
    exposes domain-specific OSINT tasks: Google Dork generation, etc.
    """

    def __init__(self, generator):
        self.generator = generator

    def generate_gdork(self, description: str) -> str | None:
        """
        Synthesizes an optimized Google Dork from a natural-language description.
        Streams tokens live to the terminal (real token-by-token rendering)
        and returns the assembled dork. Retries automatically on transient
        provider errors via the underlying generator.

        Args:
            description: Human-readable target description.

        Returns:
            The generated dork string (stripped), or None on failure.
        """
        prompt = self._build_prompt(description)
        try:
            buffer: list[str] = []
            console.print()
            for token in self.generator.stream(prompt, render=False):
                if not token:
                    continue
                print(token, end="", flush=True)
                buffer.append(token)
            print()
            result = "".join(buffer).strip()
            return result or None
        except TypeError:
            # Generator.stream() may not accept the render kwarg in older versions.
            try:
                return self.generator.generate(prompt)
            except Exception as e:
                console.print(f"  [{THEME['ERROR']}]✘[/]  Error generating dork: {e}")
                return None
        except Exception as e:
            console.print(f"  [{THEME['ERROR']}]✘[/]  Error generating dork: {e}")
            return None

    def _build_prompt(self, description: str) -> str:
        return f"""
Your task is to act as an OSINT expert and generate a precise and effective Google Dork
based on the user's description. A Google Dork uses advanced search operators to find
specific information that is not easily accessible through conventional searches.

Instructions:
1. Analyze the user's description to identify keywords, file types, domains, and any other constraints.
2. Translate these requirements into the corresponding Google operators (e.g., `site:`, `filetype:`, `inurl:`, `intitle:`, etc.).
3. Combine the operators logically to create a cohesive and efficient dork.
4. Return ONLY the generated dork, without any additional explanations or text.

Examples:

User description: "Find annual reports in PDF format from Microsoft."
Google Dork: filetype:pdf "annual report" site:microsoft.com

User description: "Search for admin login pages on educational sites in Colombia."
Google Dork: site:.edu.co intitle:"admin login" | inurl:"admin"

User description: "I want to find Excel spreadsheets containing price lists for electronic products."
Google Dork: filetype:xlsx "price list" "electronic products"

Now, generate the Google Dork for the following description:

User description: "{description}"
"""

    # -----------------------------------------------------------------------
    # Query Planner — ReAct-style plan generation + execution
    # -----------------------------------------------------------------------

    def plan(
        self,
        goal: str,
        prior_observations: list[dict] | None = None,
    ) -> "QueryPlan":
        """
        Ask the LLM for a structured investigation plan for the given goal.

        Args:
            goal:              Natural-language description of what to investigate.
            prior_observations: If provided, the planner is told about previous
                                step outcomes and is asked to refine the remaining plan.

        Returns:
            A QueryPlan with steps that reference only whitelisted tools.
            Unknown tools are silently dropped.
        """
        prompt = self._planner_prompt(goal, prior_observations)
        try:
            buffer: list[str] = []
            for token in self.generator.stream(prompt, render=False):
                if token:
                    buffer.append(token)
            raw = "".join(buffer).strip()
        except Exception as e:
            console.print(f"  [{THEME['ERROR']}]✘[/]  Planner generation failed: {e}")
            return QueryPlan(goal=goal)

        parsed = self._parse_plan_json(raw)
        if not parsed:
            console.print(f"  [{THEME['ERROR']}]✘[/]  Could not parse plan JSON from LLM output.")
            return QueryPlan(goal=goal)

        plan = QueryPlan.from_dict(parsed, goal=goal)
        # Safety: drop any step referencing a tool outside the whitelist
        plan.steps = [s for s in plan.steps if s.tool in TOOL_DISPATCH]
        return plan

    def execute_plan(
        self,
        plan: "QueryPlan",
        *,
        interactive: bool = True,
        confirm_each: bool = True,
    ) -> list[dict]:
        """
        Execute the plan step-by-step. Returns a list of observations:
          {step, tool, args, status, summary, data}
        where status ∈ {"ok", "skip", "error"}.
        """
        observations: list[dict] = []
        confirm_fn = None
        if interactive and confirm_each:
            try:
                from cli.ui import confirm as _confirm
                confirm_fn = _confirm
            except Exception:
                confirm_fn = None

        total = len(plan.steps)
        for idx, step in enumerate(plan.steps, start=1):
            console.print()
            console.rule(
                f"[{THEME['PRIMARY']}]Step {idx}/{total} · {step.tool}[/]",
                style=THEME["DIM"],
            )
            if step.rationale:
                console.print(f"  [{THEME['DIM']}]why:[/]      {step.rationale}")
            if step.expected:
                console.print(f"  [{THEME['DIM']}]expect:[/]   {step.expected}")
            if step.args:
                console.print(f"  [{THEME['DIM']}]args:[/]     {step.args}")

            if confirm_fn and not confirm_fn("Run this step?", default=True):
                observations.append({
                    "step": idx, "tool": step.tool, "args": step.args,
                    "status": "skip", "summary": "skipped by user", "data": None,
                })
                continue

            dispatch = TOOL_DISPATCH.get(step.tool)
            if not dispatch:
                observations.append({
                    "step": idx, "tool": step.tool, "args": step.args,
                    "status": "error", "summary": f"unknown tool: {step.tool}", "data": None,
                })
                continue

            try:
                result = dispatch(step.args, self)
            except Exception as e:
                result = {"status": "error", "summary": f"exception: {e}", "data": None}

            observation = {
                "step":    idx,
                "tool":    step.tool,
                "args":    step.args,
                "status":  result.get("status", "ok"),
                "summary": result.get("summary", ""),
                "data":    result.get("data"),
            }
            observations.append(observation)
            badge = {
                "ok":    f"[{THEME['SUCCESS']}]✔[/]",
                "error": f"[{THEME['ERROR']}]✘[/]",
                "skip":  f"[{THEME['DIM']}]○[/]",
            }.get(observation["status"], "·")
            console.print(f"  {badge}  {_truncate(observation['summary'], 180)}")
        return observations

    def replan(self, goal: str, observations: list[dict]) -> "QueryPlan":
        """Refine the plan using past observations (ReAct loop)."""
        return self.plan(goal, prior_observations=observations)

    def _planner_prompt(
        self,
        goal: str,
        prior_observations: list[dict] | None,
    ) -> str:
        catalog = _format_catalog_for_prompt()

        history_block = ""
        if prior_observations:
            lines = []
            for obs in prior_observations[-10:]:
                args_json = json.dumps(obs.get("args", {}), ensure_ascii=False)
                lines.append(
                    f"- step {obs.get('step')}: {obs.get('tool')}({args_json}) "
                    f"→ [{obs.get('status')}] {_truncate(obs.get('summary', ''), 160)}"
                )
            history_block = (
                "\n\nPreviously executed steps and their observed results:\n"
                + "\n".join(lines)
                + "\n\nUse these observations to refine the remaining plan. "
                  "Do not repeat steps that already produced useful output."
            )

        return f"""You are an OSINT planning agent. Given a goal, produce a concrete,
executable investigation plan composed of calls to the tools below.

Available tools (use ONLY these names — any other will be rejected):
{catalog}

Rules:
1. Decompose the goal into 3 to 8 ordered steps, each a single tool call.
2. Prefer breadth first (search, username_enum) before depth (extract_pii, tech_scan).
3. For `search` / `deep_search`, craft the query like a Google Dork when useful
   (operators: site:, filetype:, intitle:, inurl:, "exact phrase", AND, OR, -exclude).
4. Every step must be self-contained — results are observed AFTER each call,
   so do not embed placeholders like {{{{previous_url}}}} in args.
5. Output ONLY one JSON object. No markdown fences, no prose, no comments.

JSON schema:
{{
  "summary": "one or two sentences describing the overall strategy",
  "steps": [
    {{
      "tool": "<tool name from the catalog>",
      "args": {{ "<arg>": "<value>" }},
      "rationale": "why this step is included",
      "expected": "what information we expect to learn"
    }}
  ]
}}

Goal: {goal}{history_block}
""".strip()

    @staticmethod
    def _parse_plan_json(raw: str) -> dict | None:
        """Robustly extract a JSON object from a possibly-messy LLM response."""
        if not raw:
            return None
        cleaned = raw.strip()

        # Strip ```json ... ``` fences if present
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
        if fence:
            cleaned = fence.group(1).strip()

        # Direct parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Fall back to the first balanced {...} block
        start = cleaned.find("{")
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        return None
        return None
