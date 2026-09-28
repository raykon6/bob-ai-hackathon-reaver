# Setup Guide

Written for someone who has never seen this repo. It runs **with zero credentials**
using the deterministic offline extractor; watsonx/Bob are optional upgrades.

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | `python --version` |
| pip | recent | ships with Python |
| Git | any | to clone |
| IBM Cloud + watsonx.ai | optional | only for the real Bob extraction path |
| IBM Bob (bob.ibm.com) | optional | only for the MCP chat integration |

## 2. Get the code

```bash
git clone https://github.com/<your-username>/bob-ai-hackathon-<your-team>.git
cd bob-ai-hackathon-<your-team>/src
```

## 3. Create a virtual environment and install

```bash
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

This installs everything needed to run the app and the tests. The **real
Bob/watsonx path and the MCP server are optional** — install them only if you
want live watsonx classification:

```bash
pip install -r requirements-optional.txt
```

> Works on Python 3.11–3.14. If you are on Python 3.13+ and an older
> `ibm-watsonx-ai` fails to resolve, this file already targets a compatible range.

## 4. Configure environment

```bash
cp .env.example .env       # Windows: copy .env.example .env
```

Every variable and what it does:

| Variable | Required? | Purpose |
|---|---|---|
| `WATSONX_APIKEY` | for watsonx path | IBM Cloud API key |
| `WATSONX_URL` | for watsonx path | e.g. `https://us-south.ml.cloud.ibm.com` |
| `WATSONX_PROJECT_ID` | for watsonx path | watsonx.ai project id |
| `WATSONX_MODEL_ID` | optional | default `ibm/granite-3-8b-instruct` |
| `TRIAGE_OFFLINE` | optional | `1` forces the offline extractor (no network) |
| `TRIAGE_DB_PATH` | optional | SQLite path (default `evidence_audit.db`) |
| `TRIAGE_HOST` / `TRIAGE_PORT` | optional | default `127.0.0.1` / `8000` |

**To run with no credentials at all**, set `TRIAGE_OFFLINE=1` (or just leave the
watsonx variables blank — the app falls back automatically).

```bash
# macOS / Linux
export TRIAGE_OFFLINE=1
# Windows PowerShell
$env:TRIAGE_OFFLINE = "1"
```

## 5. Run the API + console

```bash
python run.py
```

Open **http://127.0.0.1:8000** — the console loads with the reference case. Click
**Run triage**.

## 6. Verify it's working

```bash
# health: shows rules version, SHA-256 hash, and which extractor is active
curl http://127.0.0.1:8000/health

# full pipeline
curl -X POST http://127.0.0.1:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"raw_text":"Cigarette butt near the gate\nBloodstained knife by the body","crime_type":"homicide"}'
```

You should see a JSON `schedule`, each item carrying `final_score`, `urgency_flag`,
a `breakdown`, and `rules_version_hash`.

## 7. Run the tests (proves determinism)

```bash
pytest -q
```

Expect **57 passed**. These pin the scoring formula to exact numbers and run the
scorer 1000× to prove it never drifts.

## 8. (Optional) Register the pipeline with IBM Bob via MCP

From `src/`, with the venv active (install the optional deps first):

```bash
pip install -r requirements-optional.txt
```

```bash
# stdio MCP server
python -m app.mcp_server
```

Bob discovers the server from the committed **`.bob/mcp.json`** at the repo root —
open the repo in Bob and it registers `evidence-triage` (3 tools: `extract_evidence`,
`score_evidence`, `triage_scene`). `.bob/rules.md` tells Bob the core constraint
(classify only; never compute scores — always call `score_evidence`).

The committed config uses `command: "python"` with a relative `cwd` so it is
portable. If Bob starts the wrong interpreter (one without `mcp` installed), point
it at your venv's Python with **absolute paths**:

```json
{
  "mcpServers": {
    "evidence-triage": {
      "command": "C:\\path\\to\\crime-scene-evidence-triage\\src\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp_server"],
      "cwd": "C:\\path\\to\\crime-scene-evidence-triage\\src"
    }
  }
}
```

(Confirm the exact config location against your Bob version's docs at
`bob.ibm.com/docs/ide`; the file uses the standard `mcpServers` schema.)

Then, in Bob chat:

> "Here are the items from a homicide scene: a cigarette butt near the gate, a
> bloodstained knife by the body, a locked phone that's still on. Triage them."

Bob calls `extract_evidence` (language) then `score_evidence` (deterministic) and
returns the ranked schedule. Bob never computes the score itself.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No module named app` | running pytest/uvicorn from repo root | `cd src` first |
| `/health` shows `extractor: offline-deterministic` unexpectedly | watsonx creds missing/blank or `TRIAGE_OFFLINE=1` | fill `.env`, unset `TRIAGE_OFFLINE` |
| `ModuleNotFoundError: ibm_watsonx_ai` | optional dep not installed | `pip install -r requirements-optional.txt` |
| `Could not find a version that satisfies ibm-watsonx-ai` | pinned version too old for your Python (e.g. 3.14) | use `requirements-optional.txt` (ranged), not a hard pin |
| watsonx path raises auth error | bad key/project/url | re-check the three `WATSONX_*` values |
| Console shows "offline mirror" badge | API not reachable from the page | start `python run.py`, open the page from `127.0.0.1:8000` |
| Console shows "Triage failed on the server" | the API is up but returned an error (e.g. 503 when watsonx is unreachable) | read the message shown; check `/health` and your `WATSONX_*` values |
| `/health` shows `"status": "degraded"` | watsonx credentials are set but the client failed to start; the offline extractor is being used | see `extractor_fallback_reason` in the same response |
| `test_web_mirror` fails | `rules_v1.yaml` or the offline keywords changed but the console's embedded copy did not | `python sync_web_mirror.py` from `src/` |
| Port 8000 in use | another process | `TRIAGE_PORT=8010 python run.py` |
| Tests fail after editing weights | you changed `rules_v1.yaml` | update the expected numbers in `tests/test_scoring.py`, bump the rules `version` |
