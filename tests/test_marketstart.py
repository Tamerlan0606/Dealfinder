from fastapi.testclient import TestClient
from marketstart.app import app

client = TestClient(app)

def test_health():
    r=client.get("/health")
    assert r.status_code==200
    assert r.json()["pages"]==90

def test_home():
    r=client.get("/")
    assert r.status_code==200
    assert "MARKETSTART AI" in r.text

def test_sitemap():
    r=client.get("/sitemap.xml")
    assert r.status_code==200
    assert "/guide/launch/checklist" in r.text

def test_redirect():
    r=client.get("/go?src=test", follow_redirects=False)
    assert r.status_code==302
    assert "source=marketstart" in r.headers["location"]\n    assert "channel=test" in r.headers["location"]
