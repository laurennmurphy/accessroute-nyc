"""Optional Tavily web search for accessible alternatives.

Only used when the trip verdict is "alternative" or "no_route". Everything here
is best-effort: with no TAVILY_API_KEY, or on any error/timeout, we return an
empty list and the app behaves exactly as it does without Tavily.
Docs: https://docs.tavily.com (POST https://api.tavily.com/search).
"""
import logging
import os
import time

import requests

log = logging.getLogger(__name__)

TAVILY_URL = os.getenv("TAVILY_URL", "https://api.tavily.com/search")
CACHE_SECONDS = 600
_cache = {}  # query -> (timestamp, results)


def build_query(plan):
    """Search phrase aimed at current, official accessible-travel info."""
    return (f"NYC accessible alternative to subway from {plan['start']} to {plan['end']}: "
            "MTA elevator outage, accessible bus, Access-A-Ride")


def search_alternatives(plan, max_results=4):
    """Return [{title, url, snippet}] (possibly empty). Never raises."""
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        return []
    query = build_query(plan)
    cached = _cache.get(query)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        resp = requests.post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"query": query, "max_results": max_results, "search_depth": "basic",
                  "include_domains": ["mta.info", "nyc.gov", "511ny.org"]},
            timeout=8,  # keep the page snappy if Tavily is slow
        )
        resp.raise_for_status()
        results = [{"title": r.get("title", "")[:120], "url": r.get("url", ""),
                    "snippet": (r.get("content") or "")[:300]}
                   for r in resp.json().get("results", []) if r.get("url")]
    except (requests.RequestException, ValueError, AttributeError) as exc:
        log.warning("Tavily search failed (continuing without it): %s", exc)
        return []
    _cache[query] = (time.time(), results)
    return results
