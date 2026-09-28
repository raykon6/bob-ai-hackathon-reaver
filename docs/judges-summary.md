# Judge's Summary — Evidence Triage Console

**Team REAVER · Track 1 · Problem Statement 03 — AI-Based Crime Scene Evidence Prioritization**

## In one sentence

An investigator lists crime-scene items in plain language; **IBM Bob (watsonx
Granite) extracts and classifies** them, and a **deterministic Python engine
scores, flags urgency, and ranks** them into a reproducible, court-traceable FSL
examination schedule.

## The idea that makes it different

Most "AI prioritizer" projects let the model output a priority number — which is
non-reproducible and unexplainable, and would not survive cross-examination. We
drew a hard line:

> **The LLM classifies. Deterministic, versioned rules decide priority.**

Bob never assigns a score, never ranks, and never makes the urgent/non-urgent
call. Those are pure functions of `(item, crime_type, ruleset)`, so the same
input always yields the same schedule — stamped with the SHA-256 hash of the
exact ruleset that produced it.

## How it maps to the evaluation criteria

| Criterion | Where to look |
|---|---|
| **Technical implementation (25)** | `src/app/scoring.py` (pure engine, `Decimal`/`ROUND_HALF_UP`), `src/app/extraction.py` (strict Pydantic + 2× retry + manual-review fallback), FastAPI in `src/app/main.py` |
| **Innovation & differentiation (25)** | The extraction/decision split. `rules_v1.yaml` as a single, hashed source of truth; urgency as an independent boolean so perishables are never buried |
| **Problem depth & vision (15)** | `docs/problem-statement.md` — grounded in the Hyderabad case, FSL backlog, and admissibility, not just the spec |
| **Working demo (15)** | Runs with zero credentials via the offline extractor; `python run.py` → console at `127.0.0.1:8000`; `demo/` video + screenshots |
| **IBM Bob integration (10)** | `src/app/mcp_server.py` exposes `extract_evidence` (LLM) + `score_evidence` (deterministic) as MCP tools; the tool boundary enforces the design rule. watsonx Granite client in `src/app/llm_client.py` |
| **Documentation & reproducibility (10)** | `docs/setup-guide.md` (tested from a clean venv), 45-test suite incl. a 1000× determinism check, SQLite audit replay |

## What to try in 60 seconds

```bash
cd src
pip install -r requirements.txt
$env:TRIAGE_OFFLINE = "1"; python run.py      # PowerShell; bash: export TRIAGE_OFFLINE=1
# open http://127.0.0.1:8000 → Run triage → expand any "Breakdown"
pytest -q                                      # 45 passed — proves determinism
```

## Honest limitations

- The offline extractor is a deterministic keyword classifier for demos/CI;
  production classification quality depends on watsonx Granite (wire `.env`).
- Scoring weights in `rules_v1.yaml` are a defensible v1, not yet calibrated
  against real FSL case outcomes.

## What we're most proud of

We can hand a judge a schedule and answer *"why is this item ranked here?"* with
an exact arithmetic breakdown and a ruleset hash — not a shrug. That is the
difference between a demo and a tool a forensic lab could actually trust.
