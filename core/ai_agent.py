"""
core/ai_agent.py — the OSINT AI orchestrator (:class:`IAAgent`).

The provider wrappers live in :mod:`core.providers` and the ReAct query planner
(plan model, tool catalog, dispatchers) in :mod:`core.planner`. This module
holds the high-level ``IAAgent`` orchestrator and re-exports the provider
classes and planner primitives, so the whole AI surface is importable from one
place (e.g. ``from core.ai_agent import IAAgent, GeminiGenerator``).

Providers:
  - OpenAIGenerator     — OpenAI Chat Completions (streaming)
  - GeminiGenerator     — Google Gemini (streaming)
  - AnthropicGenerator  — Anthropic Claude (streaming)
  - OllamaGenerator     — local Ollama HTTP API (streaming, no key)
"""

import json
import re

from cli.ui import console, THEME
from core.providers import (
    AnthropicGenerator,
    GeminiGenerator,
    OllamaGenerator,
    OpenAIGenerator,
)
from core.planner import (
    PlanStep,
    QueryPlan,
    TOOL_CATALOG,
    TOOL_DISPATCH,
    _format_catalog_for_prompt,
    _truncate,
)


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


# ---------------------------------------------------------------------------
# Re-exports: provider wrappers (core.providers) and planner primitives
# (core.planner) are surfaced here so callers can import the full AI surface
# from core.ai_agent.
# ---------------------------------------------------------------------------

__all__ = [
    "IAAgent",
    # providers
    "OpenAIGenerator",
    "GeminiGenerator",
    "AnthropicGenerator",
    "OllamaGenerator",
    # planner primitives
    "PlanStep",
    "QueryPlan",
    "TOOL_CATALOG",
    "TOOL_DISPATCH",
]
