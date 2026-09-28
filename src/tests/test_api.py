"""API-level tests with FastAPI's TestClient. Covers every endpoint, the audit
round-trip, determinism over HTTP, and that the /score path rejects junk."""
# TRIAGE_OFFLINE and a temp TRIAGE_DB_PATH are set in conftest.py, which pytest
# loads before this module — so the app never touches the real audit log.
from fastapi.testclient import TestClient

from app import extraction
from app.main import app

client = TestClient(app)

SCENE = "Bloodstained kitchen knife beside the body\nLocked smartphone, powered on"


def test_health_reports_hash_and_extractor():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["extractor"] == "offline-deterministic"
    assert len(body["rules_version_hash"]) == 64


def test_extract_returns_items_without_scores():
    r = client.post("/extract", json={"raw_text": SCENE, "crime_type": "homicide"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert all("category" in i for i in items)
    assert all("final_score" not in i for i in items)


def test_triage_then_audit_roundtrip():
    r = client.post("/triage", json={"raw_text": SCENE, "crime_type": "homicide"})
    assert r.status_code == 200
    data = r.json()
    sid = data["session_id"]
    assert data["schedule"] and data["schedule"][0]["rank"] == 1

    a = client.get(f"/audit/{sid}")
    assert a.status_code == 200
    records = a.json()["records"]
    assert len(records) == len(data["schedule"])
    assert records[0]["crime_type"] == "homicide"
    assert records[0]["rank"] == 1


def test_triage_is_deterministic_over_http():
    body = {"raw_text": SCENE, "crime_type": "homicide"}
    a = client.post("/triage", json=body).json()["schedule"]
    b = client.post("/triage", json=body).json()["schedule"]
    strip = lambda sched: [(s["item"]["item_name"], s["final_score"], s["urgency_flag"]) for s in sched]
    assert strip(a) == strip(b)


def test_score_endpoint_rejects_hallucinated_flag():
    bad = {"crime_type": "homicide", "items": [{
        "item_id": 0, "item_name": "phone", "category": "digital",
        "condition": "intact", "context_flags": ["teleport"], "confidence": 0.8,
    }]}
    assert client.post("/score", json=bad).status_code == 422


def test_score_endpoint_rejects_duplicate_flags():
    bad = {"crime_type": "homicide", "items": [{
        "item_id": 0, "item_name": "junk", "category": "other",
        "condition": "intact", "context_flags": ["near_body", "near_body"], "confidence": 0.8,
    }]}
    assert client.post("/score", json=bad).status_code == 422


def test_audit_captures_raw_output_and_verifies_replay():
    r = client.post("/triage", json={"raw_text": SCENE, "crime_type": "homicide"}).json()
    sid = r["session_id"]
    a = client.get(f"/audit/{sid}", params={"verify": "true"}).json()
    # verbatim model text is stored (offline extractor returns a JSON array string)
    assert a["records"][0]["raw_model_output"]
    v = a["verification"]
    assert v["ruleset_matches_current"] is True
    assert v["all_reproduced"] is True
    assert v["mismatches"] == []


def test_triage_rejects_misspelled_crime_type():
    r = client.post("/triage", json={"raw_text": SCENE, "crime_type": "homocide"})
    assert r.status_code == 422


def test_known_crime_type_is_accepted():
    assert client.post("/triage", json={"raw_text": SCENE, "crime_type": "arson"}).status_code == 200


def test_audit_unknown_session_is_404():
    assert client.get("/audit/does-not-exist").status_code == 404


def test_blank_raw_text_is_rejected():
    for text in ("", "   \n  "):
        assert client.post("/triage", json={"raw_text": text, "crime_type": "homicide"}).status_code == 422
        assert client.post("/extract", json={"raw_text": text}).status_code == 422


class _DownClient:
    def complete(self, system, user, temperature=0.0):
        raise ConnectionError("watsonx unreachable")


def test_model_outage_is_503_not_500(monkeypatch):
    monkeypatch.setattr(extraction, "get_default_client", lambda: _DownClient())
    r = client.post("/triage", json={"raw_text": SCENE, "crime_type": "homicide"})
    assert r.status_code == 503
    assert "watsonx unreachable" in r.json()["detail"]
    assert client.post("/extract", json={"raw_text": SCENE}).status_code == 503


def test_health_reports_watsonx_init_failure(monkeypatch):
    from app import llm_client

    def boom():
        raise RuntimeError("bad credentials")

    monkeypatch.setenv("TRIAGE_OFFLINE", "0")
    monkeypatch.setenv("WATSONX_APIKEY", "x")
    monkeypatch.setenv("WATSONX_PROJECT_ID", "y")
    monkeypatch.setattr(llm_client, "WatsonxClient", boom)
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["extractor"] == "offline-deterministic"
    assert "bad credentials" in body["extractor_fallback_reason"]
