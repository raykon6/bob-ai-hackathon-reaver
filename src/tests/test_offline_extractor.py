"""Regression tests for offline-extractor keyword bugs found in review."""
from app.llm_client import _classify


def test_tablets_are_drugs_not_devices():
    c = _classify("10 white tablets in a zip bag")
    assert c["category"] == "toxicological"
    assert "electronic_device" not in c["context_flags"]


def test_cellphone_is_digital():
    for text in ("Cellphone on the sofa", "Cell phone under the bed", "iPhone near the door"):
        c = _classify(text)
        assert c["category"] == "digital", text
        assert "electronic_device" in c["context_flags"]


def test_blood_soaked_indoors_is_not_weather_exposed():
    c = _classify("Blood-soaked towel in the bathroom")
    assert c["category"] == "biological"
    assert "exposed_to_weather" not in c["context_flags"]


def test_rain_soaked_is_still_weather_exposed():
    assert "exposed_to_weather" in _classify("Rain-soaked jacket")["context_flags"]


def test_common_word_will_is_not_documentary():
    assert _classify("Glass shard that will need drying")["category"] == "trace"
    assert _classify("Handwritten last will")["category"] == "documentary"


def test_weapons_are_classified_not_other():
    for text in ("Knife under the sofa", "Machete in the drain", "Iron rod by the door"):
        assert _classify(text)["category"] != "other", text
    # a blood-bearing weapon still goes to biology (probative + perishable)
    assert _classify("Bloodstained kitchen knife beside the body")["category"] == "biological"
