"""AccessRoute NYC - Flask backend.

Endpoints
  GET  /              the single-page frontend
  GET  /api/stations  station list for autocomplete
  POST /api/route     {start, end, need} -> trip analysis from live MTA data
Run with:  python app.py
"""
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from accessroute import mta_feed, planner
from accessroute.subway_graph import ELEVATOR_ONLY, ELEVATOR_OR_ESCALATOR, SubwayGraph

logging.basicConfig(level=logging.INFO)
load_dotenv()  # optional: lets you set PORT in a .env file

app = Flask(__name__, static_folder="static", static_url_path="/static")
graph = SubwayGraph()
NEEDS = {ELEVATOR_ONLY, ELEVATOR_OR_ESCALATOR}


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/stations")
def stations():
    return jsonify(graph.station_list())


@app.post("/api/route")
def route():
    body = request.get_json(silent=True) or {}
    start, end, need = body.get("start"), body.get("end"), body.get("need")
    if start not in graph.stations or end not in graph.stations:
        return jsonify(error="Please choose a start and end station from the list."), 400
    if start == end:
        return jsonify(error="Start and end stations are the same."), 400
    if need not in NEEDS:
        return jsonify(error="Unknown accessibility need."), 400

    try:
        outages = mta_feed.fetch_outages()   # live data
    except Exception as exc:                 # network error or malformed XML
        app.logger.warning("MTA feed failed: %s", exc)
        return jsonify(error="Couldn't get the latest elevator and escalator status from the MTA. Please try again in a minute."), 502

    plan = planner.plan_trip(graph, start, end, need, outages, mta_feed.fetch_ada_station_names())
    return jsonify(plan=plan, summary=planner.summarize(plan), total_outages=len(outages))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
