# Testing Walkthrough — exercise every feature

Assumes you have run the setup once (`cd src`, venv active, `pip install -r requirements.txt`).

## 0. Start the server

```powershell
cd path\to\crime-scene-evidence-triage\src
.\.venv\Scripts\Activate.ps1
$env:TRIAGE_OFFLINE = "1"       # deterministic offline extractor (no credentials)
python run.py
```

Open **http://127.0.0.1:8000**.

---

## A. Web console (the UI)

### A1. "Attach" / enter evidence
There is no file upload — evidence is entered as **text, one item per line** (that is
how an officer would dictate or type a seizure list). Two ways:
- Click **Load case** to auto-fill the Hyderabad reference items, or
- Type your own into the **Recovered items** box, e.g.:

```
Bloodstained kitchen knife beside the body
Cigarette butt near the compound gate
Locked smartphone, screen cracked, powered on
Empty liquor bottle with fingerprints
CCTV DVR unit from the front gate
```

### A2. Pick the crime type
Use the **Crime type** dropdown (Homicide, Arson, Narcotics, Cyber, …). This changes
the multipliers, so the **same items re-rank** for a different crime. Good thing to
show in the demo.

### A3. Run triage
Click **Run triage**. You should see:
- **Summary tiles**: items triaged, urgent count, manual-review count, ruleset hash.
- **Ranked table**: rank, item + category chip, URGENT/ROUTINE pill, one-line
  rationale, score + meter.

### A4. Expand a breakdown
Click **Breakdown** on any row. Confirm you see the full arithmetic
(`base × multiplier + degradation + flag_bonus = final`), the extracted attributes
(location, condition, confidence, context flags), and the ruleset hash.

### A5. Copy the schedule
Click **Copy schedule** → paste into Notepad/Excel. It copies a tab-separated table.

### A6. Theme
Click **Theme** to toggle light/dark; reload to confirm it persists.

### A7. Live-API vs offline badge
With the server running, the table caption badge reads **live API** (results came from
`/triage`). Open the standalone `src/web/index.html` file directly (no server) and it
reads **offline mirror** — same engine, in-browser.

### Edge cases worth trying
- A nonsense line like `xyzzy blob` → classified `other`, low score, ROUTINE.
- Change crime type to **Arson** with `Diesel-soaked rag near the door` → the
  toxicological/trace items jump up.
- Empty box + Run triage → shows the "No items yet" empty state.

---

## B. API endpoints

Easiest: open the built-in Swagger UI at **http://127.0.0.1:8000/docs** and click
**Try it out** on each endpoint. Or use curl (`curl.exe` on Windows PowerShell):

### B1. Health — rules version, hash, active extractor
```powershell
curl.exe http://127.0.0.1:8000/health
```

### B2. Extract only (Bob step — classifies, no scores)
```powershell
curl.exe -X POST http://127.0.0.1:8000/extract -H "Content-Type: application/json" -d "{\"raw_text\":\"Cigarette butt near the gate\nLocked phone still on\",\"crime_type\":\"homicide\"}"
```
Confirm each item has a `category` and `context_flags` but **no score**.

### B3. Score only (deterministic step — takes items, returns ranked)
Feed it already-structured items:
```powershell
curl.exe -X POST http://127.0.0.1:8000/score -H "Content-Type: application/json" -d "{\"crime_type\":\"homicide\",\"items\":[{\"item_id\":0,\"item_name\":\"knife\",\"category\":\"biological\",\"condition\":\"degraded\",\"context_flags\":[\"biological_material\"],\"confidence\":0.9}]}"
```

### B4. Full pipeline + audit id
```powershell
curl.exe -X POST http://127.0.0.1:8000/triage -H "Content-Type: application/json" -d "{\"raw_text\":\"Bloodstained knife by the body\nCCTV DVR from the gate\",\"crime_type\":\"homicide\"}"
```
Note the `session_id` in the response.

### B5. Replay from the audit log (no model call)
```powershell
curl.exe http://127.0.0.1:8000/audit/PASTE_SESSION_ID_HERE
```
Each record stores the **verbatim model output** (`raw_model_output`), the crime
type, and the rank. Add `?verify=true` to re-score the stored extractions and prove
the run reproduces exactly:
```powershell
curl.exe "http://127.0.0.1:8000/audit/PASTE_SESSION_ID_HERE?verify=true"
```
Look for `"all_reproduced": true` and `"ruleset_matches_current": true`.

---

## C. Prove determinism

### C1. Same input → same output
Run B4 twice with the same body. The `schedule`, scores, and `rules_version_hash`
are identical every time.

### C2. The test suite (stop the server first, or use a second terminal)
```powershell
cd path\to\crime-scene-evidence-triage\src
.\.venv\Scripts\Activate.ps1
pytest -q
```
Expect **45 passed**, including:
- `test_scoring.py` — exact-match scores (zero tolerance)
- `test_determinism.py` — scorer run 1000× is identical
- `test_extraction_retry.py` — malformed/hallucinated LLM output is retried, then
  routed to manual review; never reaches the scorer
- `test_ranking.py` — urgency-first, stable item_id tie-break
- `test_api.py` — every endpoint, audit replay, blank-input 422, model-outage 503
- `test_offline_extractor.py` — keyword regressions (tablets, cellphones, weapons…)
- `test_web_mirror.py` — the console's offline mirror matches `rules_v1.yaml`

Verbose view of what each test checks:
```powershell
pytest -v
```

---

## D. IBM Bob via MCP (optional — the load-bearing integration)

```powershell
pip install -r requirements-optional.txt
python -m app.mcp_server        # runs the stdio MCP server
```
Register with Bob (see bob.ibm.com/docs/ide → MCP), then in Bob chat ask it to triage
a scene. Bob calls `extract_evidence` (language) then `score_evidence` (deterministic).

## E. Real watsonx extraction (optional)

```powershell
copy .env.example .env          # then edit .env with your WATSONX_* keys
$env:TRIAGE_OFFLINE = "0"
python run.py
```
`/health` should now report `"extractor":"watsonx"`, and the console breakdown will say
"Extracted attributes (from Bob)".

---

## Quick pass/fail checklist

- [ ] `/health` returns a 64-char `rules_version_hash`
- [ ] Console ranks the reference case; cigarette butt is URGENT
- [ ] Breakdown shows the arithmetic and the hash
- [ ] Changing crime type re-ranks the same items
- [ ] Two identical `/triage` calls return identical scores
- [ ] `/audit/{session_id}` replays a past run
- [ ] `pytest -q` → 45 passed
