"""Sprint-0 smoke test (U0.2): the app imports and /health responds.
Requires no secrets and no network, so CI is green out of the box.
"""
from fastapi.testclient import TestClient

import app


def test_app_imports():
    assert app.app is not None


def test_health_ok():
    client = TestClient(app.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
