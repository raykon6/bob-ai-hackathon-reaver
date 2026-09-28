"""LLM clients for the extraction step.

`WatsonxClient` calls IBM watsonx.ai (Granite) at temperature 0 — this is "Bob"
doing the natural-language-to-structured-data work.

`OfflineExtractionClient` is a deterministic, no-network stand-in that emits the
same JSON contract using keyword rules. It exists so the pipeline runs in CI, in
tests, and in demos with zero credentials. It is NOT the production extractor and
never touches the scoring layer.

Both expose the same interface:  complete(system, user, temperature) -> str
"""
from __future__ import annotations

import json
import os
import re
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, system: str, user: str, temperature: float = 0.0) -> str: ...


# --------------------------------------------------------------------------- #
#  watsonx.ai (Granite) — real extraction
# --------------------------------------------------------------------------- #
class WatsonxClient:
    def __init__(self) -> None:
        # Imported lazily so the package works without ibm-watsonx-ai installed.
        from ibm_watsonx_ai import Credentials
        from ibm_watsonx_ai.foundation_models import ModelInference

        api_key = os.environ["WATSONX_APIKEY"]
        url = os.environ.get("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
        project_id = os.environ["WATSONX_PROJECT_ID"]
        model_id = os.environ.get("WATSONX_MODEL_ID", "ibm/granite-3-8b-instruct")

        self._model = ModelInference(
            model_id=model_id,
            credentials=Credentials(api_key=api_key, url=url),
            project_id=project_id,
        )

    def complete(self, system: str, user: str, temperature: float = 0.0) -> str:
        # Greedy decoding for reproducibility of the extraction step itself.
        params = {
            "decoding_method": "greedy",
            "temperature": temperature,
            "max_new_tokens": 1500,
            "repetition_penalty": 1.0,
        }
        prompt = f"{system}\n\nSCENE NOTES:\n{user}\n\nJSON ARRAY:"
        return self._model.generate_text(prompt=prompt, params=params)


# --------------------------------------------------------------------------- #
#  Offline deterministic extractor (fallback / CI / demo)
# --------------------------------------------------------------------------- #
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("pattern", ("fingerprint", "finger print", "latent", "palm print", "footwear",
                 "shoe print", "foot impression", "tyre", "tire", "tool mark",
                 "toolmark", "glove mark", "impression")),
    ("biological", ("blood", "bloodstain", "bloody", "dna", "semen", "saliva", "cigarette",
                    "butt", "hair", "tissue", "swab", "buccal", "vomit", "urine",
                    "fingernail", "nail clipping", "sanitary", "tampon", "bone",
                    "flesh", "skin")),
    ("ballistic", ("firearm", "pistol", "revolver", "rifle", "shotgun", "gun",
                   "cartridge", "bullet", "shell", "casing", "spent round", "gsr",
                   "gunshot residue")),
    # NOTE: bare "tablet" is deliberately NOT here — it means a pill far more often
    # at a scene. Only unambiguous device words ("tablet computer", "ipad") count.
    ("digital", ("smartphone", "phone", "cellphone", "cell phone", "iphone", "mobile",
                 "laptop", "computer", "hard disk", "hard drive", "hdd", "ssd", "usb",
                 "pen drive", "pendrive", "sim", "memory card", "sd card", "dvr", "cctv",
                 "camera", "tablet computer", "ipad", "router", "drone")),
    ("toxicological", ("powder", "tablet", "pill", "capsule", "drug", "narcotic",
                       "heroin", "cocaine", "ganja", "cannabis", "charas", "syringe",
                       "injection", "poison", "pesticide", "liquor", "alcohol",
                       "whisky", "vial", "chemical", "petrol", "diesel", "kerosene",
                       "accelerant")),
    ("documentary", ("document", "letter", "note", "cheque", "currency", "banknote",
                     "diary", "ledger", "last will", "passport", "id card", "certificate",
                     "handwriting", "signature", "forged")),
    ("trace", ("fibre", "fiber", "glass", "paint", "soil", "mud", "dust", "rope",
               "thread", "button", "sand", "pollen", "tape", "wire", "fragment",
               "burnt", "charred", "matchstick", "match", "soot", "ash",
               # weapons / physical objects — examined for tool marks & trace transfer
               "knife", "blade", "dagger", "machete", "axe", "sickle", "hammer",
               "iron rod", "screwdriver")),
]

_CONDITION_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("degraded", ("wet", "damp", "moist", "soaked", "waterlogged", "burnt", "burned",
                  "charred", "scorched", "decomposing", "decomposed", "rotting",
                  "putrefied", "bloody", "bloodstained", "corroded", "mouldy", "moldy",
                  "smeared")),
    ("partially_exposed", ("cracked", "broken", "open", "exposed", "torn", "chipped",
                           "partially", "weathered", "dirty", "muddy", "buried")),
]

