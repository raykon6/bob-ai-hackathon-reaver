"""The Bob extraction layer must validate strictly, retry on failure, and never
let malformed or hallucinated data reach the scorer."""
import json

from app.extraction import extract_items
from app.models import ExtractedItem
from app.scoring import score_item
from app.rules import load_rules

RULES = load_rules()

GOOD = json.dumps([
    {"item_name": "knife", "category": "biological", "location_found": "kitchen",
     "condition": "degraded", "context_flags": ["biological_material"], "confidence": 0.9}
])


class ScriptedClient:
    """Returns queued responses in order; repeats the last one if exhausted.
    Counts calls so we can assert the retry path actually ran."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def complete(self, system, user, temperature=0.0):
        self.calls += 1
        idx = min(self.calls - 1, len(self._responses) - 1)
        return self._responses[idx]


def test_malformed_json_triggers_retries_then_manual_review():
    client = ScriptedClient(["not json at all", "still broken {", "<xml>nope</xml>"])
    items = extract_items("cigarette butt\nbloody knife", client=client)
    assert client.calls == 3  # 1 initial + 2 retries
    assert all(i.needs_manual_review for i in items)
    assert all(i.category is None for i in items)  # nothing guessed


def test_invalid_then_valid_recovers_on_retry():
    client = ScriptedClient(["garbage", GOOD])
    items = extract_items("knife", client=client)
    assert client.calls == 2
    assert len(items) == 1
    assert items[0].needs_manual_review is False
    assert items[0].category.value == "biological"


def test_hallucinated_category_is_rejected_not_coerced():
    bad = json.dumps([
        {"item_name": "orb", "category": "magic", "location_found": "x",
         "condition": "intact", "context_flags": [], "confidence": 0.5}
    ])
    client = ScriptedClient([bad, bad, bad])
    items = extract_items("orb", client=client)
    assert client.calls == 3
    assert all(i.needs_manual_review for i in items)
    assert all(i.category is None for i in items)


def test_hallucinated_flag_is_rejected():
    bad = json.dumps([
        {"item_name": "phone", "category": "digital", "location_found": "sofa",
         "condition": "intact", "context_flags": ["teleport"], "confidence": 0.8}
    ])
    client = ScriptedClient([bad])
    items = extract_items("phone", client=client, max_retries=0)
    assert items[0].needs_manual_review is True


def test_bad_data_never_reaches_scorer_with_a_score():
    client = ScriptedClient(["broken"])
    items = extract_items("mystery item", client=client, max_retries=0)
    scored = [score_item(i, "homicide", RULES) for i in items]
    assert all(s.final_score is None for s in scored)
    assert all(s.needs_manual_review for s in scored)


def test_partial_batch_keeps_good_flags_bad():
    mixed = json.dumps([
        {"item_name": "knife", "category": "biological", "location_found": "kitchen",
         "condition": "degraded", "context_flags": [], "confidence": 0.9},
        {"item_name": "orb", "category": "magic", "location_found": "x",
         "condition": "intact", "context_flags": [], "confidence": 0.5},
    ])
    client = ScriptedClient([mixed])
    items = extract_items("knife\norb", client=client, max_retries=0)
    by_id = {i.item_id: i for i in items}
    assert by_id[0].needs_manual_review is False
    assert by_id[0].category.value == "biological"
    assert by_id[1].needs_manual_review is True
    assert by_id[1].category is None
