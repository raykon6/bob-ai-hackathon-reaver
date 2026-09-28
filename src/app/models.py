"""Pydantic v2 schemas.

Two extraction models on purpose:
  * RawExtractedItem  — the STRICT validation target for raw LLM output. extra
    fields forbidden, category constrained to the enum, context_flags constrained
    to the fixed vocabulary AND required to be unique. A hallucinated category or
    flag, or a repeated flag, raises here and is never coerced.
  * ExtractedItem     — the pipeline object, also used as the /score request body.
    It carries an item_id and a needs_manual_review escape hatch with nullable
    fields, but it applies the SAME closed-vocabulary + uniqueness check and strict
    scalar typing, so the deterministic scoring path cannot be fed junk either.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Category(str, Enum):
    biological = "biological"
    trace = "trace"
    digital = "digital"
    toxicological = "toxicological"
    pattern = "pattern"
    documentary = "documentary"
    ballistic = "ballistic"
    other = "other"


# Fixed, closed vocabulary. Anything outside this set is rejected, not corrected.
ALLOWED_CONTEXT_FLAGS: tuple[str, ...] = (
    "near_body",
    "exposed_to_weather",
    "signs_of_tampering",
    "electronic_device",
    "biological_material",
    "chain_of_custody_break",
)


def validate_context_flags(v: list[str]) -> list[str]:
    """Reject flags outside the vocabulary AND reject duplicates.

    Duplicate rejection matters: without it, a model that repeats a scoring flag
    N times multiplies its bonus and can push any item to the maximum score —
    which would let bad model output change a priority. The scorer also de-dupes
    defensively, but validation is the real guard.
    """
    unknown = [f for f in v if f not in ALLOWED_CONTEXT_FLAGS]
    if unknown:
        raise ValueError(
            f"context_flags contains values outside the allowed vocabulary: {unknown}"
        )
    seen, dupes = set(), []
    for f in v:
        if f in seen and f not in dupes:
            dupes.append(f)
        seen.add(f)
    if dupes:
        raise ValueError(f"context_flags contains duplicates: {dupes}")
    return v


def validate_raw_text(v: str) -> str:
    """Reject blank scene text: it would yield an empty schedule and an empty,
    un-auditable run (the returned session_id would 404 on /audit)."""
    if not v.strip():
        raise ValueError("raw_text must contain at least one evidence item")
    return v


def validate_crime_type(v: str) -> str:
    """Reject an unrecognised crime type (e.g. a typo like 'homocide') instead of
    silently treating it as 'unknown' with all multipliers = 1.0. Allowed values
    are the crime types defined in rules_v1.yaml, plus the explicit 'unknown'."""
    from .rules import get_rules  # lazy: rules imports this module
    allowed = set(get_rules().crime_type_multipliers) | {"unknown"}
    if v not in allowed:
        raise ValueError(
            f"unknown crime_type {v!r}; expected one of {sorted(allowed)}"
        )
    return v


class RawExtractedItem(BaseModel):
    """Strict validation target for a single object in the LLM's JSON array.

    Scalars are strict (no silent type coercion — "0.9" is not accepted for a
    float, 123 is not accepted for a string). `category` and `context_flags` are
    a closed enum / closed vocabulary, so an out-of-set or repeated value raises
    rather than being coerced — but a JSON *string* is still allowed to name an
    enum member, which is what the model actually emits. `extra="forbid"` rejects
    stray keys.
    """

    model_config = ConfigDict(extra="forbid")

    item_name: str = Field(strict=True)
    category: Category
    location_found: str = Field(strict=True)
    condition: str = Field(strict=True)
    context_flags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, strict=True)

    _check_flags = field_validator("context_flags")(staticmethod(validate_context_flags))


class ExtractedItem(BaseModel):
    """Pipeline representation of an extracted item (post-validation).

    Also the /score and MCP score_evidence request shape, so it enforces the same
    closed vocabulary + uniqueness and strict id/confidence typing — the scoring
    path is not a back door around validation.
    """

    model_config = ConfigDict(extra="forbid")

    item_id: int = Field(strict=True)
    item_name: str
    category: Optional[Category] = None
    location_found: Optional[str] = None
    condition: Optional[str] = None
    context_flags: list[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, strict=True)
    needs_manual_review: bool = False

    _check_flags = field_validator("context_flags")(staticmethod(validate_context_flags))

    @classmethod
    def from_raw(cls, item_id: int, raw: RawExtractedItem) -> "ExtractedItem":
        return cls(
            item_id=item_id,
            item_name=raw.item_name,
            category=raw.category,
            location_found=raw.location_found,
            condition=raw.condition,
            context_flags=list(raw.context_flags),
            confidence=raw.confidence,
        )

    @classmethod
    def manual_review(cls, item_id: int, item_name: str = "Unparsed item") -> "ExtractedItem":
        """Built when validation fails after retries — nulled fields, flagged.
        Never passed to the scorer (score_item excludes it explicitly)."""
        return cls(item_id=item_id, item_name=item_name, needs_manual_review=True)


class ScoreBreakdown(BaseModel):
    """Every contributing term, so a score can always be explained/audited."""

    base: float
    multiplier: float
    degradation: float
    flag_bonus: float
    raw_score: float


class ScoredItem(BaseModel):
    rank: Optional[int] = None
    item: ExtractedItem
    final_score: Optional[float] = None          # None only for manual-review items
    breakdown: Optional[ScoreBreakdown] = None
    urgency_flag: bool = False
    rules_version: str
    rules_version_hash: str
    rationale: str = ""
    needs_manual_review: bool = False


# ---- API request/response envelopes ----------------------------------------

class ExtractRequest(BaseModel):
    raw_text: str
    crime_type: str = "unknown"
    _check_text = field_validator("raw_text")(staticmethod(validate_raw_text))
    _check_crime = field_validator("crime_type")(staticmethod(validate_crime_type))


class ScoreRequest(BaseModel):
    items: list[ExtractedItem]
    crime_type: str = "unknown"
    _check_crime = field_validator("crime_type")(staticmethod(validate_crime_type))


class TriageRequest(BaseModel):
    raw_text: str
    crime_type: str = "unknown"
    _check_text = field_validator("raw_text")(staticmethod(validate_raw_text))
    _check_crime = field_validator("crime_type")(staticmethod(validate_crime_type))


class TriageResponse(BaseModel):
    session_id: str
    crime_type: str
    rules_version: str
    rules_version_hash: str
    generated_at: str
    extractor: str = "unknown"   # which extractor actually ran: watsonx | offline-deterministic
    schedule: list[ScoredItem]
