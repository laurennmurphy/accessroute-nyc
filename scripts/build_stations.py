"""Build data/stations.json from the MTA's static subway GTFS feed.

The MTA outage feed only knows station *names*, so AccessRoute needs its own
map of the subway: which stations exist, which lines serve them, which
stations are adjacent on each line, and where riders can transfer.

Usage:
    python scripts/build_stations.py [path/to/gtfs_subway.zip]

With no argument the zip is downloaded from the MTA.
"""
import csv
import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import requests

GTFS_URL = "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip"
OUT_FILE = Path(__file__).resolve().parent.parent / "data" / "stations.json"


def read_csv(zf, name):
    """Yield each row of a CSV file inside the zip as a dict."""
    with zf.open(name) as fh:
        yield from csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig"))


def main():
    # Load the zip from disk if a path was given, otherwise download it.
    if len(sys.argv) > 1:
        data = Path(sys.argv[1]).read_bytes()
    else:
        resp = requests.get(GTFS_URL, timeout=120)
        resp.raise_for_status()
        data = resp.content
    zf = zipfile.ZipFile(io.BytesIO(data))

    # 1. Stations = stops with location_type 1 (platform stops point at them).
    stations = {}
    for row in read_csv(zf, "stops.txt"):
        if row["location_type"] == "1":
            stations[row["stop_id"]] = {
                "name": row["stop_name"],
                "lat": float(row["stop_lat"]),
                "lon": float(row["stop_lon"]),
                "routes": set(),
            }
    platform_to_station = {
        r["stop_id"]: r["parent_station"]
        for r in read_csv(zf, "stops.txt")
        if r["parent_station"]
    }

    # 2. Each trip knows its route (line letter/number).
    # Rush-hour "diamond"/express variants (6X, 7X, FX) are folded into their
    # base line so the app never tells a rider to take a train that isn't running.
    base_line = {"6X": "6", "7X": "7", "FX": "F"}
    trip_route = {
        r["trip_id"]: base_line.get(r["route_id"], r["route_id"])
        for r in read_csv(zf, "trips.txt")
    }

    # 3. Collect each trip's ordered station list, then record every pair of
    #    consecutive stations as an edge on that route.
    trip_stops = defaultdict(list)
    for row in read_csv(zf, "stop_times.txt"):
        trip_stops[row["trip_id"]].append(
            (int(row["stop_sequence"]), platform_to_station[row["stop_id"]])
        )
    edges = set()
    for trip_id, stops in trip_stops.items():
        route = trip_route[trip_id]
        stops.sort()
        seq = [s for _, s in stops]
        for a, b in zip(seq, seq[1:]):
            if a != b:
                edges.add((a, b, route))
                edges.add((b, a, route))  # trains run both ways
        for s in seq:
            stations[s]["routes"].add(route)

    # 4. Walking transfers between different stations of one complex.
    transfers = sorted(
        {
            tuple(sorted((r["from_stop_id"], r["to_stop_id"])))
            for r in read_csv(zf, "transfers.txt")
            if r["from_stop_id"] != r["to_stop_id"]
            and r["from_stop_id"] in stations
            and r["to_stop_id"] in stations
        }
    )

    out = {
        "stations": {
            sid: {**s, "routes": sorted(s["routes"])} for sid, s in sorted(stations.items())
        },
        "edges": sorted(edges),
        "transfers": [list(t) for t in transfers],
    }
    OUT_FILE.write_text(json.dumps(out, separators=(",", ":")))
    print(f"Wrote {OUT_FILE}: {len(stations)} stations, {len(edges)} edges, {len(transfers)} transfers")


if __name__ == "__main__":
    main()
