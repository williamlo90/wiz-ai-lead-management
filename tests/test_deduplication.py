from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.deduplication import (
    assess_candidate_pairs,
    generate_candidate_pairs,
    score_candidate,
)
from app.main import create_app
from app.models import Lead
from app.normalization import (
    email_domain,
    normalize_company,
    normalize_email,
    normalize_name,
    normalize_phone,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = PROJECT_ROOT / "data" / "leads_seed.csv"


def make_lead(
    lead_id: int,
    *,
    name: str = "",
    email: str = "",
    phone: str = "",
    company: str = "",
    country: str = "United States",
) -> Lead:
    return Lead(
        id=lead_id,
        name=name,
        email=email,
        phone=phone,
        company=company,
        country=country,
        name_key=normalize_name(name),
        email_key=normalize_email(email),
        phone_key=normalize_phone(phone),
        email_domain=email_domain(email),
        company_key=normalize_company(company),
    )


def build_seeded_app(tmp_path: Path):
    database_path = tmp_path / "dedupe.db"
    return create_app(f"sqlite:///{database_path.as_posix()}", SEED_PATH)


def test_candidate_generation_is_blocked_and_deduplicated(tmp_path: Path) -> None:
    app = build_seeded_app(tmp_path)
    with TestClient(app):
        with app.state.database.session_factory() as session:
            leads = list(session.scalars(select(Lead)))

    pairs = generate_candidate_pairs(leads)
    assessments, evaluated_count = assess_candidate_pairs(leads)

    assert len(pairs) == evaluated_count == 5047
    assert all(left_id < right_id for left_id, right_id in pairs)
    assert len({assessment.lead_ids for assessment in assessments}) == len(assessments)
    assert {assessment.lead_ids for assessment in assessments} == pairs

    blank_contact_leads = [make_lead(1), make_lead(2)]
    assert generate_candidate_pairs(blank_contact_leads) == set()


def test_scoring_handles_known_matches_typos_and_false_positive_guards(tmp_path: Path) -> None:
    app = build_seeded_app(tmp_path)
    with TestClient(app):
        with app.state.database.session_factory() as session:
            ids = (100234834, 100234835, 100234846, 100234847, 100236413, 100236414)
            leads = {lead_id: session.get(Lead, lead_id) for lead_id in ids}

    initial_match = score_candidate(leads[100234834], leads[100234835])
    local_part_change = score_candidate(leads[100234846], leads[100234847])
    similar_non_match = score_candidate(leads[100236413], leads[100236414])

    assert initial_match.score == 0.99
    assert initial_match.confidence == "clear"
    assert "initial/full-name compatibility" in initial_match.reasons
    assert local_part_change.score == 0.97
    assert "different normalized emails" in local_part_change.reasons
    assert similar_non_match.score == 0.0
    assert similar_non_match.confidence == "insufficient"
    assert "incompatible given names" in similar_non_match.reasons

    typo_match = score_candidate(
        make_lead(
            1,
            name="Maya Chen",
            email="maya.chen@example.com",
            phone="+1 212 555 0101",
            company="Example Labs",
        ),
        make_lead(
            2,
            name="Mya Chen",
            email="mya.chen@example.com",
            phone="+1 212 555 0102",
            company="Example Labs",
        ),
    )
    missing_name = score_candidate(
        make_lead(3, email="same@example.com", phone="+1 212 555 0103"),
        make_lead(
            4,
            name="Known Person",
            email="same@example.com",
            phone="+1 212 555 0103",
        ),
    )

    assert 0.75 <= typo_match.score < 0.90
    assert typo_match.confidence == "likely"
    assert missing_name.score == 0.85
    assert missing_name.confidence == "likely"


@pytest.mark.parametrize(
    ("right_name", "expected_score", "expected_confidence", "incompatible"),
    [
        ("abcdefghix", 0.95, "clear", False),
        ("abcdefghxy", 0.85, "likely", False),
        ("abcdefgxyz", 0.69, "insufficient", True),
    ],
)
def test_scoring_name_thresholds_and_incompatible_guard(
    right_name: str,
    expected_score: float,
    expected_confidence: str,
    incompatible: bool,
) -> None:
    left = make_lead(
        1,
        name="abcdefghij",
        email="same@example.com",
        phone="+1 212 555 0101",
        company="Example Labs",
    )
    right = make_lead(
        2,
        name=right_name,
        email="same@example.com",
        phone="+1 212 555 9999",
        company="Example Labs",
    )

    assessment = score_candidate(left, right)

    assert assessment.score == expected_score
    assert assessment.confidence == expected_confidence
    assert ("incompatible given names" in assessment.reasons) is incompatible


def test_dedupe_endpoint_is_ranked_limited_deterministic_and_read_only(tmp_path: Path) -> None:
    app = build_seeded_app(tmp_path)
    with TestClient(app) as client:
        with app.state.database.session_factory() as session:
            count_before = session.scalar(select(func.count()).select_from(Lead))
            owner_before = session.get(Lead, 100234811).owner

        first = client.post("/leads/dedupe-candidates", json={"limit": 3})
        repeated = client.post("/leads/dedupe-candidates", json={"limit": 3})
        defaults = client.post("/leads/dedupe-candidates")
        clear_only = client.post(
            "/leads/dedupe-candidates",
            json={"min_score": 0.95, "limit": 500},
        )
        none = client.post(
            "/leads/dedupe-candidates",
            json={"min_score": 1.0, "limit": 1},
        )

        with app.state.database.session_factory() as session:
            count_after = session.scalar(select(func.count()).select_from(Lead))
            owner_after = session.get(Lead, 100234811).owner

    assert first.status_code == repeated.status_code == 200
    assert first.json() == repeated.json()
    assert first.json()["candidate_pairs_evaluated"] == 5047
    assert first.json()["total_matches"] == 289
    assert len(first.json()["candidates"]) == 3
    assert defaults.status_code == 200
    assert defaults.json()["candidate_pairs_evaluated"] == 5047
    assert len(defaults.json()["candidates"]) == 100
    assert all(
        first.json()["candidates"][index]["score"]
        >= first.json()["candidates"][index + 1]["score"]
        for index in range(2)
    )

    clear_candidates = clear_only.json()["candidates"]
    candidate_pairs = {tuple(candidate["lead_ids"]) for candidate in clear_candidates}
    assert (100234834, 100234835) in candidate_pairs
    assert (100234846, 100234847) in candidate_pairs
    assert (100236413, 100236414) not in candidate_pairs
    assert all(candidate["confidence"] == "clear" for candidate in clear_candidates)
    assert none.json()["total_matches"] == 0
    assert none.json()["candidates"] == []
    assert (count_after, owner_after) == (count_before, owner_before)


def test_dedupe_endpoint_validates_options(tmp_path: Path) -> None:
    app = build_seeded_app(tmp_path)
    with TestClient(app) as client:
        assert client.post("/leads/dedupe-candidates", json={"min_score": 0.74}).status_code == 422
        assert client.post("/leads/dedupe-candidates", json={"limit": 501}).status_code == 422
        assert client.post("/leads/dedupe-candidates", json={"unknown": True}).status_code == 422
