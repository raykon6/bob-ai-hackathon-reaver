# Solution Overview

## Core mechanism

```
free text ─▶ [ Bob / watsonx Granite ] ─▶ structured items ─▶ [ deterministic Python ] ─▶ ranked FSL schedule
              EXTRACT & CLASSIFY only                          SCORE · FLAG URGENCY · RANK
              (language)                                       (fixed, versioned rules — no LLM)
```

The single design decision everything else follows from: **the model does the
language work and nothing else.** It converts an officer's item list into
structured, classified records. It does **not** assign scores, does **not** rank,
and does **not** decide urgency. Those are computed by pure Python from a versioned
rules file, so the same input always yields the same schedule.

## What makes it different from a naive AI tool

| Naive "AI prioritizer" | This system |
|---|---|
| LLM outputs a priority number | LLM outputs only category + attributes; a ruleset computes the number |
| Non-reproducible (temp, phrasing) | Byte-identical output for identical input (proven by test) |
| Unexplainable score | Full additive breakdown + ruleset hash on every item |
| Hallucinated category silently used | Hallucinations rejected by strict validation, routed to manual review |
| No audit trail | Every run written to SQLite; replayable without the model |

## The four stages

### 1. Extraction (Bob / watsonx Granite) — `app/extraction.py`
- Prompted at **temperature 0** to return **only a JSON array**.
- Each object is validated against a **strict** Pydantic schema
  (`RawExtractedItem`): closed 8-category enum, closed context-flag vocabulary,
  no extra keys, no scalar coercion.
- On validation failure: **retry up to 2 times**, feeding the exact error back to
  the model. After that, valid items pass through and the rest become
  `needs_manual_review` stubs with nulled fields — **we never guess a category.**

### 2. Scoring (deterministic) — `app/scoring.py`
For a valid item:
```
base       = category_base_weights[category]
multiplier = crime_type_multipliers[crime_type][category]   (default 1.0)
degradation= degradation_risk_by_condition[normalize(condition)]
flag_bonus = sum(context_flag_modifiers[f] for f in context_flags)
raw        = base * multiplier + degradation + flag_bonus
final      = round(min(raw, 100), 2)      # Decimal, ROUND_HALF_UP
```
All arithmetic runs through `decimal.Decimal` so results never drift across
platforms. No clock, no randomness, no I/O.

### 3. Urgency (independent boolean) — `app/scoring.py`
```
urgent = (final >= 30) OR (any context_flag in force_urgent_flags)
```
Computed **separately from the score** so a low-scoring but perishable item
(e.g. weather-exposed biological trace) is still flagged and never buried.

### 4. Ranking — `app/scoring.py`
Stable `sorted()` (Timsort) with an **explicit** key:
`(urgency first, then final_score desc, then item_id asc)`. Ties never fall back to
insertion order.

## Key design decisions and why

- **Rules in a versioned YAML, hashed with SHA-256.** The hash is stamped on every
  result, so a schedule from six months ago can be traced to the exact weights that
  produced it. Change a weight → change the file → change the hash. This is the
  reproducibility a court needs.
- **`condition` is free text, normalized deterministically.** The model may say
  "wet", "partially exposed", "charred"; a normalization table maps each onto one
  of three canonical degradation levels. (See the assumptions note in the README.)
- **Offline extractor as a first-class fallback.** With no watsonx credentials the
  pipeline still runs end-to-end using a deterministic keyword classifier — so CI,
  tests, and demos never depend on a network or a key. It is clearly not the
  production classifier.

## What the user experience looks like

1. Officer selects the crime type and pastes/lists the recovered items.
2. Clicks **Run triage**. The console calls `/triage`.
3. Back comes a ranked table: rank, item, category, **Urgent/Routine** status, a
   one-line deterministic rationale, and the numeric score.
4. Expanding any row shows the **full additive breakdown** and the ruleset hash —
   the officer (or a court) can see exactly why item #3 outranks item #7.
5. The schedule can be copied for the FSL submission form; the run is logged for
   later replay.
