"""Pydantic schemas for resume endpoints.

Regression finding 90: `POST /api/v1/resume/{id}/customize` declared
`body: dict`, so a caller POSTing `{"target_score": "high"}` crashed
the request with `TypeError: '<=' not supported between instances of
'int' and 'str'` — the handler did `if not (60 <= target_score <= 95)`
against whatever type came in. The error surfaced as a 500 with a
non-JSON stack trace, not the clean 400 the caller expected.

Same failure-mode class as findings #79 (credentials) and #80 (answer
book): `body: dict` writer endpoints can't enforce numeric bounds or
type coercion, so any numeric-looking field POSTed as a string crashes
with a 500 instead of returning a 422.

This schema pins the shape: `job_id` is a proper UUID (422 on garbage
strings), and `target_score` is an `int` bounded to [60, 95] via
Pydantic `Field(ge=..., le=...)` — so `"high"`, `-5`, `120`, `42.7`
and `null` all fail at parse time with a clean 422, never reach the
comparison, and never log a 500 stack trace.
"""

from uuid import UUID

from pydantic import BaseModel, Field


# Target-score bounds mirror the original manual guard in
# `api/v1/resume.py::customize_resume_for_job` (60 ≤ target ≤ 95). 60
# is the minimum useful bar for AI rewrite (below that the resume
# usually just needs the base scoring path); 95 is the ceiling we
# trust the model to hit without fabricating experience.
_TARGET_SCORE_MIN = 60
_TARGET_SCORE_MAX = 95
_TARGET_SCORE_DEFAULT = 85


class CustomizeRequest(BaseModel):
    """Body of POST /api/v1/resume/{resume_id}/customize.

    Pydantic enforces UUID parsing on `job_id` and an int-coercible
    value in [60, 95] on `target_score`. String `"85"` is accepted
    (Pydantic coerces); string `"high"` is rejected with a 422.
    """

    job_id: UUID
    target_score: int = Field(
        default=_TARGET_SCORE_DEFAULT,
        ge=_TARGET_SCORE_MIN,
        le=_TARGET_SCORE_MAX,
        description="Target ATS score (60-95) the AI customization should aim for.",
    )
