"""Case-tuned (dynamic) rulesets: the model proposes, the engine clamps, freezes and
hashes — and scoring stays exactly reproducible from the stored ruleset."""
import json
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

from app import audit, llm_client
from app.extraction import extract_items
from app.main import app
from app.models import Category
from app.rules import RulesConfig, get_rules
from app.ruleset_generator import BOUNDS, EVALUATION_ANGLES, generate_case_ruleset
from app.scoring import score_and_rank

client = TestClient(app)
BASE = get_rules()
SCENE = (
    "Bloodstained kitchen knife beside the body\n"
    "Wet, partially burnt t-shirt in the backyard\n"
    "Single strand of hair on the victim's collar\n"
    "Locked smartphone, screen cracked, powered on"
)
ITEMS = extract_items(SCENE)


class Scripted:
    """A fake model that returns fixed text (or raises) and counts calls."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), 0

    def complete(self, system, user, temperature=0.0):
        self.calls += 1
        r = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(r, Exception):
            raise r
        return r


def _in_bounds(rules: RulesConfig):
    lo, hi = BOUNDS["base_weight"]
    assert set(rules.category_base_weights) == {c.value for c in Category}
    assert all(lo <= v <= hi for v in rules.category_base_weights.values())
    d = rules.degradation_risk_by_condition
    assert d["intact"] <= d["partially_exposed"] <= d["degraded"]
    assert set(BASE.force_urgent_flags) <= set(rules.force_urgent_flags)


def test_offline_case_ruleset_is_bounded_hashed_and_explained():
    rules, info, _ = generate_case_ruleset(ITEMS, "homicide", BASE)  # offline in tests
    _in_bounds(rules)
    assert rules.version_hash.startswith("case-") and info.version_hash == rules.version_hash
    assert rules.version == f"{BASE.version}+case"
    assert info.source == "heuristic"
    assert set(info.evaluation_angles) == set(EVALUATION_ANGLES)
    assert info.adjustments, "a real scene should move at least one parameter"


def test_case_ruleset_and_schedule_are_deterministic():
    r1, _, _ = generate_case_ruleset(ITEMS, "homicide", BASE)
    r2, _, _ = generate_case_ruleset(ITEMS, "homicide", BASE)
    assert r1.version_hash == r2.version_hash
    s1 = [(s.item.item_id, s.final_score, s.urgency_flag) for s in score_and_rank(ITEMS, "homicide", r1)]
    s2 = [(s.item.item_id, s.final_score, s.urgency_flag) for s in score_and_rank(ITEMS, "homicide", r2)]
    assert s1 == s2


def test_hostile_model_proposal_is_clamped_not_trusted():
    hostile = json.dumps({
        "category_base_weights": {"biological": 999, "digital": -5, "magic": 7},
        "crime_multipliers": {"biological": 50, "trace": 0.01},
        "degradation_risk_by_condition": {"intact": 14, "partially_exposed": 3, "degraded": 1},
        "context_flag_modifiers": {"near_body": 1e9, "teleport": 5},
        "score_urgent": "high",
        "force_urgent_flags": ["near_body", "teleport"],  # tries to drop the safety floor
        "rationale": "trust me",
    })
    rules, info, raw = generate_case_ruleset(ITEMS, "homicide", BASE, client=Scripted("Sure! " + hostile))
    _in_bounds(rules)
    assert raw.startswith("Sure!")  # verbatim proposal is kept for the audit trail
    assert rules.category_base_weights["biological"] == BOUNDS["base_weight"][1]
    assert rules.category_base_weights["digital"] == BOUNDS["base_weight"][0]
    assert rules.crime_type_multipliers["homicide"]["biological"] == BOUNDS["multiplier"][1]
    assert rules.crime_type_multipliers["homicide"]["trace"] == BOUNDS["multiplier"][0]
    assert rules.context_flag_modifiers["near_body"] == BOUNDS["flag_modifier"][1]
    assert rules.score_urgent == BASE.score_urgent  # non-numeric -> baseline
    assert "near_body" in rules.force_urgent_flags
    notes = " ".join(info.clamps)
    assert "magic" in notes and "teleport" in notes and "safety floor" in notes
    assert "re-ordered" in notes


def test_unparseable_proposal_falls_back_to_heuristic_with_reason():
    model = Scripted("no json here", "still nothing")
    rules, info, _ = generate_case_ruleset(ITEMS, "homicide", BASE, client=model)
    assert model.calls == 2  # one retry with the error fed back
    assert info.source == "heuristic" and info.fallback_reason
    _in_bounds(rules)


def test_model_outage_falls_back_and_says_why():
    _, info, _ = generate_case_ruleset(ITEMS, "arson", BASE, client=Scripted(ConnectionError("down")))
    assert info.source == "heuristic" and "down" in info.fallback_reason


def test_static_triage_is_unchanged():
    body = client.post("/triage", json={"raw_text": SCENE, "crime_type": "homicide"}).json()
    assert body["ruleset_mode"] == "static" and body["case_ruleset"] is None
    assert body["rules_version_hash"] == BASE.version_hash


def test_dynamic_triage_is_logged_and_replays_exactly():
    body = client.post("/triage", json={"raw_text": SCENE, "crime_type": "homicide",
                                        "dynamic_rules": True}).json()
    assert body["ruleset_mode"] == "dynamic"
    assert body["rules_version_hash"].startswith("case-")
    assert body["case_ruleset"]["version_hash"] == body["rules_version_hash"]
    assert all(s["rules_version_hash"] == body["rules_version_hash"] for s in body["schedule"])

    v = client.get(f"/audit/{body['session_id']}", params={"verify": "true"}).json()["verification"]
    assert v["ruleset_mode"] == "dynamic"
    assert v["ruleset_integrity_ok"] is True
    assert v["all_reproduced"] is True and v["mismatches"] == []


def test_tampered_stored_ruleset_fails_verification():
    sid = client.post("/triage", json={"raw_text": SCENE, "crime_type": "homicide",
                                       "dynamic_rules": True}).json()["session_id"]
    with sqlite3.connect(audit.DEFAULT_DB_PATH) as conn:
        stored = json.loads(conn.execute(
            "SELECT ruleset_json FROM evidence_log WHERE session_id=? LIMIT 1", (sid,)).fetchone()[0])
        stored["parameters"]["category_base_weights"]["biological"] = 1.0  # quiet edit
        conn.execute("UPDATE evidence_log SET ruleset_json=? WHERE session_id=?", (json.dumps(stored), sid))
    v = client.get(f"/audit/{sid}", params={"verify": "true"}).json()["verification"]
    assert v["ruleset_integrity_ok"] is False and v["all_reproduced"] is False


def test_ruleset_preview_endpoint():
    r = client.post("/ruleset", json={"raw_text": SCENE, "crime_type": "burglary"})
    assert r.status_code == 200
    info = r.json()["case_ruleset"]
    assert info["version_hash"].startswith("case-") and set(info["evaluation_angles"]) == set(EVALUATION_ANGLES)


# ---- Bob Shell client -------------------------------------------------------

def _script(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return f'"{sys.executable}" "{p}"'


def test_bob_shell_client_is_selected_and_pipes_prompt(tmp_path, monkeypatch):
    cmd = _script(tmp_path, "echo_len.py",
                  "import sys\ndata = sys.stdin.read()\nprint('got', len(data) > 0)\n")
    monkeypatch.setenv("TRIAGE_OFFLINE", "0")
    monkeypatch.setenv("BOB_SHELL_CMD", cmd)
    c = llm_client.get_default_client()
    assert isinstance(c, llm_client.ShellClient)
    assert llm_client.describe_client(c) == "bob-shell"
    assert c.complete("system", "user") == "got True"


def test_bob_shell_prompt_file_mode_and_chatty_json(tmp_path, monkeypatch):
    # A chatty wrapper around valid extraction JSON must still parse (then validate).
    item = {"item_name": "knife", "category": "biological", "location_found": "kitchen",
            "condition": "degraded", "context_flags": ["biological_material"], "confidence": 0.9}
    body = (
        "import sys\n"
        "assert open(sys.argv[1], encoding='utf-8').read()\n"
        f"print('Here you go:', {json.dumps(json.dumps([item]))}, 'Done.')\n"
    )
    cmd = _script(tmp_path, "bob.py", body) + ' "{prompt_file}"'
    shell = llm_client.ShellClient(cmd)
    items = extract_items("knife", client=shell)
    assert len(items) == 1 and items[0].category.value == "biological"


def test_bob_shell_failure_raises(tmp_path):
    cmd = _script(tmp_path, "fail.py", "import sys\nsys.exit(3)\n")
    with pytest.raises(RuntimeError, match="exited 3"):
        llm_client.ShellClient(cmd).complete("s", "u")
