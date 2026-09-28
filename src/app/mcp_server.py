"""MCP server — exposes the triage pipeline as tools IBM Bob can call directly.

This is what makes Bob *load-bearing*: an investigator talks to Bob in natural
language; Bob calls these MCP tools. The tool boundary enforces the core rule:

    * extract_evidence       -> structures/classifies text (the LLM's job)
    * generate_case_ruleset  -> the LLM PROPOSES case-tuned scoring parameters; the
                                engine clamps, freezes and hashes them (no scores)
    * score_evidence         -> PURE deterministic Python. Bob passes data through it
                                but never computes the score itself.
    * triage_scene           -> the full pipeline in one call.

score_evidence and triage_scene write to the same SQLite audit log as the API, so a
Bob-driven run is auditable and replayable too (GET /audit/{session_id}?verify=true).
With dynamic_rules=True the frozen case ruleset is stored with the run.

Bob discovers this server from `.bob/mcp.json` at the repo root (standard
`mcpServers` schema). Run standalone for a smoke test:  python -m app.mcp_server
"""
from __future__ import annotations

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import json
import uuid

# mcp v1 exposes FastMCP; mcp v2 renamed it to MCPServer (same .tool()/.run() API).
# Support both so the server runs regardless of which version is installed.
try:
    from mcp.server.fastmcp import FastMCP as _MCPServer  # mcp < 2
except ModuleNotFoundError:
    from mcp.server.mcpserver import MCPServer as _MCPServer  # mcp >= 2

from .audit import DEFAULT_DB_PATH, log_run
from .extraction import extract_items, extract_items_with_raw
from .models import ExtractedItem, validate_crime_type, validate_raw_text
from .rules import get_rules
from .ruleset_generator import generate_case_ruleset
from .scoring import score_and_rank

mcp = _MCPServer("evidence-triage")


def _score_and_log(items, crime_type, dynamic_rules, raw_output=None) -> dict:
    rules, info, ruleset_json = get_rules(), None, None
    if dynamic_rules:
        rules, info, raw_proposal = generate_case_ruleset(items, crime_type, get_rules())
        ruleset_json = json.dumps(
            {"version": rules.version, "parameters": info.parameters,
             "raw_proposal": raw_proposal, "source": info.source},
            sort_keys=True,
        )
    ranked = score_and_rank(items, crime_type, rules)
    session_id = str(uuid.uuid4())
    log_run(session_id, ranked, crime_type, DEFAULT_DB_PATH,
            raw_model_output=raw_output, ruleset_json=ruleset_json)
    out = {
        "session_id": session_id,
        "crime_type": crime_type,
        "ruleset_mode": "dynamic" if info else "static",
        "rules_version": rules.version,
        "rules_version_hash": rules.version_hash,
        "schedule": [s.model_dump() for s in ranked],
    }
    if info:
        out["case_ruleset"] = info.model_dump(exclude={"parameters"})
    return out


@mcp.tool()
def extract_evidence(raw_text: str) -> list[dict]:
    """Extract & classify crime-scene items from free text into the fixed
    evidence taxonomy. Does NOT score or rank. Returns structured items."""
    return [i.model_dump() for i in extract_items(validate_raw_text(raw_text))]


@mcp.tool(name="generate_case_ruleset")
def generate_case_ruleset_tool(raw_text: str, crime_type: str = "unknown") -> dict:
    """Propose a ruleset tuned to THIS scene (base weights, crime multipliers,
    degradation scale, context-flag modifiers, urgency threshold) across eight
    evaluation angles. The proposal is clamped to hard bounds, the force-urgent
    safety floor is kept, and the result is frozen + SHA-256 hashed. Returns the
    ruleset and a diff against the base rules. Does NOT score any item."""
    crime_type = validate_crime_type(crime_type)
    items = extract_items(validate_raw_text(raw_text))
    _, info, _ = generate_case_ruleset(items, crime_type, get_rules())
    return info.model_dump()


@mcp.tool()
def score_evidence(items: list[dict], crime_type: str = "unknown", dynamic_rules: bool = False) -> dict:
    """Deterministically score and rank already-extracted items for FSL
    submission. Pure function — identical input yields identical output, stamped
    with the ruleset hash. With dynamic_rules=True the scene first gets a frozen,
    hashed case-tuned ruleset. Bob must call this rather than reasoning out scores.
    Logs the run to the audit trail and returns its session_id."""
    crime_type = validate_crime_type(crime_type)
    parsed = [ExtractedItem.model_validate(i) for i in items]
    return _score_and_log(parsed, crime_type, dynamic_rules)


@mcp.tool()
def triage_scene(raw_text: str, crime_type: str = "unknown", dynamic_rules: bool = False) -> dict:
    """Full pipeline in one call: extract (LLM), optionally generate a frozen
    case-tuned ruleset (dynamic_rules=True), then score & rank deterministically.
    Logs the run and returns the ranked FSL examination schedule + session_id."""
    crime_type = validate_crime_type(crime_type)
    raw_text = validate_raw_text(raw_text)
    items, raw_output = extract_items_with_raw(raw_text)
    return _score_and_log(items, crime_type, dynamic_rules, raw_output)


if __name__ == "__main__":
    try:
        mcp.run()
    except KeyboardInterrupt:
        print("\nevidence-triage MCP server stopped.")
