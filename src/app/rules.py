"""Load, validate and hash the versioned rules config.

The SHA-256 is computed over the file bytes after normalizing line endings to LF
(CRLF/CR -> LF), so it changes if and only if the file content changes -- not when
git checks the file out with Windows line endings. That hash is stamped onto every ScoredItem for traceability.
"""
from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "rules_v1.yaml"


class RulesConfig(BaseModel):
    version: str
    version_hash: str
    category_base_weights: dict[str, float]
    crime_type_multipliers: dict[str, dict[str, float]]
    degradation_risk_by_condition: dict[str, float]
    condition_normalization: dict[str, str]
    default_condition: str
    context_flag_modifiers: dict[str, float]
    score_urgent: float
    force_urgent_flags: list[str]

    # ---- dynamic (case-specific) rulesets --------------------------------------
    # A case ruleset is not a file, so it is hashed over its canonical JSON instead:
    # sorted keys + fixed separators give byte-identical output for identical content.

    def to_mapping(self) -> dict:
        """Every scoring parameter, without the version/hash identity fields."""
        return {
            "category_base_weights": dict(self.category_base_weights),
            "crime_type_multipliers": {k: dict(v) for k, v in self.crime_type_multipliers.items()},
            "degradation_risk_by_condition": dict(self.degradation_risk_by_condition),
            "condition_normalization": dict(self.condition_normalization),
            "default_condition": self.default_condition,
            "context_flag_modifiers": dict(self.context_flag_modifiers),
            "score_urgent": self.score_urgent,
            "force_urgent_flags": list(self.force_urgent_flags),
        }

    @staticmethod
    def canonical_hash(mapping: dict) -> str:
        canonical = json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()
        return "case-" + hashlib.sha256(canonical).hexdigest()

    @classmethod
    def from_mapping(cls, mapping: dict, *, version: str) -> "RulesConfig":
        """Freeze a (validated) parameter mapping into an immutable, hashed ruleset."""
        return cls(version=version, version_hash=cls.canonical_hash(mapping), **mapping)

    def normalize_condition(self, condition: Optional[str]) -> str:
        """Map a free-text condition onto a canonical degradation key.

        Deterministic: lowercases, trims, collapses spaces/hyphens to underscores,
        then looks up the normalization table, then the degradation table directly,
        then falls back to `default_condition`.
        """
        if not condition:
            return self.default_condition
        key = condition.strip().lower().replace("-", "_").replace(" ", "_")
        if key in self.condition_normalization:
            return self.condition_normalization[key]
        if key in self.degradation_risk_by_condition:
            return key
        return self.default_condition


def load_rules(path: Path | str = DEFAULT_RULES_PATH) -> RulesConfig:
    raw_bytes = Path(path).read_bytes()
    # Normalize line endings before hashing so the SAME rules produce the SAME
    # hash on Windows (CRLF) and Unix (LF) checkouts — otherwise git's autocrlf
    # would give teammates different hashes for an identical ruleset.
    canonical = raw_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    data = yaml.safe_load(canonical)
    version_hash = hashlib.sha256(canonical).hexdigest()
    thresholds = data["urgency_thresholds"]
    cfg = RulesConfig(
        version=str(data["version"]),
        version_hash=version_hash,
        category_base_weights=data["category_base_weights"],
        crime_type_multipliers=data["crime_type_multipliers"],
        degradation_risk_by_condition=data["degradation_risk_by_condition"],
        condition_normalization=data.get("condition_normalization", {}),
        default_condition=data.get("default_condition", "intact"),
        context_flag_modifiers=data["context_flag_modifiers"],
        score_urgent=thresholds["score_urgent"],
        force_urgent_flags=list(thresholds["force_urgent_flags"]),
    )
    # Validate the ruleset itself: every evidence category must have a base weight,
    # so a typo in the YAML fails loudly instead of silently defaulting to "other".
    from .models import Category
    missing = [c.value for c in Category if c.value not in cfg.category_base_weights]
    if missing:
        raise ValueError(f"rules_v1.yaml is missing base weights for categories: {missing}")
    return cfg


@functools.lru_cache(maxsize=None)
def get_rules() -> RulesConfig:
    """Cached singleton loaded once at startup."""
    return load_rules()
