"""FastAPI application.

Endpoints:
  POST /extract          raw_text, crime_type -> [ExtractedItem]   (Bob only)
  POST /score            [ExtractedItem], crime_type -> [ScoredItem] ranked (pure)
  POST /triage           raw_text, crime_type[, dynamic_rules] -> full pipeline, logged
  POST /ruleset          raw_text, crime_type -> the case-tuned ruleset (preview, no scoring)
  GET  /audit/{session}  replay a stored run (?verify=true re-hashes and re-scores)
  GET  /health           rules version + hash + extractor mode
"""
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

# Load .env (watsonx credentials, TRIAGE_* settings) before anything reads os.environ.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # python-dotenv optional; real env vars still work without it
    pass

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from pydantic import ValidationError

from . import __version__
from .audit import DEFAULT_DB_PATH, get_run, init_db, log_run
from . import llm_client
from .extraction import ExtractionUnavailable, extract_items, extract_items_with_raw
from .llm_client import describe_client, get_default_client
from .models import ExtractedItem, ExtractRequest, ScoreRequest, TriageRequest, TriageResponse
from .rules import RulesConfig, get_rules
from .ruleset_generator import generate_case_ruleset
from .scoring import score_and_rank, score_item

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(DEFAULT_DB_PATH)
    get_rules()  # load + hash once at startup
    yield


app = FastAPI(
    title="Crime Scene Evidence Triage API",
    version=__version__,
    description="Bob extracts & classifies; deterministic Python scores & ranks.",
    lifespan=lifespan,
)

# CORS: restricted to localhost origins. The served console is same-origin so it
# needs no CORS; this only allows a console opened from another local port. Add your
# host here before any non-local deployment — do not widen back to "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    rules = get_rules()
    body = {
        "status": "ok",
        "version": __version__,
        "rules_version": rules.version,
        "rules_version_hash": rules.version_hash,
        "extractor": describe_client(get_default_client()),
        "dynamic_rules": "available",
    }
    if llm_client.watsonx_fallback_reason:
        # Credentials are set but watsonx could not be initialised — say so loudly.
        body["status"] = "degraded"
        body["extractor_fallback_reason"] = llm_client.watsonx_fallback_reason
    return body


