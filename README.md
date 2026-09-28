# Evidence Triage Console — AI-Assisted Crime Scene Evidence Prioritization

> IBM Bob AI Hackathon · NFSU — **Track 1 · Problem Statement 03**

An investigator lists the items recovered from a crime scene in plain language.
**IBM Bob (watsonx.ai Granite) extracts and classifies** each item into a fixed
evidence taxonomy. A **deterministic Python engine then scores, flags urgency, and
ranks** everything into a Forensic Science Laboratory (FSL) examination schedule —
reproducibly, and stamped with the exact ruleset version used.

---

## The one rule that shapes everything

**Bob classifies. Deterministic code decides priority.**

The language model never assigns a number, never ranks, and never makes the
urgent/non-urgent call. All of that happens in pure Python with no LLM calls, so
the same input and the same ruleset version always produce the *identical*
schedule — a property forensic evidence handling actually requires.

## Team

| | |
|---|---|
| **Team** | REAVER |
| **Track** | Forensic Science (Track 1) |
| **Lead** | Sarthak Singh |
| **Members** | Dular Bewal · Rishi Bhardwaj · Krisha Jogi |

## Problem Statement

Major crime scenes produce hundreds of physical items and thousands of photographs.
In the **2019 Hyderabad homicide**, investigators handled 3,000+ photos and 200+
items; a DNA-bearing cigarette butt was nearly missed on the first sweep, and
overloaded FSLs delayed testing by weeks. There is no tool that turns an
investigator's raw item list into a defensible, examine-this-first schedule.
Full write-up: [`docs/problem-statement.md`](docs/problem-statement.md).

## Solution

A four-stage pipeline:

1. **Extract (Bob / watsonx Granite)** — free text → structured, classified items
   (fixed 8-category taxonomy, fixed context-flag vocabulary). Strict validation;
   hallucinated categories/flags are rejected, not coerced; unresolved items are
   routed to manual review, never guessed.
2. **Score (deterministic Python)** — `base × crime-multiplier + degradation +
   flag_bonus`, clamped to 0–100 with `Decimal`/`ROUND_HALF_UP`.
3. **Flag urgency (independent boolean)** — `score ≥ 30` **OR** any force-urgent
   flag (electronic device, weather-exposed, biological). Computed separately from
   the score so perishable low-scorers still surface. (The additive score tops out
   near 44, so the threshold sits inside the real range, not above it.)
4. **Rank & schedule** — stable sort: urgency, then score desc, then item_id.

How it works, in depth: [`docs/solution-overview.md`](docs/solution-overview.md)
and [`docs/architecture.md`](docs/architecture.md).

## Key Features

- **Bob is load-bearing, not name-dropped** — it does the language work; an MCP
  server lets it drive the pipeline conversationally.
- **Reproducible by construction** — pure scoring functions, no clock, no
  randomness; a 1000× regression test proves it.
- **Court-traceable** — every result carries the SHA-256 hash of `rules_v1.yaml`.
- **Auditable** — SQLite log replays any past run without calling the model again.
- **Honest failure mode** — unvalidated extractions become `needs_manual_review`
  with nulled fields; they never reach the scorer.
- **Case-tuned rulesets (opt-in)** — Bob can propose weights, crime multipliers,
  degradation baselines and flag modifiers tuned to *this* scene, reasoning across
  eight evaluation angles. The engine clamps the proposal, keeps the safety floor,
  then freezes and hashes it — so the schedule is still exactly reproducible.
- **IBM Bob Shell routing** — set `BOB_SHELL_CMD` and every LLM call (extraction
  and ruleset proposals) goes through Bob Shell.

## Case-tuned rulesets

A single fixed ruleset can't weigh every scene well — a poisoning, a burglary and
a scene soaked by rain stress different evidence. With `dynamic_rules=true`:

1. **Propose** — the model reads the extracted items and proposes scoring
   *parameters* for this case, covering probative value, individualization, legal
   relevance, fragility, time sensitivity, contamination risk, chain of custody and
   corroboration. It still never scores or ranks an item.
2. **Clamp** — every number is forced into hard bounds (e.g. base weight 1–12,
   multiplier 0.5–2.5), unknown categories/flags are dropped, the degradation scale
   stays non-decreasing, and force-urgent safety flags can be added but never removed.
3. **Freeze + hash** — the result becomes a ruleset `1.1.1+case` with hash
   `case-<sha256>` over its canonical JSON.
4. **Score** — the same pure engine scores against the frozen ruleset.
5. **Replay** — the frozen ruleset is stored with the run; `GET /audit/{id}?verify=true`
   re-hashes it (tamper detection) and re-scores every item.

Try it: tick **Case-tuned ruleset** in the console, `POST /ruleset` to preview one,
or ask Bob to call `triage_scene` with `dynamic_rules: true`. With no model
configured, a deterministic case heuristic proposes the parameters instead.

## Tech Stack

Python 3.11+ · FastAPI · Pydantic v2 (strict) · IBM watsonx.ai (Granite) ·
Model Context Protocol · SQLite · pytest · single-page HTML/JS
(Inter / Newsreader / IBM Plex Mono).

## How to Run

Exact, copy-pasteable steps are in [`docs/setup-guide.md`](docs/setup-guide.md).
The short version (runs with **no credentials** via the offline extractor):

```bash
cd src
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export TRIAGE_OFFLINE=1        # Windows PowerShell: $env:TRIAGE_OFFLINE=1
python run.py                  # open http://127.0.0.1:8000
```

Run the tests:

```bash
cd src && pytest -q
```

## Demo

- Video: [`demo/demo-video.mp4`](demo/demo-video.mp4) (1 min 28 s, narrated) — link also in
  [`demo/demo-video-link.txt`](demo/demo-video-link.txt)
- Pitch deck: [`presentation/Evidence_Triage_Pitch.pdf`](presentation/Evidence_Triage_Pitch.pdf)
- Live demo: [`demo/live-demo-url.txt`](demo/live-demo-url.txt) — the single-page
  console also runs fully in-browser (offline mirror of the same engine) and can
  be shared as a hosted link.
- Screenshots: [`demo/screenshots/`](demo/screenshots/)

## Known Limitations

- The **offline extractor** is a deterministic keyword classifier for demos, CI,
  and no-credential runs. Production classification quality depends on watsonx
  Granite; wire real credentials in `.env` to use it.
- Scoring weights in `rules_v1.yaml` are a defensible **v1 starting point** built
  with forensic-priority reasoning, not yet calibrated against FSL case outcomes.
- Extraction of `location_found` uses a light heuristic in the offline path.

## What We're Most Proud Of

The **extraction/decision split**. It is the difference between "an LLM guessed a
priority" and "a versioned, auditable ruleset decided the priority and we can
prove it produced this exact schedule." See [`src/app/scoring.py`](src/app/scoring.py)
and the zero-tolerance tests in [`src/tests/`](src/tests/).
