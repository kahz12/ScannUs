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
        "desc": "Search, then crawl each URL and extract PII (emails, phones, IBANs, "
                "credit cards, DNIs, CUITs, RFCs).",
        "args": {
            "query":  "str (required)",
            "engine": "str (default: duckduckgo)",
        },
    },
    "extract_pii": {
        "desc": "Fetch a single URL and extract identifiers (emails, phones, IBANs, "
                "credit cards, DNIs, CUITs, RFCs).",
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
        "desc": "Look up the URL's history on the Wayback Machine.",
        "args": {"url": "str (required)"},
    },
    "summarize_url": {
        "desc": "Fetch a URL's main content and ask the LLM to summarise it.",
        "args": {"url": "str (required)"},
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
    from cli.actions import _get_search_engine
    query = (args.get("query") or "").strip()
    if not query:
        return {"status": "error", "summary": "search: missing 'query'"}
    engine = (args.get("engine") or "duckduckgo").lower()
    try:
        pages = int(args.get("pages") or 1)
    except (TypeError, ValueError):
        pages = 1
    try:
        results = _get_search_engine(engine, pages, 1, "lang_es", query)
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


TOOL_DISPATCH: dict[str, Callable[..., dict]] = {
    "search":         _dispatch_search,
    "deep_search":    _dispatch_deep_search,
    "extract_pii":    _dispatch_extract_pii,
    "tech_scan":      _dispatch_tech_scan,
    "username_enum":  _dispatch_username_enum,
    "screenshot":     _dispatch_screenshot,
    "wayback":        _dispatch_wayback,
    "summarize_url":  _dispatch_summarize_url,
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
