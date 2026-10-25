"""AccessRoute NYC - Flask backend.

Endpoints
  GET  /              the single-page frontend
  GET  /api/stations  station list for autocomplete
  POST /api/route     {start, end, need} -> trip analysis + AI recommendation
  POST /api/chat      follow-up questions about a trip analysis
Run with:  python app.py
"""
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
load_dotenv()  # read NVIDIA_API_KEY etc. from .env before importing modules that use them

from accessroute import ai_client, mta_feed, planner  # noqa: E402
from accessroute.subway_graph import ELEVATOR_ONLY, ELEVATOR_OR_ESCALATOR, SubwayGraph  # noqa: E402

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
        return jsonify(error="Couldn't reach the MTA outage feed. Please try again in a minute."), 502

    plan = planner.plan_trip(graph, start, end, need, outages, mta_feed.fetch_ada_station_names())
    reply, ai_used, ai_error = ai_client.ask(plan)
    return jsonify(plan=plan, reply=reply, ai_used=ai_used, ai_error=ai_error,
                   total_outages=len(outages))


@app.post("/api/chat")
def chat():
    body = request.get_json(silent=True) or {}
    plan, question = body.get("plan"), (body.get("question") or "").strip()
    history = [m for m in body.get("history", [])
               if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
    if not plan or not question:
        return jsonify(error="Missing trip or question."), 400
    reply, ai_used, ai_error = ai_client.ask(plan, history, question[:500])
    if not ai_used:
        reply = f"The AI assistant isn't available right now ({ai_error}). " + reply
    return jsonify(reply=reply)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
