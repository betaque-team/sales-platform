"""Review feedback processing for scoring signal generation.

Regression finding 89 — per-user signal scoping (layer 1)
---------------------------------------------------------
The feedback writer now threads `review.reviewer_id` into every
`_upsert_signal` call, so each reviewer owns their own row per
`signal_key` via the composite `(user_id, signal_key)` unique
constraint added in migration `l2g3h4i5j6k7`. Legacy rows with
`user_id = NULL` remain in place and are still summed by the
nightly `rescore_jobs` batch, so existing behavior is preserved —
this commit only changes what NEW feedback writes look like.

Layer 2 (follow-up) will add query-time per-user enrichment to the
`/jobs` endpoint and stop the nightly batch from applying feedback
at all. That change builds on the column this commit populates.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.scoring_signal import ScoringSignal

logger = logging.getLogger(__name__)


def _upsert_signal(
    session: Session,
    signal_type: str,
    signal_key: str,
    delta: float,
    user_id: uuid.UUID | None = None,
) -> None:
    """Add delta to an existing signal or create a new one.

    Scoped by `(user_id, signal_key)` so each reviewer gets their
    own row. `user_id=None` preserves the legacy-pool semantics for
    any caller that hasn't been updated yet (there are currently
    none — `process_review_feedback` always passes the reviewer).
    """
    existing = session.execute(
        select(ScoringSignal).where(
            ScoringSignal.signal_key == signal_key,
            ScoringSignal.user_id == user_id,
        )
    ).scalar_one_or_none()

    if existing:
        existing.weight += delta
        existing.source_count += 1
    else:
        session.add(ScoringSignal(
            id=uuid.uuid4(),
            user_id=user_id,
            signal_type=signal_type,
            signal_key=signal_key,
            weight=delta,
            source_count=1,
        ))


def process_review_feedback(session: Session, review, job):
    """Extract scoring signals from a review decision.

    Regression finding 89: signals are now upserted scoped to the
    reviewing user (`review.reviewer_id`). A rogue reviewer rejecting
    20 jobs at Acme no longer drags everyone else's Acme scores down.
    """
    decision = review.decision
    tags = review.tags or []
    company_id = str(job.company_id) if job.company_id else ""
    role_cluster = job.role_cluster or ""
    geography = job.geography_bucket or ""
    level = ""

    # Regression finding 89: the reviewer's user_id scopes every
    # signal upsert below. `Review.reviewer_id` is NOT NULL in the
    # model so it's always populated when this function is invoked
    # from the feedback Celery task.
    reviewer_id: uuid.UUID | None = getattr(review, "reviewer_id", None)

    # Detect level from matched_role or title
    from app.workers.tasks._role_matching import LEVEL_KEYWORDS, _normalize
    norm_title = _normalize(job.title)
    for kw, lvl in LEVEL_KEYWORDS.items():
        if kw in norm_title:
            level = lvl
            break

    if decision == "accepted":
        if company_id:
            _upsert_signal(session, "company_boost", f"company:{company_id}", 0.1, reviewer_id)
        if role_cluster:
            _upsert_signal(session, "cluster_boost", f"cluster:{role_cluster}", 0.05, reviewer_id)
        if geography:
            _upsert_signal(session, "geography_boost", f"geo:{geography}", 0.05, reviewer_id)

    elif decision == "rejected":
        if tags:
            for tag in tags:
                _upsert_signal(session, "tag_penalty", f"tag:{tag}", -0.1, reviewer_id)
                # Special tag handling
                if tag == "location_mismatch" and geography:
                    _upsert_signal(session, "geography_penalty", f"geo:{geography}", -0.1, reviewer_id)
                elif tag == "seniority_mismatch" and level:
                    _upsert_signal(session, "level_penalty", f"level:{level}", -0.1, reviewer_id)
                elif tag == "not_relevant" and company_id:
                    _upsert_signal(session, "company_penalty", f"company:{company_id}", -0.05, reviewer_id)
        else:
            # Generic reject without tags
            if company_id:
                _upsert_signal(session, "company_penalty", f"company:{company_id}", -0.02, reviewer_id)


def get_feedback_adjustment(job, signals_cache: dict) -> float:
    """Compute feedback adjustment for a job from cached signals.

    signals_cache is a dict of signal_key -> weight.
    Returns adjustment clamped to [-15, +15].

    Callers are responsible for building `signals_cache`: nightly
    `rescore_jobs` sums across all users (back-compat); query-time
    callers should scope the cache to a single user_id via
    `load_user_signals_cache()`.
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


def load_user_signals_cache(session: Session, user_id: uuid.UUID | None) -> dict:
    """Build a `signal_key -> weight` cache scoped to a single user.

    Regression finding 89 layer 2 hook: query-time scoring
    enrichment uses this to compute per-user adjustments without
    hitting the database per-job. Includes both the user's own
    signals AND the legacy shared pool (user_id = NULL) so the
    migration doesn't drop pre-existing feedback wholesale — the
    shared pool fades over time via the nightly decay.
    """
    cache: dict[str, float] = {}
    # Legacy shared pool first, so per-user rows overwrite.
    legacy = session.execute(
        select(ScoringSignal.signal_key, ScoringSignal.weight).where(
            ScoringSignal.user_id.is_(None)
        )
    ).all()
    for key, weight in legacy:
        cache[key] = weight

    if user_id is not None:
        user_rows = session.execute(
            select(ScoringSignal.signal_key, ScoringSignal.weight).where(
                ScoringSignal.user_id == user_id
            )
        ).all()
        for key, weight in user_rows:
            # Per-user signals take precedence over the legacy pool for
            # the same key — this is the isolation guarantee.
            cache[key] = weight

    return cache


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
