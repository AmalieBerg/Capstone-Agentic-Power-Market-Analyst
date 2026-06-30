"""Tests for the FastAPI app (U5.1). Skips if fastapi isn't installed."""
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
import app as appmod


client = TestClient(appmod.app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_index_serves_html():
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_shape_response_answered():
    res = {"answer": "X is offline [1].", "refused": False,
           "citations": [{"index": 1, "label": "X", "zone": "DE-LU", "source_url": "u"}],
           "sources": [{"index": 1, "label": "X", "zone": "DE-LU", "source_url": "u", "snippet": "s"}]}
    out = appmod.shape_response("q", res)
    assert out["refused"] is False
    assert out["citations"][0]["label"] == "X"
    assert out["snippets"][0]["snippet"] == "s"


def test_shape_response_refused():
    out = appmod.shape_response("bitcoin?", {"answer": "no", "refused": True, "citations": [], "sources": []})
    assert out["refused"] is True and out["citations"] == [] and out["snippets"] == []