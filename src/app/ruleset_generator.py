"""Case-specific (dynamic) ruleset generation.

The LLM PROPOSES scoring parameters tuned to one case; this module DISPOSES:

  1. every proposed number is clamped to a hard bound (BOUNDS),
  2. structural invariants are enforced — all eight categories present, the
     degradation scale stays non-decreasing, and the force-urgent safety floor
     from the base ruleset can be extended but never removed,
  3. the result is frozen into a RulesConfig hashed over its canonical JSON.

Scoring then runs deterministically against that frozen ruleset, so a case's
schedule is exactly reproducible from the stored ruleset (GET /audit?verify
re-hashes it and re-scores). The model sets policy for the case; it still never
sees or produces a score for any item.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from typing import Optional

from . import llm_client
from .models import ALLOWED_CONTEXT_FLAGS, CaseRulesetInfo, Category, ExtractedItem
from .rules import RulesConfig

# Hard limits on anything the model proposes.
BOUNDS: dict[str, tuple[float, float]] = {
    "base_weight": (1.0, 12.0),
    "multiplier": (0.5, 2.5),
    "degradation": (0.0, 15.0),
    "flag_modifier": (0.0, 10.0),
    "score_urgent": (10.0, 60.0),
}

# The angles a case ruleset must reason about, and which parameters each drives.
EVALUATION_ANGLES: dict[str, str] = {
    "probative_value": "how strongly the category can link suspect, victim and scene (base weights)",
    "individualization": "whether the evidence can identify one person or source (base weights)",
    "legal_relevance": "how central the category is to proving this offence (crime multipliers)",
    "fragility": "how fast the material degrades if not examined (degradation scale)",
    "time_sensitivity": "what is lost with every hour of delay (degradation scale, urgency)",
    "contamination_risk": "exposure, handling and transfer risk (context-flag modifiers)",
    "chain_of_custody": "integrity of seizure and packaging (context-flag modifiers)",
    "corroboration": "whether several items reinforce the same line of inquiry (base weights)",
}

DEGRADATION_LEVELS = ("intact", "partially_exposed", "degraded")
_MAX_ATTEMPTS = 2


# --------------------------------------------------------------------------- #
#  Prompt
# --------------------------------------------------------------------------- #
def build_ruleset_prompt(base: RulesConfig, crime_type: str) -> str:
    cats = ", ".join(c.value for c in Category)
    flags = ", ".join(ALLOWED_CONTEXT_FLAGS)
    angles = "\n".join(f"  - {k}: {v}" for k, v in EVALUATION_ANGLES.items())
    baseline = {
        "category_base_weights": base.category_base_weights,
        "crime_multipliers": base.crime_type_multipliers.get(crime_type, {}),
        "degradation_risk_by_condition": base.degradation_risk_by_condition,
        "context_flag_modifiers": base.context_flag_modifiers,
        "score_urgent": base.score_urgent,
        "force_urgent_flags": base.force_urgent_flags,
    }
    lo = BOUNDS
    return (
        "You are a forensic evidence-policy assistant for a Forensic Science Laboratory. "
        f"The crime type is '{crime_type}'. You will receive the items recovered at THIS "
        "scene. Propose scoring PARAMETERS tuned to this case. You are setting policy, "
        "not scoring items: never output a score, rank or urgency for any item.\n"
        f"Reason through every evaluation angle:\n{angles}\n"
        "Output ONLY one JSON object — no prose, no markdown, no code fences — with keys:\n"
        f'  "category_base_weights": {{category: number {lo["base_weight"][0]}-{lo["base_weight"][1]}}} for all of [{cats}]\n'
        f'  "crime_multipliers": {{category: number {lo["multiplier"][0]}-{lo["multiplier"][1]}}}\n'
        f'  "degradation_risk_by_condition": {{"intact","partially_exposed","degraded": number '
        f'{lo["degradation"][0]}-{lo["degradation"][1]}, non-decreasing in that order}}\n'
        f'  "context_flag_modifiers": {{flag: number {lo["flag_modifier"][0]}-{lo["flag_modifier"][1]}}} for [{flags}]\n'
        f'  "score_urgent": number {lo["score_urgent"][0]}-{lo["score_urgent"][1]}\n'
        f'  "force_urgent_flags": subset of [{flags}]\n'
        '  "evaluation_angles": {angle: one-sentence note on how this case affects it}\n'
        '  "rationale": one or two sentences\n'
        "Start from this baseline and change only what the case justifies:\n"
        f"{json.dumps(baseline, sort_keys=True)}"
    )


def _case_payload(items: list[ExtractedItem], crime_type: str) -> str:
    return json.dumps({
        "crime_type": crime_type,
        "items": [
            {
                "item_name": i.item_name,
                "category": i.category.value if i.category else None,
                "condition": i.condition,
                "location_found": i.location_found,
                "context_flags": i.context_flags,
            }
            for i in items if not i.needs_manual_review
        ],
    }, sort_keys=True)


def _json_object(text: str) -> dict:
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model output")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("top-level JSON value must be an object")
    return data


# --------------------------------------------------------------------------- #
#  Deterministic heuristic (offline / fallback)
# --------------------------------------------------------------------------- #
def heuristic_proposal(items: list[ExtractedItem], crime_type: str, base: RulesConfig) -> dict:
    """Case-tuning with no model: a pure function of the extracted items, so the
    offline path is reproducible too."""
    scored = [i for i in items if i.category and not i.needs_manual_review]
    cats = Counter(i.category.value for i in scored)
    flags = Counter(f for i in scored for f in i.context_flags)
    conds = Counter(base.normalize_condition(i.condition) for i in scored)
    n = max(len(scored), 1)

    weights = dict(base.category_base_weights)
    for cat, count in cats.items():
        # probative value in THIS scene, plus corroboration when several items agree
        weights[cat] = weights[cat] + 1.0 + (0.5 if count >= 2 else 0.0)

    mults = dict(base.crime_type_multipliers.get(crime_type, {}))
    for cat in cats:
        mults.setdefault(cat, 1.1)  # present categories are relevant to this offence

    degr = dict(base.degradation_risk_by_condition)
    perishable = conds.get("degraded", 0) / n
    if perishable >= 0.25:  # a scene dominated by fragile material raises time pressure
        degr["degraded"] = degr["degraded"] + 2
        degr["partially_exposed"] = degr["partially_exposed"] + 1

    mods = dict(base.context_flag_modifiers)
    if flags.get("chain_of_custody_break"):
        mods["chain_of_custody_break"] = mods["chain_of_custody_break"] + 2
    if flags.get("signs_of_tampering"):
        mods["signs_of_tampering"] = mods["signs_of_tampering"] + 1
    if flags.get("exposed_to_weather", 0) >= 2:
        mods["exposed_to_weather"] = mods["exposed_to_weather"] + 1

    top = ", ".join(c for c, _ in cats.most_common(3)) or "none"
    angles = {
        "probative_value": f"Categories present at this scene ({top}) gain weight.",
        "individualization": "Biological and pattern evidence keep their individualizing lead.",
        "legal_relevance": f"Every category present is treated as relevant to {crime_type}.",
        "fragility": f"{perishable:.0%} of items are degraded"
                     + ("; the degradation scale is raised." if perishable >= 0.25 else "."),
        "time_sensitivity": "Force-urgent safety flags are kept from the base ruleset.",
        "contamination_risk": "Weather-exposure bonus rises when several items are exposed.",
        "chain_of_custody": "Custody breaks and tampering carry extra weight when present.",
        "corroboration": "Categories with two or more items receive a corroboration bonus.",
    }
    return {
        "category_base_weights": weights,
        "crime_multipliers": mults,
        "degradation_risk_by_condition": degr,
        "context_flag_modifiers": mods,
        "score_urgent": base.score_urgent,
        "force_urgent_flags": list(base.force_urgent_flags),
        "evaluation_angles": angles,
        "rationale": "Deterministic case tuning from the extracted items (no model call).",
    }


# --------------------------------------------------------------------------- #
#  Validation + clamping
# --------------------------------------------------------------------------- #
def _num(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return float(value)


def _clamp(value, bound: str, fallback: float, label: str, notes: list[str]) -> float:
    lo, hi = BOUNDS[bound]
    v = _num(value)
    if v is None:
        if value is not None:
            notes.append(f"{label}: non-numeric proposal {value!r} replaced by baseline {fallback:g}")
        v = fallback
    if v < lo or v > hi:
        clamped = min(max(v, lo), hi)
        notes.append(f"{label}: {v:g} clamped to {clamped:g}")
        v = clamped
    return round(v, 2)


def validate_and_clamp(proposal: dict, base: RulesConfig, crime_type: str) -> tuple[dict, list[str]]:
    """Turn an untrusted proposal into a complete, bounded parameter mapping."""
    notes: list[str] = []
    valid_cats = {c.value for c in Category}

    prop_w = proposal.get("category_base_weights") or {}
    prop_w = prop_w if isinstance(prop_w, dict) else {}
    for key in sorted(set(prop_w) - valid_cats):
        notes.append(f"ignored unknown category {key!r}")
    weights = {
        c: _clamp(prop_w.get(c), "base_weight", base.category_base_weights[c], f"base_weight[{c}]", notes)
        for c in sorted(valid_cats)
    }

    prop_m = proposal.get("crime_multipliers") or {}
    prop_m = prop_m if isinstance(prop_m, dict) else {}
    base_m = base.crime_type_multipliers.get(crime_type, {})
    case_m = {}
    for c in sorted(valid_cats):
        if c in prop_m or c in base_m:
            case_m[c] = _clamp(prop_m.get(c), "multiplier", base_m.get(c, 1.0), f"multiplier[{c}]", notes)
    for key in sorted(set(prop_m) - valid_cats):
        notes.append(f"ignored multiplier for unknown category {key!r}")
    multipliers = {k: dict(v) for k, v in base.crime_type_multipliers.items()}
    multipliers[crime_type] = case_m

    prop_d = proposal.get("degradation_risk_by_condition") or {}
    prop_d = prop_d if isinstance(prop_d, dict) else {}
    levels = [
        _clamp(prop_d.get(k), "degradation", base.degradation_risk_by_condition[k], f"degradation[{k}]", notes)
        for k in DEGRADATION_LEVELS
    ]
    if levels != sorted(levels):
        notes.append(f"degradation scale {levels} was not non-decreasing; re-ordered")
        levels = sorted(levels)
    degradation = dict(zip(DEGRADATION_LEVELS, levels))

    prop_f = proposal.get("context_flag_modifiers") or {}
    prop_f = prop_f if isinstance(prop_f, dict) else {}
    for key in sorted(set(prop_f) - set(ALLOWED_CONTEXT_FLAGS)):
        notes.append(f"ignored unknown context flag {key!r}")
    modifiers = {
        f: _clamp(prop_f.get(f), "flag_modifier", base.context_flag_modifiers.get(f, 0.0), f"flag_modifier[{f}]", notes)
        for f in ALLOWED_CONTEXT_FLAGS
    }

    score_urgent = _clamp(proposal.get("score_urgent"), "score_urgent", base.score_urgent, "score_urgent", notes)

    prop_force = proposal.get("force_urgent_flags")
    prop_force = prop_force if isinstance(prop_force, list) else []
    floor = list(base.force_urgent_flags)
    dropped = [f for f in floor if f not in prop_force]
    if prop_force and dropped:
        notes.append(f"safety floor kept: force-urgent flags {dropped} cannot be removed")
    extra = sorted({f for f in prop_force if f in ALLOWED_CONTEXT_FLAGS} - set(floor))
    bad = sorted({str(f) for f in prop_force if f not in ALLOWED_CONTEXT_FLAGS})
    if bad:
        notes.append(f"ignored unknown force-urgent flags {bad}")
    force = floor + extra

    mapping = {
        "category_base_weights": weights,
        "crime_type_multipliers": multipliers,
        "degradation_risk_by_condition": degradation,
        "condition_normalization": dict(base.condition_normalization),
        "default_condition": base.default_condition,
        "context_flag_modifiers": modifiers,
        "score_urgent": score_urgent,
        "force_urgent_flags": force,
    }
    return mapping, notes


def _adjustments(mapping: dict, base: RulesConfig, crime_type: str) -> list[dict]:
    """Human-readable diff of the case ruleset against the base ruleset."""
    out: list[dict] = []

    def add(param: str, before, after):
        if before != after:
            out.append({"parameter": param, "baseline": before, "case": after})

    for c, v in mapping["category_base_weights"].items():
        add(f"base_weight[{c}]", float(base.category_base_weights.get(c, 0)), v)
    base_m = base.crime_type_multipliers.get(crime_type, {})
    for c, v in mapping["crime_type_multipliers"][crime_type].items():
        add(f"multiplier[{crime_type}][{c}]", float(base_m.get(c, 1.0)), v)
    for k, v in mapping["degradation_risk_by_condition"].items():
        add(f"degradation[{k}]", float(base.degradation_risk_by_condition[k]), v)
    for f, v in mapping["context_flag_modifiers"].items():
        add(f"flag_modifier[{f}]", float(base.context_flag_modifiers.get(f, 0)), v)
    add("score_urgent", float(base.score_urgent), mapping["score_urgent"])
    add("force_urgent_flags", list(base.force_urgent_flags), mapping["force_urgent_flags"])
    return out


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #
def generate_case_ruleset(
    items: list[ExtractedItem],
    crime_type: str,
    base: RulesConfig,
    client: llm_client.LLMClient | None = None,
) -> tuple[RulesConfig, CaseRulesetInfo, str]:
    """Return (frozen case ruleset, explanation for the response, verbatim proposal)."""
    client = client or llm_client.get_default_client()
    source, fallback_reason, raw = "heuristic", None, ""
    proposal: dict | None = None

    if not isinstance(client, llm_client.OfflineExtractionClient):
        system = build_ruleset_prompt(base, crime_type)
        payload = _case_payload(items, crime_type)
        error = ""
        for _ in range(_MAX_ATTEMPTS):
            try:
                raw = client.complete(system + error, payload, temperature=0.0)
                proposal = _json_object(raw)
                source = llm_client.describe_client(client)
                break
            except (ValueError, json.JSONDecodeError) as exc:
                error = f"\n\nYOUR PREVIOUS OUTPUT WAS INVALID: {exc}. Return ONLY the JSON object."
                fallback_reason = f"unparseable proposal: {exc}"
            except Exception as exc:  # model unreachable — fall back, but say so
                fallback_reason = f"{type(exc).__name__}: {exc}"
                break

    if proposal is None:
        proposal = heuristic_proposal(items, crime_type, base)
        source = "heuristic"

    mapping, clamps = validate_and_clamp(proposal, base, crime_type)
    ruleset = RulesConfig.from_mapping(mapping, version=f"{base.version}+case")

    angles_in = proposal.get("evaluation_angles")
    angles_in = angles_in if isinstance(angles_in, dict) else {}
    angles = {a: str(angles_in.get(a, "not addressed by the proposal"))[:300] for a in EVALUATION_ANGLES}

    info = CaseRulesetInfo(
        version=ruleset.version,
        version_hash=ruleset.version_hash,
        source=source,
        fallback_reason=fallback_reason if source == "heuristic" else None,
        rationale=str(proposal.get("rationale", ""))[:600],
        evaluation_angles=angles,
        adjustments=_adjustments(mapping, base, crime_type),
        clamps=clamps,
        parameters=mapping,
    )
    return ruleset, info, raw
