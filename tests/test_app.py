"""Offline tests: the MTA feed is replaced with a sample XML document."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import app as app_module  # noqa: E402
from accessroute import mta_feed, planner  # noqa: E402

# Elevator out at Times Sq (all lines) + an escalator out at 14 St-Union Sq.
SAMPLE_XML = b"""<NYCOutages>
  <outage><station>Times Sq-42 St</station><trainno>1/2/3/7/N/Q/R/W</trainno>
    <equipment>EL1</equipment><equipmenttype>EL</equipmenttype><serving>Street to mezzanine</serving>
    <ADA>Y</ADA><estimatedreturntoservice>10/30/2026</estimatedreturntoservice><reason>Repair</reason>
    <isupcomingoutage>N</isupcomingoutage></outage>
  <outage><station>14 St-Union Sq</station><trainno>4/5/6/L/N/Q/R/W</trainno>
    <equipment>ES2</equipment><equipmenttype>ES</equipmenttype><serving>Mezzanine</serving>
    <ADA>N</ADA><isupcomingoutage>N</isupcomingoutage></outage>
  <outage><station>Grand Central-42 St</station><trainno>4/5/6/7/S</trainno>
    <equipment>EL3</equipment><equipmenttype>EL</equipmenttype><ADA>Y</ADA>
    <isupcomingoutage>Y</isupcomingoutage></outage>
</NYCOutages>"""


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mta_feed, "fetch_outages",
                        lambda: mta_feed.parse_records(SAMPLE_XML, "outage"))
    monkeypatch.setattr(mta_feed, "fetch_ada_station_names", lambda: None)
    return app_module.app.test_client()


def station_id(name, route):
    g = app_module.graph
    return next(s for s, v in g.stations.items() if v["name"] == name and route in v["routes"])


def test_parse_records():
    recs = mta_feed.parse_records(SAMPLE_XML, "outage")
    assert len(recs) == 3 and recs[0]["equipmenttype"] == "EL" and recs[0]["ada"] == "Y"


def test_name_matching_uses_train_list():
    g = app_module.graph
    ids = g.match_station_ids("Times Sq-42 St", "1/2/3/7/N/Q/R/W")
    assert ids and all("Times Sq" in g.name(i) for i in ids)


def test_stations_endpoint(client):
    data = client.get("/api/stations").get_json()
    assert len(data) > 400 and {"id", "label"} <= set(data[0])


def test_validation(client):
    assert client.post("/api/route", json={"start": "x", "end": "y", "need": "elevator_only"}).status_code == 400


def test_elevator_outage_forces_alternative(client):
    start, end = station_id("34 St-Penn Station", "1"), station_id("Times Sq-42 St", "7")
    # Ending at Times Sq with its elevator out -> nothing usable for elevator-only riders.
    r = client.post("/api/route", json={"start": start, "end": end, "need": "elevator_only"}).get_json()
    assert r["plan"]["verdict"] == "no_route"


def test_escalator_rider_gets_warning(client):
    start, end = station_id("34 St-Penn Station", "1"), station_id("Times Sq-42 St", "7")
    r = client.post("/api/route", json={"start": start, "end": end,
                                        "need": "elevator_or_escalator"}).get_json()
    assert r["plan"]["verdict"] == "warning"


def test_upcoming_outage_ignored(client):
    start, end = station_id("Grand Central-42 St", "4"), station_id("86 St", "4")
    r = client.post("/api/route", json={"start": start, "end": end, "need": "elevator_only"}).get_json()
    assert r["plan"]["verdict"] == "clear"


def test_transfer_avoids_blocked_station(client):
    # Route that would normally change trains at Times Sq must find another way.
    start, end = station_id("Van Cortlandt Park-242 St", "1"), station_id("Atlantic Av-Barclays Ctr", "N")
    r = client.post("/api/route", json={"start": start, "end": end, "need": "elevator_only"}).get_json()
    plan = r["plan"]
    assert plan["verdict"] in ("clear", "alternative")
    assert all(c["status"] != "blocked" for c in plan["recommended"]["checks"])


def test_response_has_plain_summary_and_outage_details(client):
    start, end = station_id("34 St-Penn Station", "1"), station_id("Times Sq-42 St", "7")
    r = client.post("/api/route", json={"start": start, "end": end, "need": "elevator_only"}).get_json()
    assert r["summary"] and "ADA" not in r["summary"]
    outage = r["plan"]["fastest"]["checks"][-1]["outages"][0]
    assert outage["type"] == "Elevator" and outage["estimated_return"] == "10/30/2026"


def test_summaries_name_the_chosen_stations_for_every_verdict():
    for verdict in ("clear", "warning", "alternative", "no_route"):
        text = planner.summarize({"verdict": verdict, "start": "1 Av", "end": "14 St"})
        assert "1 Av" in text and "14 St" in text


def test_ai_and_search_removed(client):
    assert client.post("/api/chat", json={}).status_code == 404
    r = client.post("/api/route", json={"start": station_id("Grand Central-42 St", "4"),
                                        "end": station_id("86 St", "4"), "need": "elevator_only"}).get_json()
    assert "reply" not in r and "web_results" not in r["plan"]


def test_route_steps_end_at_the_chosen_destination():
    """A final walk between linked stations (6 Av -> 14 St) must appear as a step."""
    g = app_module.graph
    start = station_id("1 Av", "L")
    end = station_id("14 St", "F")
    route = g.find_route(start, end)
    last = route["legs"][-1]
    assert last["to"] == "14 St" and last["type"] == "walk" and last["from"] == "6 Av"
    assert route["legs"][0]["from"] == "1 Av"


def test_steps_are_contiguous():
    """Every step starts where the previous one ended (no gaps, no wrong destination)."""
    g = app_module.graph
    for a, b in [("1 Av", "14 St"), ("Van Cortlandt Park-242 St", "Atlantic Av-Barclays Ctr"),
                 ("Far Rockaway-Mott Av", "Flushing-Main St")]:
        route = g.find_route(next(s for s, v in g.stations.items() if v["name"] == a),
                             next(s for s, v in g.stations.items() if v["name"] == b))
        assert route["legs"][-1]["to"] == b
        for prev, nxt in zip(route["legs"], route["legs"][1:]):
            assert prev["to"] == nxt["from"]
