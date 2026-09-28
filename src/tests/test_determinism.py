"""Regression against nondeterminism: the same input must produce byte-identical
output every time, across many repetitions."""
from app.models import Category, ExtractedItem
from app.rules import load_rules
from app.scoring import score_item

RULES = load_rules()


def _item():
    return ExtractedItem(
        item_id=7,
        item_name="cigarette butt",
        category=Category.biological,
        location_found="near the gate",
        condition="degraded",
        context_flags=["near_body", "biological_material", "exposed_to_weather"],
        confidence=0.9,
    )


def test_1000_runs_are_identical():
    first = score_item(_item(), "homicide", RULES).model_dump()
    for _ in range(1000):
        assert score_item(_item(), "homicide", RULES).model_dump() == first


def test_breakdown_values_are_exact_floats():
    s = score_item(_item(), "homicide", RULES)
    # 9*1.5 + 9 + (3 + 0 + 4) = 13.5 + 9 + 7 = 29.5
    assert s.breakdown.raw_score == 29.5
    assert s.final_score == 29.5
