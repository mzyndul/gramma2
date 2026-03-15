import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server.app import app
from server.service import clear_cache


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /improve
# ---------------------------------------------------------------------------

def test_fake_backend(client):
    resp = client.post("/improve", json={"text": "he go to store", "backend": "fake"})
    assert resp.status_code == 200
    assert resp.json()["suggestions"] == ["Fixed: he go to store"]


@patch("server.backends.call_local")
def test_local_backend(mock_call, client):
    mock_call.return_value = "He went to the store."
    resp = client.post("/improve", json={"text": "he go to store", "backend": "local"})
    assert resp.status_code == 200
    assert resp.json()["suggestions"] == ["He went to the store."]


@patch("server.backends.call_codex")
def test_codex_backend(mock_call, client):
    mock_call.return_value = "He went to the store."
    resp = client.post("/improve", json={"text": "he go to store", "backend": "codex"})
    assert resp.status_code == 200
    assert resp.json()["suggestions"] == ["He went to the store."]


@patch("server.backends.call_local")
def test_default_backend_is_local(mock_call, client):
    mock_call.return_value = "Fixed text"
    client.post("/improve", json={"text": "test"})
    mock_call.assert_called_once()


def test_unknown_backend(client):
    resp = client.post("/improve", json={"text": "test", "backend": "unknown"})
    assert resp.status_code == 400
    assert "unknown backend" in resp.json()["error"]


def test_improve_empty_text(client):
    resp = client.post("/improve", json={"text": ""})
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_improve_missing_text(client):
    resp = client.post("/improve", json={})
    assert resp.status_code == 400
    assert "error" in resp.json()


@patch("server.backends.call_local")
def test_backend_failure(mock_call, client):
    mock_call.side_effect = RuntimeError("Connection refused")
    resp = client.post("/improve", json={"text": "he go to store", "backend": "local"})
    assert resp.status_code == 500
    assert "error" in resp.json()


def test_cors_headers(client):
    resp = client.post(
        "/improve",
        json={"text": "test", "backend": "fake"},
        headers={"Origin": "http://example.com"},
    )
    assert resp.headers["Access-Control-Allow-Origin"] == "*"


def test_options_preflight(client):
    resp = client.options(
        "/improve",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["Access-Control-Allow-Origin"] == "*"


def test_wrong_path(client):
    resp = client.post("/nonexistent", json={"text": "hello"})
    assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# POST /improve-batch
# ---------------------------------------------------------------------------

def test_improve_batch_fake(client):
    resp = client.post(
        "/improve-batch",
        json={"sentences": ["He go to store.", "She dont like it."], "backend": "fake"},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 2
    assert results[0]["original"] == "He go to store."
    assert results[0]["suggestion"] == "Fixed: He go to store."
    assert results[1]["original"] == "She dont like it."


@patch("server.backends.call_local")
def test_improve_batch_local(mock_call, client):
    mock_call.side_effect = lambda text: f"Corrected: {text}"
    resp = client.post(
        "/improve-batch",
        json={"sentences": ["Bad grammar."], "backend": "local"},
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["suggestion"] == "Corrected: Bad grammar."


@patch("server.backends.call_codex")
def test_improve_batch_codex(mock_call, client):
    mock_call.side_effect = lambda text: f"Codex: {text}"
    resp = client.post(
        "/improve-batch",
        json={"sentences": ["Bad grammar."], "backend": "codex"},
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["suggestion"] == "Codex: Bad grammar."


def test_improve_batch_empty_list(client):
    resp = client.post("/improve-batch", json={"sentences": [], "backend": "fake"})
    assert resp.status_code == 400
    assert "non-empty" in resp.json()["error"]


def test_improve_batch_invalid_sentence_item(client):
    resp = client.post(
        "/improve-batch", json={"sentences": ["ok", ""], "backend": "fake"}
    )
    assert resp.status_code == 400
    assert "non-empty string" in resp.json()["error"]


def test_improve_batch_unknown_backend(client):
    resp = client.post(
        "/improve-batch", json={"sentences": ["hello"], "backend": "nope"}
    )
    assert resp.status_code == 400
    assert "unknown backend" in resp.json()["error"]


def test_improve_batch_preserves_order(client):
    sentences = [f"Sentence {i}." for i in range(5)]
    resp = client.post(
        "/improve-batch", json={"sentences": sentences, "backend": "fake"}
    )
    assert resp.status_code == 200
    for i, r in enumerate(resp.json()["results"]):
        assert r["original"] == f"Sentence {i}."


@patch("server.service.improve_single")
def test_improve_batch_parallel(mock_single, client):
    def slow_improve(text, backend):
        time.sleep(0.3)
        return f"Fixed: {text}"

    mock_single.side_effect = slow_improve
    sentences = ["A.", "B.", "C."]
    start = time.monotonic()
    resp = client.post(
        "/improve-batch", json={"sentences": sentences, "backend": "fake"}
    )
    elapsed = time.monotonic() - start
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 3
    assert elapsed < 0.7


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------

def test_cache_hit_avoids_backend_call(client):
    with patch("server.backends.call_fake") as mock_call:
        mock_call.return_value = "Fixed: hello"
        # First call — cache miss
        client.post("/improve", json={"text": "hello", "backend": "fake"})
        assert mock_call.call_count == 1
        # Second call — cache hit
        client.post("/improve", json={"text": "hello", "backend": "fake"})
        assert mock_call.call_count == 1


def test_different_backends_have_separate_cache(client):
    with patch("server.backends.call_fake") as mock_fake, \
         patch("server.backends.call_local") as mock_local:
        mock_fake.return_value = "Fake result"
        mock_local.return_value = "Local result"

        client.post("/improve", json={"text": "hello", "backend": "fake"})
        client.post("/improve", json={"text": "hello", "backend": "local"})

        mock_fake.assert_called_once()
        mock_local.assert_called_once()


def test_backend_failure_does_not_cache(client):
    with patch("server.backends.call_fake") as mock_call:
        mock_call.side_effect = RuntimeError("fail")
        resp = client.post("/improve", json={"text": "hello", "backend": "fake"})
        assert resp.status_code == 500

        # Fix the backend and retry — should call again (not cached)
        mock_call.side_effect = None
        mock_call.return_value = "Fixed: hello"
        resp = client.post("/improve", json={"text": "hello", "backend": "fake"})
        assert resp.status_code == 200
        assert mock_call.call_count == 2
