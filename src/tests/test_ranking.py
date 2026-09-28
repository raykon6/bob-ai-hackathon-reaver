"""Ranking must be a stable sort with an explicit tie-break, never insertion order."""
from app.models import Category, ExtractedItem, ScoreBreakdown, ScoredItem
from app.rules import load_rules
from app.scoring import rank_items, score_and_rank

RULES = load_rules()


def _scored(item_id, score, urgent):
    """Construct a ScoredItem directly to isolate the sort logic."""
    return ScoredItem(
        item=ExtractedItem(item_id=item_id, item_name=f"i{item_id}", category=Category.other,
                           condition="intact"),
        final_score=score,
        breakdown=ScoreBreakdown(base=0, multiplier=1, degradation=0, flag_bonus=0, raw_score=score),
        urgency_flag=urgent,
        rules_version=RULES.version,
        rules_version_hash=RULES.version_hash,
    )


def test_urgency_ranks_above_higher_non_urgent_score():
    ranked = rank_items([_scored(1, 90.0, False), _scored(2, 10.0, True)])
    assert ranked[0].item.item_id == 2  # urgent first even with far lower score
    assert ranked[0].rank == 1
    assert ranked[1].rank == 2


def test_tie_break_is_item_id_ascending_and_stable():
    # Three items tied at 42.0, deliberately inserted out of id order.
    ranked = rank_items([_scored(5, 42.0, False), _scored(2, 42.0, False), _scored(9, 42.0, False)])
    assert [r.item.item_id for r in ranked] == [2, 5, 9]


def test_tie_break_repeatable():
    items = [_scored(3, 42.0, False), _scored(1, 42.0, False), _scored(3, 42.0, False)]
    order_a = [r.item.item_id for r in rank_items(list(items))]
    order_b = [r.item.item_id for r in rank_items(list(items))]
    assert order_a == order_b == [1, 3, 3]


def test_manual_review_items_sort_last():
    stub = ScoredItem(
        item=ExtractedItem.manual_review(0),
        final_score=None, urgency_flag=False,
        rules_version=RULES.version, rules_version_hash=RULES.version_hash,
        needs_manual_review=True,
    )
    ranked = rank_items([stub, _scored(1, 5.0, False)])
    assert ranked[-1].needs_manual_review is True


def test_full_pipeline_ranks_urgent_perishable_first():
    items = [
        ExtractedItem(item_id=0, item_name="ledger book", category=Category.documentary,
                      condition="intact", context_flags=[], confidence=0.9),
        ExtractedItem(item_id=1, item_name="bloody swab", category=Category.biological,
                      condition="degraded", context_flags=["biological_material", "near_body"],
                      confidence=0.9),
    ]
    ranked = score_and_rank(items, "homicide", RULES)
    assert ranked[0].item.item_id == 1
    assert ranked[0].urgency_flag is True
