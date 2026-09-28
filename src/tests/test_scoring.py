"""Exact-match scoring tests — zero tolerance. These pin the formula to specific
numbers so any accidental change to rules_v1.yaml or the engine is caught.
Computed by hand against the weights in rules_v1.yaml (currently v1.1.1).
"""
import pytest
from pydantic import ValidationError

from app.models import Category, ExtractedItem
from app.rules import RulesConfig, load_rules
from app.scoring import score_item

RULES = load_rules()


def _item(item_id, category, condition, flags):
    return ExtractedItem(
        item_id=item_id,
        item_name=f"item-{item_id}",
        category=Category(category),
        location_found="scene",
        condition=condition,
        context_flags=flags,
        confidence=0.9,
    )


def test_biological_homicide_degraded_near_body():
    # base 9 * mult 1.5 + degradation 9 + flags(near_body 3 + biological_material 0)
    #   = 13.5 + 9 + 3 = 25.5
    s = score_item(_item(0, "biological", "degraded", ["near_body", "biological_material"]),
                   "homicide", RULES)
    assert s.final_score == 25.5
    assert s.breakdown.base == 9.0
    assert s.breakdown.multiplier == 1.5
    assert s.breakdown.degradation == 9.0
    assert s.breakdown.flag_bonus == 3.0
    assert s.breakdown.raw_score == 25.5
    # forced urgent by biological_material even though score < 30 (score_urgent)
    assert s.urgency_flag is True
    assert s.needs_manual_review is False
    assert s.rules_version_hash == RULES.version_hash


def test_digital_homicide_intact_electronic_device():
    # base 8 * 1.2 + intact 2 + electronic_device 3 = 9.6 + 5 = 14.6
    s = score_item(_item(1, "digital", "intact", ["electronic_device"]), "homicide", RULES)
    assert s.final_score == 14.6
    assert s.breakdown.raw_score == 14.6
    assert s.urgency_flag is True  # electronic_device is a force-urgent flag


def test_documentary_burglary_intact_no_flags_not_urgent():
    # base 4 * 1.2 + intact 2 + 0 = 6.8
    s = score_item(_item(2, "documentary", "intact", []), "burglary", RULES)
    assert s.final_score == 6.8
    assert s.urgency_flag is False


def test_unknown_crime_defaults_multiplier_to_one():
    # 'other' base 2 * default mult 1.0 + intact 2 = 4.0
    s = score_item(_item(3, "other", "intact", []), "some_unlisted_crime", RULES)
    assert s.breakdown.multiplier == 1.0
    assert s.final_score == 4.0


def test_condition_normalization_wet_maps_to_degraded():
    # free-text 'wet' -> degraded(9). trace base 5 * hit_and_run 1.5 + 9 = 16.5
    s = score_item(_item(4, "trace", "wet", []), "hit_and_run", RULES)
    assert s.breakdown.degradation == 9.0
    assert s.final_score == 16.5


def test_score_clamp_actually_triggers():
    # Use an inflated ruleset so the raw score genuinely exceeds 100 and the clamp
    # must engage (the real rules top out ~44, so they never exercise the clamp).
    inflated = RulesConfig(
        version="test", version_hash="test",
        category_base_weights={"biological": 90},
        crime_type_multipliers={"homicide": {"biological": 5.0}},
        degradation_risk_by_condition={"degraded": 50},
        condition_normalization={}, default_condition="degraded",
        context_flag_modifiers={"near_body": 40},
        score_urgent=30, force_urgent_flags=[],
    )
    s = score_item(_item(5, "biological", "degraded", ["near_body"]), "homicide", inflated)
    assert s.breakdown.raw_score == 540.0   # 90*5 + 50 + 40
    assert s.final_score == 100.0           # clamped


def test_duplicate_flags_cannot_inflate_score():
    # Validation must reject a repeated flag — the bug that let 20x a flag hit 100.
    with pytest.raises(ValidationError):
        ExtractedItem(item_id=0, item_name="x", category=Category.other, condition="intact",
                      context_flags=["chain_of_custody_break", "chain_of_custody_break"],
                      confidence=0.9)


def test_score_path_rejects_hallucinated_flag():
    # The /score body is an ExtractedItem — it must enforce the closed vocabulary too.
    with pytest.raises(ValidationError):
        ExtractedItem(item_id=0, item_name="x", category=Category.digital, condition="intact",
                      context_flags=["teleport"], confidence=0.9)


def test_score_path_rejects_coerced_scalars():
    # strict typing: a text item_id / confidence must not be silently coerced.
    with pytest.raises(ValidationError):
        ExtractedItem(item_id="5", item_name="x", category=Category.digital,
                      condition="intact", confidence=0.9)
    with pytest.raises(ValidationError):
        ExtractedItem(item_id=0, item_name="x", category=Category.digital,
                      condition="intact", confidence="0.9")


def test_high_score_alone_triggers_urgency():
    # Three NON-force flags push the score past the 30 threshold; urgency must come
    # purely from the score, proving the threshold is reachable.
    item = _item(6, "biological", "degraded",
                 ["near_body", "signs_of_tampering", "chain_of_custody_break"])
    s = score_item(item, "homicide", RULES)
    assert s.final_score == 36.5   # 9*1.5 + 9 + (3+5+6)
    assert not any(f in RULES.force_urgent_flags for f in item.context_flags)
    assert s.urgency_flag is True


def test_unknown_condition_is_conservative_not_pristine():
    # An unrecognised condition must NOT become the lowest-risk "intact".
    s = score_item(_item(7, "biological", "half melted", []), "homicide", RULES)
    assert s.breakdown.degradation == RULES.degradation_risk_by_condition["partially_exposed"]


def test_manual_review_item_is_not_scored():
    stub = ExtractedItem.manual_review(9, item_name="garbled")
    s = score_item(stub, "homicide", RULES)
    assert s.final_score is None
    assert s.breakdown is None
    assert s.needs_manual_review is True
    assert s.urgency_flag is False
