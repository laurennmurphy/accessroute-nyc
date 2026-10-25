"""Conversational layer using NVIDIA's free hosted LLM API (build.nvidia.com).

The endpoint is OpenAI-compatible. Get a free key at https://build.nvidia.com
and put it in .env as NVIDIA_API_KEY. If the key is missing or the call fails,
we fall back to a plain templated answer so the app still works.
"""
import json
import logging
import os

import requests

log = logging.getLogger(__name__)

# OpenAI-compatible base URL; the chat endpoint is {base}/chat/completions.
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
DEFAULT_MODEL = "meta/llama-3.1-8b-instruct"

SYSTEM_PROMPT = (
    "You are AccessRoute NYC, a friendly assistant helping New York City subway riders "
    "with accessibility needs plan trips. You are given a JSON trip analysis built from the "
    "MTA's live elevator/escalator outage feed. Rules: base every statement ONLY on that "
    "analysis; never invent stations, lines or outages; clearly say which stations have "
    "outages and what is out; if the trip is fine say so; if the fastest route is blocked "
    "describe the recommended alternative; if no route exists suggest practical options "
    "(accessible buses like the Select Bus Service, Access-A-Ride, or checking mta.info/elevator "
    "or calling 511 before leaving). Keep it warm, concise (under 180 words), no markdown tables."
)


def _short(plan):
    """Trim the plan to what the model needs (keeps the prompt small)."""
    def route(r):
        if not r:
            return None
        return {
            "legs": [f'{l["route"]} train: {l["from"]} -> {l["to"]} ({l["num_stops"]} stops)'
                     for l in r["legs"]],
            "stations_rider_must_use": r["checks"],
        }
    return {k: (route(plan[k]) if k in ("fastest", "recommended") else plan[k])
            for k in ("start", "end", "need", "verdict", "fastest", "recommended")}


def fallback_message(plan):
    """Plain-text answer used when the AI is unavailable."""
    v = plan["verdict"]
    if v == "clear":
        return f"Good news! Your accessible route from {plan['start']} to {plan['end']} has no reported outages."
    if v == "warning":
        return ("Your route works, but an elevator is out at a station you'll use - "
                "you'll need an escalator there. See the details below.")
    if v == "alternative":
        return ("The fastest route has an outage at a station you'd need, but there is an "
                "alternative route that avoids it - shown below.")
    return ("I couldn't find a fully accessible route right now. Consider an accessible bus, "
            "Access-A-Ride, or check mta.info/elevator or call 511 before heading out.")


def ask(plan, history=None, question=None):
    """Return (reply_text, ai_used, error).

    history: prior chat turns [{role, content}], question: the new user message
    (None for the initial recommendation). `error` is a short reason string when
    the AI could not be used (reply_text is then the plain fallback), else None.
    """
    key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not key:
        return fallback_message(plan), False, "NVIDIA_API_KEY is not set"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\nTRIP ANALYSIS:\n" + json.dumps(_short(plan))},
    ]
    messages += (history or [])[-10:]
    messages.append({"role": "user", "content": question or
                     "Please tell me whether I can make this trip and which route to take."})
    model = os.getenv("NVIDIA_MODEL", DEFAULT_MODEL).strip()
    try:
        resp = requests.post(
            f"{NVIDIA_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                     "Content-Type": "application/json"},
            json={"model": model, "messages": messages,
                  "temperature": 0.3, "max_tokens": 500, "stream": False},
            timeout=45,
        )
        if not resp.ok:
            # NVIDIA returns a JSON/text body explaining the problem (bad key, unknown model...).
            raise RuntimeError(f"HTTP {resp.status_code} from NVIDIA: {resp.text[:200]}")
        return resp.json()["choices"][0]["message"]["content"].strip(), True, None
    except (requests.RequestException, RuntimeError, KeyError, IndexError, ValueError) as exc:
        log.warning("NVIDIA API call failed (model=%s): %s", model, exc)
        return fallback_message(plan), False, str(exc)
