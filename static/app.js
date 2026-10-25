// AccessRoute NYC frontend: talks to the Flask API and renders the results.
// Accessibility notes: status text goes to a polite live region, focus moves to the
// results heading after a search, and every status has an icon AND a text label.

const $ = (id) => document.getElementById(id);

let stationsByLabel = {};   // "86 St (4 5 6)" -> station id
let currentPlan = null;     // last trip analysis, sent back with follow-up questions
let history = [];           // chat turns for follow-ups: [{role, content}]

// Escape text before putting it in innerHTML (outage text comes from the MTA).
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Announce a message to screen readers via the polite live region.
// Clearing first makes repeated identical messages re-announce.
function announce(msg) {
  const el = $("status");
  el.textContent = "";
  setTimeout(() => (el.textContent = msg), 50);
}

// Load station names into the autocomplete lists.
async function loadStations() {
  try {
    const list = await (await fetch("/api/stations")).json();
    $("station-list").innerHTML = list.map((s) => `<option value="${esc(s.label)}">`).join("");
    list.forEach((s) => (stationsByLabel[s.label] = s.id));
  } catch {
    showError("Couldn't load the station list. Please refresh the page.");
  }
}

// Show/clear the form error; mark the offending inputs for assistive tech.
function showError(msg, invalidIds = []) {
  $("error").textContent = msg;
  $("error").hidden = !msg;
  ["start", "end"].forEach((id) => {
    if (invalidIds.includes(id)) { $(id).setAttribute("aria-invalid", "true"); $(id).setAttribute("aria-errormessage", "error"); }
    else { $(id).removeAttribute("aria-invalid"); $(id).removeAttribute("aria-errormessage"); }
  });
}

// Add a message bubble. A hidden prefix tells screen-reader users who is speaking.
function addBubble(role, text) {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.innerHTML = `<span class="sr-only">${role === "user" ? "You asked: " : "Assistant: "}</span>`;
  div.appendChild(document.createTextNode(text));
  $("chat").appendChild(div);
  div.scrollIntoView({ block: "nearest" });
}

// Icons are decorative (aria-hidden); the text beside them carries the meaning.
const BADGE = {
  ok: ["✔", "Working"], warning: ["▲", "Elevator out – use escalator"], blocked: ["✖", "Not usable"],
};
const VERDICT = {
  clear: ["✔", "Clear to go"], warning: ["▲", "Usable, with a caveat"],
  alternative: ["▲", "Use the alternative route"], no_route: ["✖", "No accessible route right now"],
};

// Render the leg-by-leg directions + per-station outage checks for one route.
function renderRoute(route) {
  $("legs").innerHTML = route.legs.map((l) =>
    `<li><span class="line" aria-hidden="true">${esc(l.route)}</span>` +
    `<span class="sr-only">${esc(l.route)} train: </span>` +
    `${esc(l.from)} to ${esc(l.to)} <span class="muted">(${l.num_stops} stop${l.num_stops === 1 ? "" : "s"})</span></li>`).join("");

  $("checks").innerHTML = route.checks.map((c) => {
    let detail = c.outages.map((o) =>
      `<div class="outage">${esc(o.type)} out: ${esc(o.serving) || "location not given"}` +
      `${o.reason ? " – " + esc(o.reason) : ""}` +
      `${o.estimated_return ? " (back about " + esc(o.estimated_return) + ")" : ""}</div>`).join("");
    if (c.no_ada) detail += `<div class="outage">The MTA does not list ADA equipment at this station.</div>`;
    const [icon, label] = BADGE[c.status];
    return `<li class="${c.status}"><div class="row"><strong>${esc(c.name)}</strong>` +
           `<span class="badge"><span aria-hidden="true">${icon}</span> ${label}</span></div>${detail}</li>`;
  }).join("");
}

// One-sentence summary for the screen-reader announcement.
function summarize(plan) {
  const route = plan.recommended || plan.fastest;
  const problems = route ? route.checks.filter((c) => c.status !== "ok").length : 0;
  let s = `Result loaded: ${VERDICT[plan.verdict][1]}. ${plan.start} to ${plan.end}.`;
  if (route) s += ` ${route.checks.length} stations checked, ${problems} with problems.`;
  return s + " Details are below.";
}

function renderResult(data) {
  const { plan, reply, ai_used, ai_error } = data;
  currentPlan = plan;
  history = [{ role: "assistant", content: reply }];

  const [vIcon, vLabel] = VERDICT[plan.verdict];
  $("verdict").className = `verdict ${plan.verdict}`;
  $("verdict").innerHTML = `<span aria-hidden="true">${vIcon}</span> ${vLabel}`;

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

  // Optional Tavily links (only present for alternative / no_route verdicts).
  const web = plan.web_results || [];
  $("web").hidden = !web.length;
  $("web-links").innerHTML = web.map((w) =>
    `<li><a href="${esc(w.url)}" target="_blank" rel="noopener noreferrer">${esc(w.title || w.url)}` +
    `<span class="sr-only"> (opens in a new tab)</span></a><div class="muted">${esc(w.snippet)}</div></li>`).join("");

  let note = ai_used ? "" : `AI assistant unavailable (${ai_error || "unknown error"}) – showing a standard summary. `;
  if (plan.unmatched_outages) note += `${plan.unmatched_outages} outage record(s) couldn’t be matched to a station. `;
  note += "Always double-check at mta.info/elevator before you travel.";
  $("footnote").textContent = note;

  $("result").hidden = false;
  announce(summarize(plan));
  $("result").focus({ preventScroll: false });   // move keyboard focus to the new results
}

// Use aria-disabled (not `disabled`) so the button keeps keyboard focus while busy.
function setBusy(btn, busy, idleText, busyText) {
  btn.setAttribute("aria-disabled", String(busy));
  btn.textContent = busy ? busyText : idleText;
  $("result").setAttribute("aria-busy", String(busy));
}

$("trip-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if ($("go").getAttribute("aria-disabled") === "true") return;
  showError("");
  const start = stationsByLabel[$("start").value], end = stationsByLabel[$("end").value];
  if (!start || !end) {
    const bad = [!start && "start", !end && "end"].filter(Boolean);
    showError("Please choose both stations from the suggestion list.", bad);
    announce("Error: please choose both stations from the suggestion list.");
    return $(bad[0]).focus();
  }

  setBusy($("go"), true, "Check my route", "Checking live MTA data…");
  announce("Checking live MTA data.");
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
    setBusy($("go"), false, "Check my route", "");
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
    addBubble("assistant", data.reply);   // the chat log is aria-live, so this is announced
  } catch (err) {
    addBubble("assistant", "Sorry, I couldn’t answer that: " + err.message);
  }
});

loadStations();
