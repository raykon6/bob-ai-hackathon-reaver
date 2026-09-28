"""Crime Scene Evidence Triage — application package.

Architecture in one line:
    Bob/watsonx EXTRACTS structured items  ->  deterministic Python SCORES & RANKS.

The LLM never assigns a number. Scoring is a pure function of (item, crime_type,
rules) and is stamped with the SHA-256 hash of the ruleset that produced it.
"""

__version__ = "1.0.0"
