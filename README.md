# AccessRoute NYC

An accessible subway route checker that alerts riders with mobility needs about
elevator and escalator outages before they travel.

Pick a start and end station and your accessibility need:

- **Elevator only** – any elevator that is out of service at a station you must use blocks it.
- **Elevator or escalator** – an elevator outage is only a warning (use the escalator),
  unless an escalator there is out too, which blocks the station.

The backend pulls the live [MTA elevator/escalator outage XML feed](https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fnyct_ene.xml),
finds the fastest route, checks every station where you board, change trains or exit,
and re-routes around blocked stations when it can. For each station you'll use, it shows
whether the elevator and escalator are working, what is out of service, and the expected return date.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py               # http://localhost:5000
```

No API keys are needed. To change the port, copy `.env.example` to `.env` and set `PORT`.

## Layout

| Path | Purpose |
| --- | --- |
| `app.py` | Flask server and API routes |
| `accessroute/mta_feed.py` | Fetch/parse the MTA XML feeds, station-name normalising |
| `accessroute/subway_graph.py` | Subway map + outage-aware routing (Dijkstra) |
| `accessroute/planner.py` | Matches outages to stations, classifies the trip |
| `scripts/build_stations.py` | Rebuilds `data/stations.json` from the MTA static GTFS |
| `static/` | JavaScript frontend |
| `tests/` | Offline tests (`pytest`) using a sample outage feed |

## Notes and limitations

- The outage feed identifies stations by name only, so names are matched to the subway map
  using normalised names plus the feed's train list. Unmatched outages are reported in the UI.
- The app also reads the MTA's companion `nyct_ene_equipments.xml` feed to learn which stations
  have an elevator or escalator; if that feed is unavailable, all stations are assumed accessible.
- Routes are chosen by number of stops with a transfer penalty, not schedules or real-time
  train positions. Service changes aren't reflected. Always confirm at <https://mta.info/elevator>.
