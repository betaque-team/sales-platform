"""Review feedback processing for scoring signal generation."""

import logging
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.scoring_signal import ScoringSignal

logger = logging.getLogger(__name__)


def _upsert_signal(session: Session, signal_type: str, signal_key: str, delta: float):
    """Add delta to an existing signal or create a new one."""
    existing = session.execute(
        select(ScoringSignal).where(ScoringSignal.signal_key == signal_key)
    ).scalar_one_or_none()

    if existing:
        existing.weight += delta
        existing.source_count += 1
    else:
        import uuid
        from datetime import datetime, timezone
        session.add(ScoringSignal(
            id=uuid.uuid4(),
            signal_type=signal_type,
            signal_key=signal_key,
            weight=delta,
            source_count=1,
        ))


def process_review_feedback(session: Session, review, job):
    """Extract scoring signals from a review decision."""
    decision = review.decision
    tags = review.tags or []
    company_id = str(job.company_id) if job.company_id else ""
    role_cluster = job.role_cluster or ""
    geography = job.geography_bucket or ""
    level = ""

    # Detect level from matched_role or title
    from app.workers.tasks._role_matching import LEVEL_KEYWORDS, _normalize
    norm_title = _normalize(job.title)
    for kw, lvl in LEVEL_KEYWORDS.items():
        if kw in norm_title:
            level = lvl
            break

    if decision == "accepted":
        if company_id:
            _upsert_signal(session, "company_boost", f"company:{company_id}", 0.1)
        if role_cluster:
            _upsert_signal(session, "cluster_boost", f"cluster:{role_cluster}", 0.05)
        if geography:
            _upsert_signal(session, "geography_boost", f"geo:{geography}", 0.05)

    elif decision == "rejected":
        if tags:
            for tag in tags:
                _upsert_signal(session, "tag_penalty", f"tag:{tag}", -0.1)
                # Special tag handling
                if tag == "location_mismatch" and geography:
                    _upsert_signal(session, "geography_penalty", f"geo:{geography}", -0.1)
                elif tag == "seniority_mismatch" and level:
                    _upsert_signal(session, "level_penalty", f"level:{level}", -0.1)
                elif tag == "not_relevant" and company_id:
                    _upsert_signal(session, "company_penalty", f"company:{company_id}", -0.05)
        else:
            # Generic reject without tags
            if company_id:
                _upsert_signal(session, "company_penalty", f"company:{company_id}", -0.02)


def get_feedback_adjustment(job, signals_cache: dict) -> float:
    """Compute feedback adjustment for a job from cached signals.

    signals_cache is a dict of signal_key -> weight.
    Returns adjustment clamped to [-15, +15].
    """
    adjustment = 0.0
    company_id = str(job.company_id) if job.company_id else ""
    role_cluster = job.role_cluster or ""
    geography = job.geography_bucket or ""

    # Detect level
    from app.workers.tasks._role_matching import LEVEL_KEYWORDS, _normalize
    norm_title = _normalize(job.title)
    level = ""
    for kw, lvl in LEVEL_KEYWORDS.items():
        if kw in norm_title:
            level = lvl
            break

    # Look up matching signals
    keys_to_check = []
    if company_id:
        keys_to_check.append(f"company:{company_id}")
    if role_cluster:
        keys_to_check.append(f"cluster:{role_cluster}")
    if geography:
        keys_to_check.append(f"geo:{geography}")
    if level:
        keys_to_check.append(f"level:{level}")

    for key in keys_to_check:
        if key in signals_cache:
            adjustment += signals_cache[key]

    return max(-15.0, min(15.0, adjustment))


def decay_signals(session: Session) -> int:
    """Decay all signal weights and remove near-zero signals. Returns count removed."""
    signals = session.execute(select(ScoringSignal)).scalars().all()
    removed = 0
    for signal in signals:
        signal.weight *= signal.decay_factor
        if abs(signal.weight) < 0.001:
            session.delete(signal)
            removed += 1
    return removed
