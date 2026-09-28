"""Bob extraction layer: raw scene text -> validated ExtractedItem list.

Contract with the model:
  * temperature 0
  * output ONLY a JSON array of objects matching RawExtractedItem
  * category from the fixed enum, context_flags from the fixed vocabulary

Validation is strict. On failure we retry up to 2 times, feeding the exact error
back to the model. After 2 failed retries we DO NOT guess: valid items pass
through, and anything still invalid becomes a needs_manual_review stub with nulled
fields. A hallucinated category or flag can never reach the scorer.
"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from .llm_client import LLMClient, _split_lines, get_default_client
from .models import ALLOWED_CONTEXT_FLAGS, Category, ExtractedItem, RawExtractedItem

MAX_RETRIES = 2


class ExtractionUnavailable(RuntimeError):
    """The model could not be reached at all (network, auth, quota). Distinct from
    bad model OUTPUT, which is handled by retry + manual review. Callers turn this
    into a clear error (HTTP 503) instead of a bare 500 or a silent fallback."""

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def build_system_prompt() -> str:
    categories = ", ".join(c.value for c in Category)
    flags = ", ".join(ALLOWED_CONTEXT_FLAGS)
    return (
        "You are a forensic evidence intake assistant. Read the crime-scene notes "
        "and output ONLY a JSON array. No prose, no markdown, no code fences.\n"
        "Each array element must be an object with EXACTLY these keys:\n"
        '  "item_name": string\n'
        f'  "category": one of [{categories}]\n'
        '  "location_found": string\n'
        '  "condition": string (e.g. "intact", "degraded", "partially exposed")\n'
        f'  "context_flags": array of strings, each from [{flags}]\n'
        '  "confidence": number between 0 and 1\n'
        "Do not invent categories or flags outside those lists. Do not assign any "
        "priority, score, rank, or urgency — that is decided elsewhere. Extract and "
        "classify only. If unsure of a field, use your best factual reading; if a "
        "flag does not apply, omit it."
    )


def _parse_json_array(text: str):
    """Parse the model output as JSON; if a shell wrapper (e.g. Bob Shell) added
    prose around it, fall back to the outermost [...] block. The result is still
    strictly validated item by item, so this never lets bad data through."""
    cleaned = _strip_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start == -1 or end <= start:
            raise
        return json.loads(cleaned[start:end + 1])


def _strip_fences(text: str) -> str:
    # Defensive only — the prompt forbids fences, but a stray ``` shouldn't break us.
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _FENCE_RE.sub("", stripped)
    return stripped.strip()


def _validation_summary(bad: list[tuple[int, ValidationError]]) -> str:
    parts = []
    for idx, err in bad:
        first = err.errors()[0] if err.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []))
        parts.append(f"item[{idx}].{loc}: {first.get('msg', str(err))}")
    return "; ".join(parts)


def extract_items_with_raw(
    raw_text: str,
    client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> tuple[list[ExtractedItem], str]:
    """Like extract_items, but also returns the verbatim model response that
    produced the result (the final attempt), so the audit log can store exactly
    what the model returned — not just the cleaned-up items."""
    client = client or get_default_client()
    system = build_system_prompt()
    error_context = ""
    last_response = ""

    for attempt in range(max_retries + 1):
        is_last = attempt == max_retries
        try:
            response = client.complete(system + error_context, raw_text, temperature=0.0)
        except Exception as exc:
            raise ExtractionUnavailable(
                f"extraction model call failed ({type(exc).__name__}: {exc})"
            ) from exc
        last_response = response

        try:
            data = _parse_json_array(response)
            if not isinstance(data, list):
                raise ValueError("top-level JSON value must be an array")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            if is_last:
                # Never fabricate — hand the whole batch to manual review.
                items = [
                    ExtractedItem.manual_review(i, item_name=line)
                    for i, line in enumerate(_split_lines(raw_text))
                ] or [ExtractedItem.manual_review(0)]
                return items, response
            error_context = (
                f"\n\nPREVIOUS OUTPUT WAS INVALID JSON: {exc}. "
                "Return ONLY a JSON array this time."
            )
            continue

        valid: list[tuple[int, RawExtractedItem]] = []
        bad: list[tuple[int, ValidationError]] = []
        for idx, obj in enumerate(data):
            try:
                valid.append((idx, RawExtractedItem.model_validate(obj)))
            except ValidationError as exc:
                bad.append((idx, exc))

        if not bad:
            return [ExtractedItem.from_raw(idx, raw) for idx, raw in valid], response

        if is_last:
            # Keep the good ones; flag the rest for manual review. No guessing.
            out = [ExtractedItem.from_raw(idx, raw) for idx, raw in valid]
            out.extend(ExtractedItem.manual_review(idx) for idx, _ in bad)
            out.sort(key=lambda x: x.item_id)
            return out, response

        error_context = (
            f"\n\nPREVIOUS OUTPUT HAD VALIDATION ERRORS: {_validation_summary(bad)}. "
            "Fix ONLY those objects and return the full JSON array again."
        )

    return [], last_response


def extract_items(
    raw_text: str,
    client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> list[ExtractedItem]:
    return extract_items_with_raw(raw_text, client, max_retries)[0]
