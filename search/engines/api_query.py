"""
Request handling shared by search APIs that answer in a single call.

Tavily and Exa have no pagination and do not document dork operators, so a
page becomes a slice of one response and ``site:`` becomes a domain filter.
"""

import re

import requests

from cli.ui import print_warn

_TIMEOUT = 30

# A site: operator, including an OR that joins it to the previous one. The
# lookbehind leaves an operator written inside a quoted phrase untouched.
_SITE_RE = re.compile(r'(?<![^\s(])(?:OR\s+)?(-?)site:([^\s()"]+)', re.IGNORECASE)
_EMPTY_GROUP_RE = re.compile(r"\(\s*\)")
_OPERATOR_RE = re.compile(r'(?<![^\s(-])(filetype|ext|intitle|inurl|intext|lang|loc):\S',
                          re.IGNORECASE)


def split_site_filters(query: str) -> tuple[str, list[str], list[str]]:
    """
    Moves ``site:`` operators out of a query, for APIs that take domain lists.

    Returns:
        The remaining query, the included domains and the excluded domains.
        A query made only of operators falls back to the domains as its text,
        because these APIs refuse an empty query.
    """
    included: list[str] = []
    excluded: list[str] = []

    def collect(match: re.Match) -> str:
        (excluded if match[1] else included).append(match[2])
        return " "

    remaining = _EMPTY_GROUP_RE.sub(" ", _SITE_RE.sub(collect, query))
    remaining = " ".join(remaining.split())
    return remaining or " ".join(included or excluded), included, excluded


def warn_ignored_operators(engine: str, query: str) -> None:
    """Warns about operators the API would read as plain words."""
    found = sorted({name.lower() for name in _OPERATOR_RE.findall(query)})
    if found:
        names = ", ".join(f"{name}:" for name in found)
        print_warn(f"{engine} does not document {names} — it reads them as plain "
                   "text, so check that the results really match.")


def result_window(engine: str, pages: int, start_page: int,
                  page_size: int, limit: int) -> tuple[int, int]:
    """
    Translates pages into the slice of a single response.

    Args:
        engine:     Name used in the messages.
        pages:      Number of pages requested.
        start_page: First page requested (1-based).
        page_size:  Results that count as one page.
        limit:      Most results one request can return.

    Returns:
        The first and last result positions, as slice bounds. The last one is
        also how many results the request has to ask for.

    Raises a runtime exception when ``start_page`` is past ``limit``, before
    any credit is spent.
    """
    first = (max(1, int(start_page)) - 1) * page_size
    if first >= limit:
        raise RuntimeError(f"{engine} only serves {limit} results per query.")
    last = first + max(1, int(pages)) * page_size
    if last > limit:
        print_warn(f"{engine} only serves {limit} results per query — stopping there.")
        last = limit
    return first, last


def post_search(engine: str, url: str, headers: dict, payload: dict,
                rejections: dict[int, str]) -> list[dict]:
    """
    Sends one search and returns the ``results`` list of the response.

    Args:
        engine:     Name used in the messages.
        url:        API endpoint.
        headers:    Request headers, including the API key.
        payload:    JSON body.
        rejections: Message to show for each status the API documents.

    Raises a runtime exception when the request fails or the response cannot
    be read, so a failure is never mistaken for a search without results.
    """
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=_TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"{engine} Search API Error: {e}")

    if response.status_code in rejections:
        raise RuntimeError(rejections[response.status_code])

    try:
        response.raise_for_status()
        return response.json().get("results") or []
    except (requests.exceptions.RequestException, ValueError, AttributeError) as e:
        raise RuntimeError(f"{engine} Search API Error: {e}")
