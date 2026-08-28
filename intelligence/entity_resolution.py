from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from intelligence.models import SourceRecord


_CORP_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "ltd", "limited", "llc",
    "lp", "llp", "co", "company", "ulc", "plc", "gmbh", "sa", "ag",
}
_COUNTRY_ALIASES = {
    "ca": "CA", "can": "CA", "canada": "CA",
    "us": "US", "usa": "US", "united states": "US", "united states of america": "US",
}


def normalize_company_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    while tokens and tokens[-1] in _CORP_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_postal_code(postal_code: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (postal_code or "").upper())


def normalize_country(country: str | None) -> str:
    value = re.sub(r"\s+", " ", (country or "").strip().casefold())
    return _COUNTRY_ALIASES.get(value, value.upper())


def normalize_domain(website: str | None) -> str:
    value = (website or "").strip().lower()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    try:
        host = (urlsplit(value).hostname or "").strip(".")
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _same_text(left: str | None, right: str | None) -> bool:
    return bool(left and right and left.strip().casefold() == right.strip().casefold())


@dataclass(frozen=True)
class MatchResult:
    score: float
    reasons: tuple[str, ...]
    hard_conflict: bool = False

    @property
    def is_likely_match(self) -> bool:
        return not self.hard_conflict and self.score >= 0.82

    @property
    def needs_review(self) -> bool:
        return not self.hard_conflict and 0.68 <= self.score < 0.82


def score_company_match(left: SourceRecord, right: SourceRecord) -> MatchResult:
    """Conservative, auditable cross-source company matcher.

    Strong contradictions are treated as hard conflicts rather than allowing a
    fuzzy name to merge unrelated companies. Ambiguous pairs remain reviewable
    instead of being silently merged.
    """
    left_name = normalize_company_name(left.name)
    right_name = normalize_company_name(right.name)
    if not left_name or not right_name:
        return MatchResult(0.0, ("missing_name",))

    left_country = normalize_country(left.country)
    right_country = normalize_country(right.country)
    if left_country and right_country and left_country != right_country:
        return MatchResult(0.0, ("country_conflict",), True)

    left_domain = normalize_domain(left.website)
    right_domain = normalize_domain(right.website)
    if left_domain and right_domain and left_domain != right_domain:
        # A domain contradiction is decisive only when the names are not exact;
        # large groups can legitimately operate multiple domains.
        if left_name != right_name:
            return MatchResult(0.0, ("domain_conflict",), True)

    score = 0.0
    reasons: list[str] = []
    if left_name == right_name:
        score += 0.70
        reasons.append("exact_normalized_name")
    else:
        ratio = SequenceMatcher(None, left_name, right_name).ratio()
        if ratio >= 0.94:
            score += 0.58
            reasons.append(f"strong_name_similarity:{ratio:.2f}")
        elif ratio >= 0.86:
            score += 0.42
            reasons.append(f"moderate_name_similarity:{ratio:.2f}")
        else:
            return MatchResult(0.0, (f"weak_name_similarity:{ratio:.2f}",))

    if left_domain and right_domain and left_domain == right_domain:
        score += 0.28
        reasons.append("domain_match")

    left_postal = normalize_postal_code(left.postal_code)
    right_postal = normalize_postal_code(right.postal_code)
    if left_postal and right_postal:
        if left_postal == right_postal:
            score += 0.20
            reasons.append("postal_match")
        elif left_country == right_country == "CA" and left_postal[:3] == right_postal[:3]:
            score += 0.10
            reasons.append("postal_fsa_match")
        elif left_country == right_country == "US" and left_postal[:5] == right_postal[:5]:
            score += 0.10
            reasons.append("zip5_match")
        elif _same_text(left.city, right.city) is False and left.city and right.city:
            score -= 0.12
            reasons.append("postal_and_city_conflict")

    if _same_text(left.city, right.city):
        score += 0.08
        reasons.append("city_match")
    elif left.city and right.city:
        score -= 0.05
        reasons.append("city_conflict")

    if _same_text(left.region, right.region):
        score += 0.04
        reasons.append("region_match")
    elif left.region and right.region:
        score -= 0.08
        reasons.append("region_conflict")

    # Exact names alone are intentionally below auto-merge threshold. They need
    # at least one corroborating geography/domain signal to avoid common-name
    # collisions across large U.S./Canadian datasets.
    return MatchResult(min(max(round(score, 3), 0.0), 1.0), tuple(reasons))
