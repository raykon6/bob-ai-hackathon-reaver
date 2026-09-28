"""Deterministic scoring + ranking engine.

PURE functions only: no LLM calls, no network, no clock, no randomness. The same
(item, crime_type, rules) always yields byte-identical output. All arithmetic runs
through decimal.Decimal with ROUND_HALF_UP so results never drift across platforms.

Formula (implemented exactly as specified — do not reorder):
    base       = category_base_weights[category]
    multiplier = crime_type_multipliers.get(crime_type, {}).get(category, 1.0)
    degradation= degradation_risk_by_condition[normalize(condition)]
    flag_bonus = sum(context_flag_modifiers.get(f, 0) for f in context_flags)
    raw_score  = (base * multiplier) + degradation + flag_bonus
    final_score= round(min(raw_score, 100), 2)  # clamped to [0, 100]

Urgency = (final_score >= score_urgent) OR (any flag in force_urgent_flags),
computed independently of the score.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .models import ExtractedItem, ScoreBreakdown, ScoredItem
from .rules import RulesConfig

_CENTS = Decimal("0.01")
_HUNDRED = Decimal("100")
_ZERO = Decimal("0")


def _dec(value) -> Decimal:
    """Convert via str() so we never inherit binary-float imprecision."""
    return Decimal(str(value))


def _round2(value: Decimal) -> float:
    return float(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


def score_item(item: ExtractedItem, crime_type: str, rules: RulesConfig) -> ScoredItem:
    stamp = {"rules_version": rules.version, "rules_version_hash": rules.version_hash}

    # Manual-review items are never scored — pass through, do not guess.
    if item.needs_manual_review or item.category is None:
        return ScoredItem(
            item=item,
            final_score=None,
            breakdown=None,
            urgency_flag=False,
            needs_manual_review=True,
            rationale="Excluded from automated scoring — flagged for manual review.",
            **stamp,
        )

    category = item.category.value

    base = _dec(rules.category_base_weights.get(category, rules.category_base_weights.get("other", 0)))
    multiplier = _dec(rules.crime_type_multipliers.get(crime_type, {}).get(category, 1.0))
    condition_key = rules.normalize_condition(item.condition)
    degradation = _dec(
        rules.degradation_risk_by_condition.get(
            condition_key,
            rules.degradation_risk_by_condition.get(rules.default_condition, 0),
        )
    )
    # De-dupe defensively: a repeated flag must never multiply its bonus, even if
    # validation were bypassed. Each distinct flag contributes at most once.
    unique_flags = list(dict.fromkeys(item.context_flags))
    flag_bonus = sum(
        (_dec(rules.context_flag_modifiers.get(flag, 0)) for flag in unique_flags),
        _ZERO,
    )

    raw_score = (base * multiplier) + degradation + flag_bonus
    clamped = min(raw_score, _HUNDRED)
    if clamped < _ZERO:
        clamped = _ZERO
    final_score = _round2(clamped)

    forced = any(flag in rules.force_urgent_flags for flag in unique_flags)
    urgency = (final_score >= rules.score_urgent) or forced

    breakdown = ScoreBreakdown(
        base=_round2(base),
        multiplier=_round2(multiplier),
        degradation=_round2(degradation),
        flag_bonus=_round2(flag_bonus),
        raw_score=_round2(raw_score),
    )

    rationale = _build_rationale(
        category, crime_type, breakdown, condition_key, final_score, urgency, forced, item, rules
    )

    return ScoredItem(
        item=item,
        final_score=final_score,
        breakdown=breakdown,
        urgency_flag=urgency,
        needs_manual_review=False,
        rationale=rationale,
        **stamp,
    )


def _build_rationale(
    category, crime_type, bd: ScoreBreakdown, condition_key, final_score,
    urgency, forced, item: ExtractedItem, rules: RulesConfig,
) -> str:
    reason = ""
    if urgency and forced:
        forced_flags = [f for f in item.context_flags if f in rules.force_urgent_flags]
        reason = f" Forced urgent by flag(s): {', '.join(forced_flags)}."
    elif urgency:
        reason = f" Score >= {rules.score_urgent} urgency threshold."
    return (
        f"{category} in a {crime_type} case: {bd.base:g} base x {bd.multiplier:g} multiplier "
        f"+ {bd.degradation:g} ({condition_key}) + {bd.flag_bonus:g} context flags "
        f"= {final_score:g}.{reason}"
    )


def score_and_rank(items: list[ExtractedItem], crime_type: str, rules: RulesConfig) -> list[ScoredItem]:
    scored = [score_item(item, crime_type, rules) for item in items]
    return rank_items(scored)


def rank_items(scored: list[ScoredItem]) -> list[ScoredItem]:
    """Stable Timsort with an EXPLICIT key. Never rely on insertion order.

    Priority: urgency (True first), then final_score descending, then item_id
    ascending as a deterministic tie-break. Manual-review items (score None) sort
    last (non-urgent, treated as score -1).
    """
    def sort_key(s: ScoredItem):
        score = s.final_score if s.final_score is not None else -1.0
        return (0 if s.urgency_flag else 1, -score, s.item.item_id)

    ordered = sorted(scored, key=sort_key)
    for rank, s in enumerate(ordered, start=1):
        s.rank = rank
    return ordered
