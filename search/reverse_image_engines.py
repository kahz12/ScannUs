"""
search/reverse_image_engines.py — Multi-engine reverse image search with
graceful fallbacks.

Tiered fallback order — each engine is independent and silently skipped if
its prerequisite (API key, browser, network) is missing:

  1. TinEye API (HMAC-signed)         — requires TINEYE_PUBLIC_KEY + TINEYE_PRIVATE_KEY
  2. Bing Visual Search (Azure CS)    — requires BING_VISUAL_SEARCH_KEY
  3. Yandex (Selenium, existing)      — requires Firefox + geckodriver
  4. Manual lookup URLs               — always returns; no deps, no auth

The orchestrator (``reverse_image_aggregate``) runs every enabled engine
and returns a flat list of ``{title, link, description, engine}`` entries.
The manual-URL tier guarantees that the user always has *something* to act
on, even when every programmatic engine has failed or is unconfigured.
"""

import hashlib
import hmac
import json as _json
import os
import time
from urllib.parse import quote

import requests


_TIMEOUT = 12
_UA = "Mozilla/5.0 (compatible; ScannUs/1.0; +OSINT-reverse-image)"


# ============================================================================
# Engine 1 — TinEye API (HMAC-signed REST endpoint)
# ============================================================================

def tineye_search(image_url: str, public_key: str | None = None,
                  private_key: str | None = None, limit: int = 20) -> list[dict]:
    """
    Query the commercial TinEye REST API.

    Returns an empty list when keys are missing or the request fails — TinEye
    is opt-in and must never block the fallback chain.
    """
    public_key  = public_key  or os.getenv("TINEYE_PUBLIC_KEY")
    private_key = private_key or os.getenv("TINEYE_PRIVATE_KEY")
    if not (public_key and private_key):
        return []

    api_url = "https://api.tineye.com/rest/search/"
    nonce   = f"scannus{int(time.time() * 1000)}"
    date    = str(int(time.time()))
    params  = {
        "image_url": image_url,
        "api_key":   public_key,
        "date":      date,
        "nonce":     nonce,
        "offset":    "0",
        "limit":     str(limit),
        "sort":      "score",
        "order":     "desc",
    }
    sorted_params = "&".join(
        f"{k}={quote(str(v), safe='')}" for k, v in sorted(params.items())
    )
    to_sign = f"{private_key}GETimage/jpeg{date}{nonce}{api_url}{sorted_params}"
    params["api_sig"] = hmac.new(
        private_key.encode(), to_sign.encode(), hashlib.sha256
    ).hexdigest()

    try:
        r = requests.get(api_url, params=params, timeout=_TIMEOUT,
                         headers={"User-Agent": _UA})
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    matches = (data.get("results") or {}).get("matches") or []
    out: list[dict] = []
    for m in matches:
        backlinks = m.get("backlinks") or []
        if not backlinks:
            continue
        bl    = backlinks[0]
        score = m.get("score", "?")
        out.append({
            "title":       bl.get("backlink_label") or bl.get("backlink") or "TinEye match",
            "link":        bl.get("backlink") or bl.get("url") or "",
            "description": f"[TinEye · score {score}] {bl.get('crawl_date', '')}".strip(),
            "engine":      "tineye",
        })
    return out


# ============================================================================
# Engine 2 — Bing Visual Search (Azure Cognitive Services)
# ============================================================================

