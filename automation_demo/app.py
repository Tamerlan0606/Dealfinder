from flask import Flask, request, jsonify, render_template_string
from datetime import datetime, timezone
import uuid

app = Flask(__name__)
LEADS = []
EVENTS = []

HTML = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Revenue Automation Demo</title>
<style>
body{font-family:Arial,sans-serif;max-width:980px;margin:40px auto;padding:0 18px;background:#f7f7f7;color:#111}
.card{background:white;border:1px solid #ddd;border-radius:14px;padding:22px;margin:16px 0}
input,select,textarea,button{width:100%;box-sizing:border-box;padding:11px;margin:6px 0 12px;border:1px solid #bbb;border-radius:8px}
button{background:#111;color:white;cursor:pointer;font-weight:700}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.badge{display:inline-block;padding:4px 9px;border-radius:999px;background:#eee;font-weight:700}
small{color:#666}
pre{white-space:pre-wrap;background:#111;color:#eee;padding:14px;border-radius:10px}
@media(max-width:700px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<h1>AI Revenue Automation Demo</h1>
<p>Working proof-of-concept: inbound lead capture → qualification → routing → next-action generation → audit log.</p>
<div class="card">
<form id="leadForm">
<div class="grid">
<div><label>Company</label><input name="company" value="Acme Logistics" required></div>
<div><label>Contact</label><input name="contact" value="Operations Director" required></div>
<div><label>Employees</label><input name="employees" type="number" value="85"></div>
<div><label>Estimated budget ($)</label><input name="budget" type="number" value="4000"></div>
</div>
<label>Need / message</label>
<textarea name="message" rows="4">We need to automate lead follow-up, CRM updates and appointment booking this quarter.</textarea>
<label>Timeline</label>
<select name="timeline">
<option value="0-30 days">0-30 days</option>
<option value="31-90 days">31-90 days</option>
<option value="90+ days">90+ days</option>
</select>
<button type="submit">Run qualification</button>
</form>
</div>
<div class="card">
<h2>Result</h2>
<pre id="result">Submit a lead to run the workflow.</pre>
</div>
<div class="card">
<h2>What this demonstrates</h2>
<ul>
<li>Webhook/API-ready lead intake</li>
<li>Deterministic scoring with transparent rules</li>
<li>HOT / WARM / COLD routing</li>
<li>Recommended sales action and follow-up draft</li>
<li>CRM-style record creation and audit events</li>
<li>Extension points for OpenAI/Claude, HubSpot, GoHighLevel, Slack, email and n8n</li>
</ul>
<small>No fake AI claims: this public demo uses deterministic rules so it runs without third-party keys. LLM and CRM integrations can be added with client credentials.</small>
</div>
<script>
document.getElementById('leadForm').onsubmit=async(e)=>{
e.preventDefault();
const fd=new FormData(e.target); const data=Object.fromEntries(fd.entries());
data.employees=Number(data.employees||0); data.budget=Number(data.budget||0);
const r=await fetch('/api/lead',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
document.getElementById('result').textContent=JSON.stringify(await r.json(),null,2);
};
</script>
</body>
</html>"""

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def qualify(data):
    budget = int(data.get("budget") or 0)
    employees = int(data.get("employees") or 0)
    message = (data.get("message") or "").lower()
    timeline = data.get("timeline") or ""

    score = 0
    reasons = []

    if budget >= 3000:
        score += 35; reasons.append("budget >= $3k")
    elif budget >= 1000:
        score += 20; reasons.append("budget >= $1k")
    elif budget > 0:
        score += 5; reasons.append("budget disclosed")

    if employees >= 50:
        score += 20; reasons.append("50+ employees")
    elif employees >= 10:
        score += 10; reasons.append("10+ employees")

    intent_terms = ["automate", "automation", "crm", "follow-up", "follow up", "booking", "agent", "integration", "api", "n8n"]
    hits = [t for t in intent_terms if t in message]
    if hits:
        score += min(30, 6 * len(hits))
        reasons.append("automation intent: " + ", ".join(hits[:5]))

    if timeline == "0-30 days":
        score += 20; reasons.append("near-term timeline")
    elif timeline == "31-90 days":
        score += 10; reasons.append("medium-term timeline")

    score = min(score, 100)
    if score >= 70:
        tier = "HOT"
        action = "Book discovery call within 1 business day"
    elif score >= 40:
        tier = "WARM"
        action = "Send tailored workflow outline and ask 3 qualification questions"
    else:
        tier = "COLD"
        action = "Nurture; do not spend manual sales time yet"

    company = data.get("company") or "your company"
    followup = (
        f"Thanks for the details on {company}. Based on the workflow you described, "
        f"the next useful step is to map the trigger, systems involved, and handoff rules. "
        f"If you send the current CRM/tool stack and one example lead journey, I can turn it into a concrete automation blueprint."
    )
    return score, tier, action, reasons, followup

@app.get("/")
def index():
    return render_template_string(HTML)

@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "ai-revenue-automation-demo"})

@app.post("/api/lead")
def create_lead():
    data = request.get_json(force=True, silent=False) or {}
    score, tier, action, reasons, followup = qualify(data)
    record = {
        "id": str(uuid.uuid4()),
        "created_at": utcnow(),
        "company": data.get("company"),
        "contact": data.get("contact"),
        "employees": int(data.get("employees") or 0),
        "budget": int(data.get("budget") or 0),
        "timeline": data.get("timeline"),
        "message": data.get("message"),
        "score": score,
        "tier": tier,
        "next_action": action,
        "qualification_reasons": reasons,
        "followup_draft": followup,
    }
    LEADS.append(record)
    EVENTS.append({"at": utcnow(), "type": "lead_qualified", "lead_id": record["id"], "tier": tier})
    return jsonify(record), 201

@app.get("/api/leads")
def list_leads():
    return jsonify({"count": len(LEADS), "items": LEADS[-50:]})

@app.get("/api/events")
def list_events():
    return jsonify({"count": len(EVENTS), "items": EVENTS[-100:]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
