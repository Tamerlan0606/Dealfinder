# AI Revenue Automation Demo

Public proof-of-concept for client work in AI / CRM automation.

## What it does
- Accepts an inbound lead through a web form or JSON API.
- Scores the lead using transparent business rules.
- Routes it into HOT / WARM / COLD.
- Generates the recommended next action and a follow-up draft.
- Stores a simple CRM-style record and audit event in memory.
- Exposes health, lead, and event endpoints.

## Why deterministic rules?
The public demo intentionally does not pretend to use an LLM when no client API key is configured. The architecture is ready to add OpenAI/Claude, HubSpot, GoHighLevel, Salesforce, Slack, Gmail, n8n, Make or custom APIs with client credentials.

## API
POST /api/lead

Example:
```json
{
  "company": "Acme Logistics",
  "contact": "Operations Director",
  "employees": 85,
  "budget": 4000,
  "message": "We need CRM follow-up and booking automation",
  "timeline": "0-30 days"
}
```

## Local run
```bash
pip install -r requirements.txt
python app.py
```

## Production
```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```
