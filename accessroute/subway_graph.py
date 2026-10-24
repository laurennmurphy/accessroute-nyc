"""Subway map + accessibility-aware routing.

The map comes from data/stations.json (built by scripts/build_stations.py).
Routing is Dijkstra over *(station, line)* states, so that changing trains
is a visible, penalised step - and so we know exactly which stations the rider
must actually use the elevators at (where they board, change trains, or exit).
Stations a train merely passes through do not need working equipment.
"""
import heapq
import json
from collections import defaultdict
from difflib import get_close_matches
from pathlib import Path

from .mta_feed import normalize_name, split_trains

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "stations.json"

TRANSFER_PENALTY = 4        # "cost" of changing trains within one station
WALK_TRANSFER_PENALTY = 5   # changing trains by walking between linked stations

# Outage-handling modes selectable by the user.
ELEVATOR_ONLY = "elevator_only"
ELEVATOR_OR_ESCALATOR = "elevator_or_escalator"


class SubwayGraph:
    def __init__(self, data_file=DATA_FILE):
        data = json.loads(Path(data_file).read_text())
        self.stations = data["stations"]                 # id -> {name, lat, lon, routes}
        self.rides = defaultdict(list)                   # (station, route) -> [next stations]
        for a, b, route in data["edges"]:
            self.rides[(a, route)].append(b)
        self.walks = defaultdict(set)                    # station -> linked stations
        for a, b in data["transfers"]:
            self.walks[a].add(b)
            self.walks[b].add(a)
        # normalised name -> station ids, for matching MTA outage records
        self.by_name = defaultdict(list)
        for sid, st in self.stations.items():
            self.by_name[normalize_name(st["name"])].append(sid)

    # ------------------------------------------------------------ lookups

    def name(self, sid):
        return self.stations[sid]["name"]

    def station_list(self):
        """Autocomplete entries, labelled with the lines serving each station."""
        out = []
        for sid, st in self.stations.items():
            # Lines are always shown: many stations share a name ("86 St").
            label = f'{st["name"]} ({" ".join(st["routes"])})'
            out.append({"id": sid, "name": st["name"], "label": label, "routes": st["routes"]})
        return sorted(out, key=lambda s: s["label"])

    def match_station_ids(self, feed_name, trainno=""):
        """Map an MTA feed station name (+ its train list) to our station ids.

        Exact normalised-name matches win; otherwise a fuzzy match is tried.
        When several stations share a name ('86 St') the feed's train list is
        used to keep only the ones served by those trains.
        """
        key = normalize_name(feed_name)
        candidates = self.by_name.get(key)
        if not candidates:
            close = get_close_matches(key, self.by_name.keys(), n=1, cutoff=0.85)
            candidates = self.by_name[close[0]] if close else []
        trains = split_trains(trainno)
        if trains and len(candidates) > 1:
            narrowed = [c for c in candidates if trains & set(self.stations[c]["routes"])]
            candidates = narrowed or candidates
        return candidates

    # ------------------------------------------------------------ routing

    def find_route(self, start, end, blocked=frozenset()):
        """Cheapest route start->end that only boards/changes/exits at
        stations not in `blocked`. Returns a dict or None if impossible."""
        if start in blocked or end in blocked:
            return None
        # state = (station, route); priority queue of (cost, state)
        heap = []
        best = {}
        prev = {}
        for r in self.stations[start]["routes"]:
            state = (start, r)
            best[state] = 0
            heapq.heappush(heap, (0, state))

        goal = None
        while heap:
            cost, state = heapq.heappop(heap)
            if cost > best.get(state, float("inf")):
                continue  # stale queue entry
            station, route = state
            if station == end:
                goal = state
                break

            moves = [((n, route), 1) for n in self.rides.get(state, [])]  # ride one stop
            if station not in blocked:
                # change to another line in the same station
                moves += [((station, r), TRANSFER_PENALTY)
                          for r in self.stations[station]["routes"] if r != route]
                # walk to a linked station of the same complex and change there
                for other in self.walks.get(station, ()):
                    if other not in blocked:
                        moves += [((other, r), WALK_TRANSFER_PENALTY)
                                  for r in self.stations[other]["routes"]]
            for nxt, step in moves:
                if cost + step < best.get(nxt, float("inf")):
                    best[nxt] = cost + step
                    prev[nxt] = state
                    heapq.heappush(heap, (cost + step, nxt))

        if goal is None:
            return None
        path = [goal]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        return self._build_legs(path, best[goal])

    def _build_legs(self, path, cost):
        """Turn a (station, line) state path into rider-friendly legs.

        Each leg is one continuous ride on a line. `needs_access` lists the
        stations where the rider must use working equipment: the start, the
        end, and both sides of every change of trains.
        """
        legs = [{"route": path[0][1], "stops": [path[0][0]]}]
        needs_access = [path[0][0]]
        for station, route in path[1:]:
            if route == legs[-1]["route"]:
                legs[-1]["stops"].append(station)        # still on the same train
            else:                                        # changed trains
                for sid in (legs[-1]["stops"][-1], station):
                    if sid != needs_access[-1]:
                        needs_access.append(sid)
                legs.append({"route": route, "stops": [station]})
        if path[-1][0] != needs_access[-1]:
            needs_access.append(path[-1][0])
        legs = [l for l in legs if len(l["stops"]) > 1]  # drop zero-length legs
        return {
            "legs": [{"route": l["route"], "stops": l["stops"],
                      "from": self.name(l["stops"][0]), "to": self.name(l["stops"][-1]),
                      "num_stops": len(l["stops"]) - 1} for l in legs],
            "needs_access": needs_access,
            "cost": cost,
        }