def _extraction_error(exc: ExtractionUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


@app.post("/extract")
def extract(req: ExtractRequest) -> dict:
    try:
        items = extract_items(req.raw_text)
    except ExtractionUnavailable as exc:
        raise _extraction_error(exc) from exc
    return {"crime_type": req.crime_type, "items": [i.model_dump() for i in items]}


@app.post("/score")
def score(req: ScoreRequest) -> dict:
    rules = get_rules()
    ranked = score_and_rank(req.items, req.crime_type, rules)
    return {
        "crime_type": req.crime_type,
        "rules_version": rules.version,
        "rules_version_hash": rules.version_hash,
        "schedule": [s.model_dump() for s in ranked],
    }


def _stored_ruleset(version: str, parameters: dict, raw_proposal: str, source: str) -> str:
    return json.dumps(
        {"version": version, "parameters": parameters, "raw_proposal": raw_proposal, "source": source},
        sort_keys=True,
    )


@app.post("/triage", response_model=TriageResponse)
def triage(req: TriageRequest) -> TriageResponse:
    rules = get_rules()
    session_id = str(uuid.uuid4())  # always fresh, so a run's audit rows never mix

    try:
        items, raw_output = extract_items_with_raw(req.raw_text)
    except ExtractionUnavailable as exc:
        raise _extraction_error(exc) from exc

    case_info, ruleset_json = None, None
    if req.dynamic_rules:
        # Model proposes -> validator clamps -> frozen + hashed -> deterministic scoring.
        rules, case_info, raw_proposal = generate_case_ruleset(items, req.crime_type, get_rules())
        ruleset_json = _stored_ruleset(rules.version, case_info.parameters, raw_proposal, case_info.source)

    ranked = score_and_rank(items, req.crime_type, rules)
    log_run(session_id, ranked, req.crime_type, DEFAULT_DB_PATH,
            raw_model_output=raw_output, ruleset_json=ruleset_json)

    return TriageResponse(
        session_id=session_id,
        crime_type=req.crime_type,
        rules_version=rules.version,
        rules_version_hash=rules.version_hash,
        generated_at=datetime.now(timezone.utc).isoformat(),
        extractor=describe_client(get_default_client()),
        ruleset_mode="dynamic" if case_info else "static",
        case_ruleset=case_info,
        schedule=ranked,
    )


@app.post("/ruleset")
def ruleset_preview(req: TriageRequest) -> dict:
    """Show the case-tuned ruleset a scene would get, without scoring or logging."""
    try:
        items = extract_items(req.raw_text)
    except ExtractionUnavailable as exc:
        raise _extraction_error(exc) from exc
    _, info, _ = generate_case_ruleset(items, req.crime_type, get_rules())
    return {
        "crime_type": req.crime_type,
        "base_rules_version": get_rules().version,
        "items": [i.model_dump() for i in items],
        "case_ruleset": info.model_dump(),
    }


@app.get("/audit/{session_id}")
def audit(session_id: str, verify: bool = False) -> dict:
    rows = get_run(session_id, DEFAULT_DB_PATH)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No audit records for session {session_id!r}")

    result: dict = {"session_id": session_id, "records": rows}

    if verify:
        # Re-score every STORED extraction against the ruleset it was scored with and
        # confirm the stored scores reproduce exactly — a real replay, not a record.
        #  * static runs  -> the current rules_v1.yaml (hash must still match)
        #  * dynamic runs -> the frozen case ruleset stored with the run, which must
        #                    re-hash to the recorded hash (detects tampering)
        current = get_rules()
        ruleset_matches, integrity_ok, dynamic = True, True, False
        mismatches = []
        for r in rows:
            stored_rs = r.get("ruleset_json")
            if isinstance(stored_rs, dict) and isinstance(stored_rs.get("parameters"), dict):
                dynamic = True
                try:
                    rules = RulesConfig.from_mapping(stored_rs["parameters"], version=stored_rs.get("version", "case"))
                except (ValidationError, TypeError):
                    integrity_ok = False
                    continue
                if rules.version_hash != r["rules_version_hash"]:
                    integrity_ok = False
            else:
                rules = current
                if r["rules_version_hash"] != current.version_hash:
                    ruleset_matches = False
            stored_item = r.get("extracted_item")
            if not isinstance(stored_item, dict):
                continue
            try:
                item = ExtractedItem.model_validate(stored_item)
            except ValidationError:
                continue
            re = score_item(item, r.get("crime_type", "unknown"), rules)
            if re.final_score != r["final_score"] or re.urgency_flag != r["urgency_flag"]:
                mismatches.append({
                    "item_name": r["item_name"],
                    "stored_score": r["final_score"],
                    "recomputed_score": re.final_score,
                    "stored_urgent": r["urgency_flag"],
                    "recomputed_urgent": re.urgency_flag,
                })
        result["verification"] = {
            "ruleset_mode": "dynamic" if dynamic else "static",
            "ruleset_matches_current": ruleset_matches,
            "ruleset_integrity_ok": integrity_ok,
            "all_reproduced": integrity_ok and len(mismatches) == 0,
            "mismatches": mismatches,
            "note": (
                "Dynamic runs are re-scored with the frozen case ruleset stored in the "
                "audit log, which must re-hash to the recorded hash. Static runs are "
                "re-scored with the CURRENT rules_v1.yaml; if ruleset_matches_current is "
                "false, differences are explained by a ruleset change (compare hashes)."
            ),
        }

    return result


@app.get("/", response_model=None)
def index() -> JSONResponse | FileResponse:
    page = _WEB_DIR / "index.html"
    if page.exists():
        return FileResponse(str(page))
    return JSONResponse({"service": "evidence-triage", "docs": "/docs"})
