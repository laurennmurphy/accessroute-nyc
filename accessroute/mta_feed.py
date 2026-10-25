"""Fetching and parsing of the MTA elevator/escalator (ENE) XML feeds.

The outage feed lists every piece of equipment that is *currently* out of
service (or scheduled to be). Each <outage> element looks roughly like:

    <outage>
      <station>Times Sq-42 St</station>
      <trainno>1/2/3/7/N/Q/R/W/S</trainno>
      <equipment>EL123</equipment>
      <equipmenttype>EL</equipmenttype>      <!-- EL = elevator, ES = escalator -->
      <serving>Street to mezzanine</serving>
      <ADA>Y</ADA>
      <estimatedreturntoservice>...</estimatedreturntoservice>
      <reason>Repair</reason>
      <isupcomingoutage>N</isupcomingoutage>
      ...
    </outage>
"""
import os
import re
import time
import xml.etree.ElementTree as ET

import requests

OUTAGE_URL = os.getenv(
    "MTA_OUTAGE_URL",
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fnyct_ene.xml",
)
# Companion feed listing *all* equipment (not just broken). Used only to learn
# which stations have ADA equipment at all; the app works without it.
EQUIPMENT_URL = os.getenv(
    "MTA_EQUIPMENT_URL",
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fnyct_ene_equipments.xml",
)

CACHE_SECONDS = 60  # the MTA refreshes the feed about once a minute
_cache = {}  # url -> (timestamp, parsed records)


def _text(elem, tag):
    """Return the stripped text of a child tag, or '' if it is missing."""
    child = elem.find(tag)
    return (child.text or "").strip() if child is not None else ""


def parse_records(xml_bytes, record_tag):
    """Parse feed XML into a list of flat dicts, one per <record_tag> element.

    Tag names are lower-cased so slight capitalisation changes in the MTA's
    feed (e.g. <ADA> vs <ada>) do not break us.
    """
    root = ET.fromstring(xml_bytes)
    records = []
    for elem in root.iter(record_tag):
        records.append({(c.tag or "").lower(): (c.text or "").strip() for c in elem})
    return records


def _fetch(url, record_tag):
    """GET a feed (cached for CACHE_SECONDS) and return its parsed records."""
    cached = _cache.get(url)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    records = parse_records(resp.content, record_tag)
    _cache[url] = (time.time(), records)
    return records


def fetch_outages():
    """Return the list of current/upcoming equipment outages."""
    return _fetch(OUTAGE_URL, "outage")


def fetch_ada_station_names():
    """Return the set of station names that have ADA equipment, or None.

    None means "unknown" (feed unreachable or in an unexpected format), in
    which case the router assumes every station is accessible.
    """
    try:
        records = _fetch(EQUIPMENT_URL, "equipment")
    except (requests.RequestException, ET.ParseError):
        return None
    names = {r["station"] for r in records if r.get("ada", "").upper() == "Y" and r.get("station")}
    return names or None


# ---------------------------------------------------------------- name matching

def normalize_name(name):
    """Reduce a station name to a comparable form.

    'Times Sq-42 St' and 'Times Sq - 42 St' both become 'times sq 42 st'.
    """
    s = name.lower().replace("&", " and ")
    s = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", s)  # 42nd -> 42
    s = re.sub(r"\bstreet\b", "st", s)
    s = re.sub(r"\b(avenue|ave)\b", "av", s)
    s = re.sub(r"\bsquare\b", "sq", s)
    s = re.sub(r"\bst\b", "", s)  # '42 St' vs '42' vs '42nd' all collapse to '42'
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def split_trains(trainno):
    """'A/C/E' or 'A,C,E' -> {'A','C','E'}."""
    return {t for t in re.split(r"[^A-Za-z0-9]+", trainno.upper()) if t}