def bing_visual_search(image_url: str, api_key: str | None = None,
                       count: int = 15) -> list[dict]:
    """
    Query the Bing Visual Search v7 endpoint via Azure Cognitive Services.

    Returns an empty list when the key is missing or the request fails.
    """
    api_key = (api_key or os.getenv("BING_VISUAL_SEARCH_KEY")
               or os.getenv("BING_SEARCH_KEY"))
    if not api_key:
        return []

    endpoint = "https://api.bing.microsoft.com/v7.0/images/visualsearch"
    knowledge_req = {"imageInfo": {"url": image_url}}
    files = {"knowledgeRequest": (None, _json.dumps(knowledge_req))}
    headers = {"Ocp-Apim-Subscription-Key": api_key, "User-Agent": _UA}

    try:
        r = requests.post(endpoint, headers=headers, files=files, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    out: list[dict] = []
    for tag in data.get("tags", []):
        for action in tag.get("actions", []):
            if action.get("actionType") not in ("PagesIncluding", "VisualSearch"):
                continue
            items = ((action.get("data") or {}).get("value") or [])[:count]
            for item in items:
                host = item.get("hostPageDisplayUrl") or item.get("hostPageUrl") or ""
                link = item.get("hostPageUrl") or item.get("contentUrl") or ""
                if not link:
                    continue
                out.append({
                    "title":       item.get("name") or "Bing match",
                    "link":        link,
                    "description": f"[Bing] {host}",
                    "engine":      "bing",
                })
            if out:
                return out
    return out


# ============================================================================
# Engine 3 — Yandex (existing Selenium-based scraper)
# ============================================================================

def yandex_search(image_url: str) -> list[dict]:
    """
    Delegate to ``SmartSearch.reverse_image_search``. Returns ``[]`` on any
    failure (missing browser, selector drift, network error) so a broken
    Yandex engine doesn't poison the fallback chain.
    """
    try:
        from search.smart_search import SmartSearch
        results = SmartSearch().reverse_image_search(image_url) or []
    except Exception:
        return []
    for r in results:
        r["engine"] = "yandex"
        if "[Yandex]" not in r.get("description", ""):
            r["description"] = f"[Yandex] {r.get('description', '')}".strip()
    return results


# ============================================================================
# Engine 4 — Manual lookup URLs (always available, zero deps)
# ============================================================================

def manual_lookup_urls(image_url: str) -> list[dict]:
    """
    Build direct search URLs for the major reverse-image engines.

    No auth, no network, no scraping — these are simply the URLs the user
    would type into a browser. They exist so the fallback chain always
    surfaces at least *something* actionable.
    """
    encoded = quote(image_url, safe="")
    return [
        {
            "title":       "Google Lens",
            "link":        f"https://lens.google.com/uploadbyurl?url={encoded}",
            "description": "[manual · Google Lens] open in browser to inspect matches",
            "engine":      "manual",
        },
        {
            "title":       "Bing Visual Search",
            "link":        f"https://www.bing.com/images/search?q=imgurl:{encoded}"
                           f"&view=detailv2&iss=sbi",
            "description": "[manual · Bing] open in browser",
            "engine":      "manual",
        },
        {
            "title":       "Yandex Images",
            "link":        f"https://yandex.com/images/search?rpt=imageview&url={encoded}",
            "description": "[manual · Yandex] open in browser",
            "engine":      "manual",
        },
        {
            "title":       "TinEye",
            "link":        f"https://tineye.com/search?url={encoded}",
            "description": "[manual · TinEye] open in browser",
            "engine":      "manual",
        },
        {
            "title":       "SauceNAO",
            "link":        f"https://saucenao.com/search.php?url={encoded}",
            "description": "[manual · SauceNAO] anime/illustration-focused",
            "engine":      "manual",
        },
    ]


# ============================================================================
# Orchestrator
# ============================================================================

_VALID_ENGINES = ("tineye", "bing", "yandex", "manual")


def reverse_image_aggregate(image_url: str,
                            engines: list[str] | None = None,
                            include_manual: bool = True) -> list[dict]:
    """
    Run all enabled reverse-image engines and aggregate their results.

    Args:
        image_url: Public URL of the target image.
        engines:   Optional whitelist (subset of ``tineye``, ``bing``,
                   ``yandex``, ``manual``). Defaults to all.
        include_manual: Force-include the manual-URL tier so the caller
                   always gets *something* even if every programmatic engine
                   returned empty. Set False for headless/API contexts that
                   only want machine-actionable hits.

    Returns:
        Flat list of ``{title, link, description, engine}`` dicts.
    """
    enabled = set(engines) if engines else set(_VALID_ENGINES)
    out: list[dict] = []

    if "tineye" in enabled:
        out.extend(tineye_search(image_url))
    if "bing" in enabled:
        out.extend(bing_visual_search(image_url))
    if "yandex" in enabled:
        out.extend(yandex_search(image_url))
    if include_manual and "manual" in enabled:
        out.extend(manual_lookup_urls(image_url))

    return out
