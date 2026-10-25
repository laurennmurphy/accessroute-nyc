"""Combines the subway map with live outage data to judge a trip."""
from .subway_graph import ELEVATOR_ONLY, ELEVATOR_OR_ESCALATOR

# Station status levels
OK, WARNING, BLOCKED = "ok", "warning", "blocked"


def outages_by_station(graph, outages):
    """Group active (not merely upcoming) outages under our station ids.

    Returns (dict station_id -> [outage], count of outages we couldn't place).
    """
    grouped, unmatched = {}, 0
    for o in outages:
        if o.get("isupcomingoutage", "N").upper() == "Y":
            continue  # planned for the future - not an outage right now
        if o.get("equipmenttype", "").upper() == "EL" and o.get("ada", "").upper() == "N":
            continue  # non-ADA elevator: irrelevant to accessible travel
        ids = graph.match_station_ids(o.get("station", ""), o.get("trainno", ""))
        if not ids:
            unmatched += 1
        for sid in ids:
            grouped.setdefault(sid, []).append(o)
    return grouped, unmatched


def station_status(station_outages, need):
    """Decide whether a rider can use a station given its broken equipment.

    elevator_only          -> any elevator outage blocks the station.
    elevator_or_escalator  -> the rider can fall back on escalators, so an
                              elevator outage is only a WARNING, unless an
                              escalator there is out as well (then BLOCKED).
    Escalator-only outages never matter to an elevator-only rider.
    """
    elevators = [o for o in station_outages if o.get("equipmenttype", "").upper() == "EL"]
    escalators = [o for o in station_outages if o.get("equipmenttype", "").upper() == "ES"]
    if need == ELEVATOR_ONLY:
        return BLOCKED if elevators else OK
    if elevators and escalators:
        return BLOCKED
    return WARNING if elevators else OK


def _describe(o):
    """Compact outage record for the frontend / AI prompt."""
    return {
        "equipment": o.get("equipment", ""),
        "type": "Elevator" if o.get("equipmenttype", "").upper() == "EL" else "Escalator",
        "serving": o.get("serving", ""),
        "reason": o.get("reason", ""),
        "estimated_return": o.get("estimatedreturntoservice", ""),
    }


def check_route(graph, route, grouped, need, inaccessible=frozenset()):
    """Annotate each station the rider must use with its outage status."""
    checks = []
    for sid in route["needs_access"]:
        outs = grouped.get(sid, [])
        # A transfer between two linked platforms of one complex lists the
        # same name twice in a row; fold those into a single entry.
        if checks and checks[-1]["name"] == graph.name(sid):
            checks[-1]["_outs"] += [o for o in outs if o not in checks[-1]["_outs"]]
            checks[-1]["no_ada"] |= sid in inaccessible
            continue
        checks.append({"id": sid, "name": graph.name(sid), "_outs": list(outs),
                       "no_ada": sid in inaccessible})
    for c in checks:
        outs = c.pop("_outs")
        c["status"] = BLOCKED if c["no_ada"] else station_status(outs, need)
        c["outages"] = [_describe(o) for o in outs]
    return checks


def plan_trip(graph, start, end, need, outages, ada_names=None):
    """Plan a trip and classify the result.

    verdict:
      clear        - the fastest route is fully usable
      warning      - usable, but some elevator is out (escalator needed)
      alternative  - fastest route is blocked; a different usable route exists
      no_route     - nothing usable between the two stations
    """
    grouped, unmatched = outages_by_station(graph, outages)

    # Stations the rider cannot use at all (outage-blocked or no ADA equipment).
    inaccessible = set()
    if ada_names:
        # Only trust the "has ADA equipment" list if it matched plenty of stations.
        ada_ids = {sid for n in ada_names for sid in graph.match_station_ids(n)}
        if len(ada_ids) > 100:
            inaccessible = set(graph.stations) - ada_ids
    blocked = {sid for sid, outs in grouped.items() if station_status(outs, need) == BLOCKED}
    blocked |= inaccessible

    fastest = graph.find_route(start, end)               # ignoring outages
    usable = graph.find_route(start, end, frozenset(blocked))
    result = {"unmatched_outages": unmatched, "need": need,
              "start": graph.name(start), "end": graph.name(end),
              "ada_data": bool(inaccessible)}

    if fastest is None:
        return {**result, "verdict": "no_route", "fastest": None, "recommended": None}

    fastest_checks = check_route(graph, fastest, grouped, need, inaccessible)
    fastest_info = {**fastest, "checks": fastest_checks}
    if usable is None:
        return {**result, "verdict": "no_route", "fastest": fastest_info, "recommended": None}

    usable_checks = check_route(graph, usable, grouped, need, inaccessible)
    usable_info = {**usable, "checks": usable_checks}
    if any(c["status"] == BLOCKED for c in fastest_checks):
        verdict = "alternative"
    elif any(c["status"] == WARNING for c in usable_checks):
        verdict = "warning"
    else:
        verdict = "clear"
    return {**result, "verdict": verdict, "fastest": fastest_info, "recommended": usable_info}


def summarize(plan):
    """One or two plain-language sentences naming the stations the rider chose."""
    trip = f"from {plan['start']} to {plan['end']}"
    v = plan["verdict"]
    if v == "clear":
        return f"Good news! Your route {trip} has no elevators or escalators out of service."
    if v == "warning":
        return (f"You can make your trip {trip}, but an elevator is out of service at a "
                "station you'll use. You'll need the escalator there.")
    if v == "alternative":
        return (f"The fastest route {trip} has an elevator or escalator out of service at a "
                "station you'd need, but there is an alternative route that avoids it, shown below.")
    return (f"We couldn't find a fully accessible route {trip} right now. "
            "Consider an accessible bus or Access-A-Ride, or call 511 before heading out.")