# Flag keywords are matched on WORD BOUNDARIES (see _word_in) and kept specific:
# location words alone ("gate", "road", "under the") are too broad and are avoided.
_FLAG_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("near_body", ("near the body", "on the body", "beside the body", "by the body",
                   "under the body", "on the victim", "the victim", "corpse", "deceased")),
    ("exposed_to_weather", ("wet", "damp", "moist", "rain", "outdoor", "outdoors",
                            "open ground", "in the open", "backyard", "field",
                            "weathered", "waterlogged")),
    # ("soaked" alone is NOT weather: "blood-soaked towel" is found indoors. "rain-soaked"
    #  still matches via "rain".)
    ("signs_of_tampering", ("tampered", "tamper", "altered", "forged", "broken seal",
                            "wiped clean", "staged")),
    ("chain_of_custody_break", ("unsealed", "mislabelled", "mislabeled", "unlabelled",
                                "no seal", "custody break", "broken chain")),
]


def _split_lines(text: str) -> list[str]:
    # Split on newlines AND semicolons — both are strong item separators. Commas
    # are left intact because they usually separate an item from its condition
    # ("cigarette butt near the body, wet"), not two distinct items.
    out = []
    for line in re.split(r"[\n;]+", text):
        cleaned = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", line).strip()
        # Drop a leading scene-header prefix like "Homicide scene:" on the first chunk.
        cleaned = re.sub(r"^[A-Za-z ]{3,30}scene:\s*", "", cleaned, flags=re.IGNORECASE)
        if cleaned:
            out.append(cleaned)
    return out


def _word_in(text_low: str, phrase: str) -> bool:
    """Whole-word match allowing a plural/inflection suffix, so 'sim' still does
    not match 'similar', but 'fingerprint' matches 'fingerprints', 'casing'
    matches 'casings', and 'bloodstain' matches 'bloodstained'."""
    return re.search(r"\b" + re.escape(phrase) + r"(?:s|es|ed|ing)?\b", text_low) is not None


def _classify(line: str) -> dict:
    low = line.lower()

    best_cat, best_hits = "other", 0
    for cat, words in _CATEGORY_KEYWORDS:
        hits = sum(1 for w in words if _word_in(low, w))
        if hits > best_hits:
            best_cat, best_hits = cat, hits

    condition = "intact"
    for cond, words in _CONDITION_RULES:
        if any(_word_in(low, w) for w in words):
            condition = cond
            break

    flags: list[str] = []
    for flag, words in _FLAG_RULES:
        if any(_word_in(low, w) for w in words):
            flags.append(flag)
    if best_cat == "digital" and "electronic_device" not in flags:
        flags.append("electronic_device")
    if best_cat == "biological" and "biological_material" not in flags:
        flags.append("biological_material")

    location = "unspecified"
    m = re.search(r"\b(?:near|on|in|under|beside|at|by)\b\s+([^,;.]{3,40})", line, re.I)
    if m:
        location = m.group(1).strip().rstrip(".")

    return {
        "item_name": line,
        "category": best_cat,
        "location_found": location,
        "condition": condition,
        "context_flags": flags,
        "confidence": 0.9,   # fixed — offline path is deterministic, not probabilistic
    }


class OfflineExtractionClient:
    """Deterministic extractor. Emits the exact JSON contract the validator expects."""

    def complete(self, system: str, user: str, temperature: float = 0.0) -> str:
        items = [_classify(line) for line in _split_lines(user)]
        return json.dumps(items)


# --------------------------------------------------------------------------- #
# Why the last get_default_client() call fell back to offline despite watsonx
# credentials being set (None when it did not). Surfaced by GET /health so a
# silent fallback is visible instead of masquerading as the real extractor.
watsonx_fallback_reason: str | None = None


def get_default_client() -> LLMClient:
    """watsonx if credentials are present and offline mode is off, else offline."""
    global watsonx_fallback_reason
    watsonx_fallback_reason = None
    if os.environ.get("TRIAGE_OFFLINE", "0") == "1":
        return OfflineExtractionClient()
    if os.environ.get("WATSONX_APIKEY") and os.environ.get("WATSONX_PROJECT_ID"):
        try:
            return WatsonxClient()
        except Exception as exc:  # missing package / bad creds -> safe deterministic fallback
            watsonx_fallback_reason = f"{type(exc).__name__}: {exc}"
            return OfflineExtractionClient()
    return OfflineExtractionClient()
