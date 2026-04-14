"""Celery tasks for review feedback processing."""

import logging
from sqlalchemy import select
from app.workers.celery_app import celery_app
from app.workers.tasks._db import SyncSession
from app.workers.tasks._feedback import process_review_feedback, decay_signals
from app.models.review import Review
from app.models.job import Job

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.feedback_task.process_review_feedback_task")
def process_review_feedback_task(review_id: str):
    """Process a review and generate scoring signals."""
    session = SyncSession()
    try:
        review = session.execute(
            select(Review).where(Review.id == review_id)
        ).scalar_one_or_none()
        if not review:
            logger.warning("Review not found: %s", review_id)
            return

        job = session.execute(
            select(Job).where(Job.id == review.job_id)
        ).scalar_one_or_none()
        if not job:
            logger.warning("Job not found for review: %s", review_id)
            return

        process_review_feedback(session, review, job)
        session.commit()
        logger.info("Processed feedback for review %s (decision=%s)", review_id, review.decision)
    except Exception as e:
        logger.exception("process_review_feedback_task failed: %s", e)
        session.rollback()
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.feedback_task.decay_scoring_signals")
def decay_scoring_signals():
    """Nightly decay of scoring signals."""
    session = SyncSession()
    try:
        removed = decay_signals(session)
        session.commit()
        logger.info("Decayed scoring signals, removed %d near-zero signals", removed)
        return {"removed": removed}
    except Exception as e:
        logger.exception("decay_scoring_signals failed: %s", e)
        session.rollback()
    finally:
        session.close()
