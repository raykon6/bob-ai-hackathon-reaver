"""MCP server — exposes the triage pipeline as tools IBM Bob can call directly.

This is what makes Bob *load-bearing*: an investigator talks to Bob in natural
language; Bob calls these MCP tools. The tool boundary enforces the core rule:

    * extract_evidence   -> structures/classifies text (the LLM's job)
    * score_evidence     -> PURE deterministic Python. Bob passes data through it
                            but never computes the score itself.
    * triage_scene       -> the full pipeline in one call.

score_evidence and triage_scene write to the same SQLite audit log as the API, so a
Bob-driven run is auditable and replayable too (GET /audit/{session_id}?verify=true).

Bob discovers this server from `.bob/mcp.json` at the repo root (standard
`mcpServers` schema). Run standalone for a smoke test:  python -m app.mcp_server
"""
from __future__ import annotations

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

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
from .scoring import score_and_rank

mcp = _MCPServer("evidence-triage")


@mcp.tool()
def extract_evidence(raw_text: str) -> list[dict]:
    """Extract & classify crime-scene items from free text into the fixed
    evidence taxonomy. Does NOT score or rank. Returns structured items."""
    return [i.model_dump() for i in extract_items(validate_raw_text(raw_text))]


@mcp.tool()
def score_evidence(items: list[dict], crime_type: str = "unknown") -> dict:
    """Deterministically score and rank already-extracted items for FSL
    submission. Pure function — identical input yields identical output, stamped
    with the ruleset hash. Bob must call this rather than reasoning out scores.
    Logs the run to the audit trail and returns its session_id."""
    crime_type = validate_crime_type(crime_type)
    rules = get_rules()
    parsed = [ExtractedItem.model_validate(i) for i in items]
    ranked = score_and_rank(parsed, crime_type, rules)
    session_id = str(uuid.uuid4())
    log_run(session_id, ranked, crime_type, DEFAULT_DB_PATH)
    return {
        "session_id": session_id,
        "rules_version": rules.version,
        "rules_version_hash": rules.version_hash,
        "schedule": [s.model_dump() for s in ranked],
    }


@mcp.tool()
def triage_scene(raw_text: str, crime_type: str = "unknown") -> dict:
    """Full pipeline in one call: extract (LLM) then score & rank (deterministic).
    Logs the run and returns the ranked FSL examination schedule + session_id."""
    crime_type = validate_crime_type(crime_type)
    raw_text = validate_raw_text(raw_text)
    rules = get_rules()
    items, raw_output = extract_items_with_raw(raw_text)
    ranked = score_and_rank(items, crime_type, rules)
    session_id = str(uuid.uuid4())
    log_run(session_id, ranked, crime_type, DEFAULT_DB_PATH, raw_model_output=raw_output)
    return {
        "session_id": session_id,
        "crime_type": crime_type,
        "rules_version": rules.version,
        "rules_version_hash": rules.version_hash,
        "schedule": [s.model_dump() for s in ranked],
    }


if __name__ == "__main__":
    try:
        mcp.run()
    except KeyboardInterrupt:
        print("\nevidence-triage MCP server stopped.")
