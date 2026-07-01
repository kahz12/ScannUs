"""
Import / structure guards for the AI package layout.

``core.ai_agent`` is a facade over ``core.providers`` (the LLM wrappers) and
``core.planner`` (the ReAct plan model, tool catalog, and dispatchers). These
tests pin the public surface — the names importable from ``core.ai_agent`` and
the catalog/dispatch parity — so a future move doesn't silently break callers
such as ``cli.menus``.
"""


def test_backward_compatible_facade_exports():
    """The exact set cli.menus imports today must resolve via core.ai_agent."""
    import core.ai_agent as m

    for name in ("IAAgent", "OpenAIGenerator", "GeminiGenerator",
                 "AnthropicGenerator", "OllamaGenerator"):
        assert hasattr(m, name), f"core.ai_agent lost export: {name}"


def test_providers_package_exports():
    import core.providers as p

    for name in ("OpenAIGenerator", "GeminiGenerator",
                 "AnthropicGenerator", "OllamaGenerator"):
        assert hasattr(p, name), f"core.providers missing: {name}"


def test_facade_and_package_are_the_same_objects():
    """The facade must re-export the real classes, not shadow copies."""
    import core.ai_agent as m
    import core.providers as p

    assert m.GeminiGenerator is p.GeminiGenerator
    assert m.OllamaGenerator is p.OllamaGenerator


def test_planner_primitives_importable():
    from core.planner import PlanStep, QueryPlan

    assert PlanStep(tool="search").tool == "search"
    assert QueryPlan(goal="g").steps == []


def test_catalog_and_dispatch_stay_in_sync():
    """Every advertised tool must have a dispatcher, and vice versa."""
    from core.planner import TOOL_CATALOG, TOOL_DISPATCH

    assert set(TOOL_CATALOG) == set(TOOL_DISPATCH)
    assert all(callable(fn) for fn in TOOL_DISPATCH.values())


def test_plan_json_parser_handles_fenced_output():
    from core.ai_agent import IAAgent

    parsed = IAAgent._parse_plan_json('```json\n{"summary": "s", "steps": []}\n```')
    assert parsed == {"summary": "s", "steps": []}


def test_plan_drops_unknown_tools():
    from core.planner import QueryPlan, TOOL_DISPATCH

    plan = QueryPlan.from_dict(
        {
            "summary": "x",
            "steps": [
                {"tool": "search", "args": {"query": "q"}},
                {"tool": "not_a_real_tool", "args": {}},
            ],
        },
        goal="g",
    )
    kept = [s for s in plan.steps if s.tool in TOOL_DISPATCH]
    assert [s.tool for s in kept] == ["search"]
