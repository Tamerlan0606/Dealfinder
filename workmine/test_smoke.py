import os
os.environ["WORKMINE_PAYMENT_MODE"] = "open"
os.environ["WORKMINE_DB_PATH"] = "/tmp/workmine-test.db"

from fastapi.testclient import TestClient
from workmine.main import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_normalize():
    r = client.post("/v1/text/normalize", json={"text": "  Hello   world  "})
    assert r.status_code == 200
    assert r.json()["text"] == "Hello world"


def test_keywords():
    r = client.post("/v1/text/keywords", json={"text": "agent agent payment payment api", "limit": 2})
    assert r.status_code == 200
    assert len(r.json()["keywords"]) == 2


def test_repair_json():
    r = client.post("/v1/json/repair", json={"text": "{'ok': true,}"})
    assert r.status_code == 200
    assert r.json()["value"]["ok"] is True


def test_redact():
    r = client.post("/v1/text/redact", json={"text": "mail me at a@example.com"})
    assert r.status_code == 200
    assert "REDACTED_EMAIL" in r.json()["text"]
