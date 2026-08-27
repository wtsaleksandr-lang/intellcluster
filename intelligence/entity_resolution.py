from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from intelligence.models import SourceRecord


_CORP_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "llc",
    "lp",
    "llp",
    "co",
    "company",
    "ulc",
}


def normalize_company_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    while tokens and tokens[-1] in _CORP_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_postal_code(postal_code: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (postal_code or "").upper())


@dataclass(frozen=True)
class MatchResult:
    score: float
    reasons: tuple[str, ...]

    @property
    def is_likely_match(self) -> bool:
        return self.score >= 0.82


def score_company_match(left: SourceRecord, right: SourceRecord) -> MatchResult:
    """Auditable baseline matcher for cross-dataset company resolution.

    This deliberately favors false negatives over false positives. AI/fuzzy
    matching can later review ambiguous pairs, but deterministic signals remain
    visible for debugging and provenance.
    """

    left_name = normalize_company_name(left.name)
    right_name = normalize_company_name(right.name)
    if not left_name or not right_name:
        return MatchResult(0.0, ("missing_name",))

    score = 0.0
    reasons: list[str] = []

    if left_name == right_name:
        score += 0.70
        reasons.append("exact_normalized_name")
    else:
        ratio = SequenceMatcher(None, left_name, right_name).ratio()
        if ratio >= 0.92:
            score += 0.58
            reasons.append(f"strong_name_similarity:{ratio:.2f}")
        elif ratio >= 0.82:
            score += 0.42
            reasons.append(f"moderate_name_similarity:{ratio:.2f}")
        else:
            return MatchResult(round(score, 3), tuple(reasons or [f"weak_name_similarity:{ratio:.2f}"]))

    left_postal = normalize_postal_code(left.postal_code)
    right_postal = normalize_postal_code(right.postal_code)
    if left_postal and right_postal:
        if left_postal == right_postal:
            score += 0.20
            reasons.append("postal_match")
        elif left_postal[:3] == right_postal[:3]:
            score += 0.10
            reasons.append("postal_fsa_match")

    if left.city and right.city and left.city.strip().casefold() == right.city.strip().casefold():
        score += 0.08
        reasons.append("city_match")

    if left.region and right.region and left.region.strip().casefold() == right.region.strip().casefold():
        score += 0.04
        reasons.append("region_match")

    if left.website and right.website:
        def host(value: str) -> str:
            return re.sub(r"^www\.", "", re.sub(r"^https?://", "", value.lower()).split("/")[0])

        if host(left.website) == host(right.website):
            score += 0.25
            reasons.append("domain_match")

    return MatchResult(min(round(score, 3), 1.0), tuple(reasons))
