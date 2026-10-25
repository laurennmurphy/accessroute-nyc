// AccessRoute NYC frontend: talks to the Flask API and renders the results.

const $ = (id) => document.getElementById(id);

let stationsByLabel = {};   // "86 St (4 5 6)" -> station id
let currentPlan = null;     // last trip analysis, sent back with follow-up questions
let history = [];           // chat turns for follow-ups: [{role, content}]

// Escape text before putting it in innerHTML (outage text comes from the MTA).
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Load station names into the autocomplete lists.
async function loadStations() {
  const list = await (await fetch("/api/stations")).json();
  $("station-list").innerHTML = list.map((s) => `<option value="${esc(s.label)}">`).join("");
  list.forEach((s) => (stationsByLabel[s.label] = s.id));
}

function showError(msg) {
  $("error").textContent = msg;
  $("error").hidden = !msg;
}

// Add a message bubble to the chat area.
function addBubble(role, text) {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.textContent = text;
  $("chat").appendChild(div);
  div.scrollIntoView({ block: "nearest" });
}

const BADGE = { ok: "✅ Working", warning: "⚠️ Elevator out", blocked: "⛔ Not usable" };

// Render the leg-by-leg directions + per-station outage checks for one route.
function renderRoute(route) {
  $("legs").innerHTML = route.legs.map((l) =>
    `<li><span class="line">${esc(l.route)}</span> ${esc(l.from)} → ${esc(l.to)}
     <span class="muted">(${l.num_stops} stop${l.num_stops === 1 ? "" : "s"})</span></li>`).join("");

  $("checks").innerHTML = route.checks.map((c) => {
    let detail = c.outages.map((o) =>
      `<div class="outage">${esc(o.type)}: ${esc(o.serving) || "n/a"}` +
      `${o.reason ? " — " + esc(o.reason) : ""}` +
      `${o.estimated_return ? " (back ~" + esc(o.estimated_return) + ")" : ""}</div>`).join("");
    if (c.no_ada) detail += `<div class="outage">Not listed as having ADA equipment by the MTA.</div>`;
    return `<li class="${c.status}"><strong>${esc(c.name)}</strong> <span>${BADGE[c.status]}</span>${detail}</li>`;
  }).join("");
}

function renderResult(data) {
  const { plan, reply, ai_used, ai_error } = data;
  currentPlan = plan;
  history = [{ role: "assistant", content: reply }];

  const labels = {
    clear: "Clear to go", warning: "Usable — with a caveat",
    alternative: "Use the alternative route", no_route: "No accessible route right now",
  };
  $("verdict").className = `verdict ${plan.verdict}`;
  $("verdict").textContent = labels[plan.verdict];

  $("chat").innerHTML = "";
  addBubble("assistant", reply);

  // Show the recommended route; if none, show the fastest route so the user sees what's blocked.
  const shown = plan.recommended || plan.fastest;
  $("route-title").textContent = plan.recommended
    ? (plan.verdict === "alternative" ? "Recommended alternative route" : "Recommended route")
    : "Fastest route (blocked)";
  $("route-title").hidden = !shown;
  if (shown) renderRoute(shown);
  else { $("legs").innerHTML = ""; $("checks").innerHTML = ""; }

  let note = ai_used ? "" : `AI assistant unavailable (${ai_error || "unknown error"}) — showing a standard summary. `;
  if (plan.unmatched_outages) note += `${plan.unmatched_outages} outage record(s) couldn’t be matched to a station. `;
  note += "Always double-check at mta.info/elevator before you travel.";
  $("footnote").textContent = note;
  $("result").hidden = false;
}

$("trip-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  const start = stationsByLabel[$("start").value], end = stationsByLabel[$("end").value];
  if (!start || !end) return showError("Please pick both stations from the suggestion list.");

  $("go").disabled = true; $("go").textContent = "Checking live MTA data…";
  try {
    const res = await fetch("/api/route", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start, end, need: document.querySelector("input[name=need]:checked").value }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Something went wrong.");
    renderResult(data);
  } catch (err) {
    showError(err.message);
    $("result").hidden = true;
  } finally {
    $("go").disabled = false; $("go").textContent = "Check my route";
  }
});

// Follow-up questions about the current trip.
$("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = $("chat-input").value.trim();
  if (!question || !currentPlan) return;
  $("chat-input").value = "";
  addBubble("user", question);
  try {
    const res = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: currentPlan, history, question }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    history.push({ role: "user", content: question }, { role: "assistant", content: data.reply });
    addBubble("assistant", data.reply);
  } catch (err) {
    addBubble("assistant", "Sorry, I couldn’t answer that: " + err.message);
  }
});

loadStations();
