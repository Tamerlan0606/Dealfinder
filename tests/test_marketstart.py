from fastapi.testclient import TestClient
from marketstart.app import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["pages"] == 90

def test_home():
    r = client.get("/")
    assert r.status_code == 200
    assert "MARKETSTART AI" in r.text

def test_sitemap():
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "/guide/launch/checklist" in r.text

def test_redirect():
    r = client.get("/go?src=test", follow_redirects=False)
    assert r.status_code == 302
    assert "source=marketstart" in r.headers["location"]
    assert "channel=test" in r.headers["location"]


def test_factory_inventory_and_jpeg():
    feed = client.get('/api/content-factory').json()
    assert len(feed['posts']) == 12
    assert all(p['media'].endswith('.mp4') for p in feed['posts'])
    assert client.get('/media/tiktok/margin.jpg').headers['content-type'] == 'image/jpeg'
    assert client.get('/media/tiktok/missing.jpg').status_code == 404


def test_factory_validation_and_render(tmp_path, monkeypatch):
    import json, subprocess
    from marketstart import factory
    monkeypatch.setattr(factory, 'CACHE', tmp_path)
    data = {'hook': 'Revenue is not profit.', 'scenes': ['Subtract product cost.', 'Account for fees and delivery.', 'Include returns and ads.'], 'cta': 'Save this checklist.'}
    token = factory.encode_script(data)
    assert factory.decode_script(token) == data
    assert client.get('/media/factory/script/invalid.mp4').status_code == 400
    import pytest
    with pytest.raises(ValueError):
        factory.encode_script({**data, 'scenes': ['x'*131]*3})
    path = factory.render_video(data)
    assert path.stat().st_size > 10000
    assert factory.render_video(data) == path
    # Verify actual media, including dimensions, codecs and audio; not just HTTP success.
    probe = json.loads(subprocess.check_output(['ffprobe','-v','quiet','-print_format','json','-show_streams','-show_format',str(path)]))
    video = next(s for s in probe['streams'] if s['codec_type']=='video')
    assert (video['width'], video['height'], video['codec_name']) == (720, 1280, 'h264')
    assert any(s['codec_name']=='aac' for s in probe['streams'])
    assert 21 <= float(probe['format']['duration']) <= 23
    # Range support allows publisher video probing and avoids re-downloading whole files.
    r = client.get(f'/media/factory/script/{token}.mp4', headers={'Range':'bytes=0-99'})
    assert r.status_code == 206 and len(r.content) == 100
