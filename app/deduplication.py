import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from typing import Literal

from fastapi import APIRouter, Depends
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Lead
from app.schemas import DedupeCandidate, DedupeRequest, DedupeResponse


router = APIRouter(prefix="/leads", tags=["deduplication"])

BLOCK_FIELDS = ("email_key", "phone_key", "email_domain", "company_key")
Confidence = Literal["clear", "likely", "insufficient"]


@dataclass(frozen=True)
class DuplicateAssessment:
    lead_ids: tuple[int, int]
    score: float
    confidence: Confidence
    reasons: tuple[str, ...]


def generate_candidate_pairs(leads: Iterable[Lead]) -> set[tuple[int, int]]:
    """Generate a deduplicated pair set from the approved cheap blocking keys."""
    lead_list = list(leads)
    pairs: set[tuple[int, int]] = set()
    for field in BLOCK_FIELDS:
        blocks: dict[str, list[int]] = defaultdict(list)
        for lead in lead_list:
            value = getattr(lead, field, "") or ""
            if value:
                blocks[value].append(lead.id)
        for ids in blocks.values():
            pairs.update(combinations(sorted(set(ids)), 2))
    return pairs


def _ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return fuzz.ratio(left, right) / 100


def _name_tokens(name: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", name.casefold())


def _name_evidence(left: str, right: str) -> tuple[float, bool, bool]:
    if not left or not right:
        return 0.0, False, False

    similarity = max(fuzz.ratio(left, right), fuzz.token_sort_ratio(left, right)) / 100
    left_tokens = _name_tokens(left)
    right_tokens = _name_tokens(right)
    initial_compatible = False

    if len(left_tokens) == len(right_tokens) and left_tokens:
        token_pairs = list(zip(left_tokens, right_tokens, strict=True))
        all_compatible = all(
            first == second
            or (len(first) == 1 and second.startswith(first))
            or (len(second) == 1 and first.startswith(second))
            for first, second in token_pairs
        )
        full_token_agreement = any(
            first == second and len(first) > 1 for first, second in token_pairs
        )
        has_initial_pair = any(
            first != second and (len(first) == 1 or len(second) == 1)
            for first, second in token_pairs
        )
        initial_compatible = all_compatible and full_token_agreement and has_initial_pair
        if initial_compatible:
            similarity = max(similarity, 0.90)

    incompatible_given_names = False
    if left_tokens and right_tokens:
        left_first, right_first = left_tokens[0], right_tokens[0]
        incompatible_given_names = (
            len(left_first) > 1
            and len(right_first) > 1
            and left_first != right_first
            and _ratio(left_first, right_first) < 0.80
        )

    return similarity, initial_compatible, incompatible_given_names


def _email_local_part(email: str) -> str:
    return email.rsplit("@", 1)[0] if "@" in email else ""


def score_candidate(left: Lead, right: Lead) -> DuplicateAssessment:
    same_email = bool(left.email_key and left.email_key == right.email_key)
    same_phone = bool(left.phone_key and left.phone_key == right.phone_key)
    same_domain = bool(left.email_domain and left.email_domain == right.email_domain)
    company_similarity = _ratio(left.company_key, right.company_key)
    name_similarity, initial_compatible, incompatible_names = _name_evidence(
        left.name_key, right.name_key
    )
    local_part_similarity = _ratio(
        _email_local_part(left.email_key), _email_local_part(right.email_key)
    )

    reasons: list[str] = []
    if same_email:
        reasons.append("same normalized email")
    elif left.email_key and right.email_key:
        reasons.append("different normalized emails")
    if same_phone:
        reasons.append("same normalized phone")
    elif left.phone_key and right.phone_key:
        reasons.append("different normalized phones")
    if same_domain:
        reasons.append("same email domain")
    if name_similarity:
        reasons.append(f"name similarity {name_similarity:.0%}")
    if initial_compatible:
        reasons.append("initial/full-name compatibility")
    if company_similarity:
        reasons.append(f"company similarity {company_similarity:.0%}")
    if incompatible_names:
        reasons.append("incompatible given names")
    if left.country and right.country and left.country.casefold() != right.country.casefold():
        reasons.append("different countries")

    score = 0.0
    confidence: Confidence = "insufficient"
    if incompatible_names:
        score = 0.69 if same_email or same_phone else 0.0
    elif same_email and same_phone and name_similarity >= 0.80:
        score, confidence = 0.99, "clear"
    elif (
        same_phone
        and name_similarity >= 0.90
        and (same_domain or company_similarity >= 0.80)
    ):
        score, confidence = 0.97, "clear"
    elif same_email and name_similarity >= 0.90:
        score, confidence = 0.95, "clear"
    elif (same_email or same_phone) and name_similarity >= 0.80:
        score, confidence = 0.85, "likely"
    elif same_email and same_phone and (not left.name_key or not right.name_key):
        score, confidence = 0.85, "likely"
    elif (
        not same_email
        and not same_phone
        and name_similarity >= 0.90
        and company_similarity >= 0.80
        and same_domain
        and local_part_similarity >= 0.80
    ):
        weighted_similarity = (
            0.60 * name_similarity
            + 0.25 * company_similarity
            + 0.15 * local_part_similarity
        )
        score = 0.75 + 0.14 * weighted_similarity
        confidence = "likely"

    return DuplicateAssessment(
        lead_ids=tuple(sorted((left.id, right.id))),
        score=score,
        confidence=confidence,
        reasons=tuple(reasons),
    )


def assess_candidate_pairs(
    leads: Iterable[Lead],
) -> tuple[list[DuplicateAssessment], int]:
    lead_list = list(leads)
    leads_by_id = {lead.id: lead for lead in lead_list}
    pairs = generate_candidate_pairs(lead_list)
    assessments = [
        score_candidate(leads_by_id[left_id], leads_by_id[right_id])
        for left_id, right_id in sorted(pairs)
    ]
    return assessments, len(pairs)


@router.post("/dedupe-candidates", response_model=DedupeResponse)
def dedupe_candidates(
    request: DedupeRequest | None = None,
    session: Session = Depends(get_session),
) -> DedupeResponse:
    options = request or DedupeRequest()
    leads = session.scalars(select(Lead)).all()
    assessments, evaluated_count = assess_candidate_pairs(leads)
    matches = [
        assessment
        for assessment in assessments
        if assessment.confidence != "insufficient"
        and assessment.score >= options.min_score
    ]
    matches.sort(key=lambda item: (-item.score, item.lead_ids))

    return DedupeResponse(
        candidates=[
            DedupeCandidate(
                lead_ids=assessment.lead_ids,
                score=round(assessment.score, 4),
                confidence=assessment.confidence,
                reasons=list(assessment.reasons),
            )
            for assessment in matches[: options.limit]
        ],
        candidate_pairs_evaluated=evaluated_count,
        total_matches=len(matches),
    )
