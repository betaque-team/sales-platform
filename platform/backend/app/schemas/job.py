from pydantic import BaseModel, computed_field
from datetime import datetime
from typing import Literal
from uuid import UUID


# Regression finding 99: before this tuple existed, `BulkActionRequest.action`
# and `JobStatusUpdate.status` were typed `str` with a throwaway comment,
# which let an admin persist any garbage string (`"BOGUS_STATUS_XYZ"`,
# `"reset"`, typos). 25 prod rows already landed in a bogus `"reset"`
# state and quietly fell off `?status=new` queries, under-counting the
# review queue. Kept as a module-level tuple so the API layer and the
# cleanup script (`app.cleanup_job_status`) share one source of truth.
JOB_STATUS_VALUES = (
    "new",
    "under_review",
    "accepted",
    "rejected",
    "hidden",
    "archived",
)
JobStatusLiteral = Literal["new", "under_review", "accepted", "rejected", "hidden", "archived"]

# Regression finding 187 / 218: filter endpoints accept an extended status
# vocabulary that includes `expired` (terminal state for jobs that fell off
# the source board) in addition to the write-side `JobStatusLiteral` values.
# Two reasons they differ: (a) historical rows persisted under a legacy
# "expired" status predate the F99 vocabulary cleanup and still need to be
# filterable; (b) `hidden` is a user-driven workflow state (reviewer hid
# this row from their queue) that's written via JobStatusUpdate, while
# `expired` is set by the scan worker. The write and filter vocabularies
# will converge once the legacy "expired" rows are migrated to "archived".
# Filters live here (not in export.py) so jobs.py / export.py can both
# import — F218 is the case where diverging local definitions bit us.
JobStatusFilter = Literal[
    "new", "under_review", "accepted", "rejected", "expired", "archived"
]

# Regression finding 218: `geography_bucket` was a free-form `str` query
# param on `/jobs`, so a typo (`geography_bucket=global-remote` with a
# dash instead of underscore, `geography_bucket=USA_ONLY` mis-cased, etc.)
# silently filtered to total=0 instead of 422-ing with the allowed values.
# Values mirror the `Job.geography_bucket` column comment in models/job.py.
GeographyBucketFilter = Literal["global_remote", "usa_only", "uae_only"]

# Regression finding 191 (moved here in F218 for reuse): the platform set
# is fixed in code (BaseFetcher subclasses under `app/fetchers/`), so a
# Literal catches typos like `platform=GREENHOUSE` (uppercase) at parse
# time. Was originally declared in `api/v1/platforms.py:24`; moved here
# to avoid duplicate Literals drifting as new fetchers are added. Both
# `platforms.py` and `jobs.py` import this one definition.
PlatformFilter = Literal[
    "greenhouse", "lever", "ashby", "workable", "bamboohr",
    "smartrecruiters", "jobvite", "recruitee", "wellfound", "himalayas",
]


class JobOut(BaseModel):
    id: UUID
    external_id: str
    company_id: UUID
    company_name: str | None = None
    title: str
    url: str
    platform: str
    location_raw: str
    remote_scope: str
    department: str
    employment_type: str | None = None
    salary_range: str | None = None
    geography_bucket: str
    matched_role: str
    role_cluster: str
    relevance_score: float
    status: str
    posted_at: datetime | None = None
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}

    # Aliases to match frontend expectations
    @computed_field
    @property
    def source_platform(self) -> str:
        return self.platform

    @computed_field
    @property
    def location_restriction(self) -> str:
        return self.location_raw

    @computed_field
    @property
    def scraped_at(self) -> str:
        return self.first_seen_at.isoformat()

    @computed_field
    @property
    def created_at(self) -> str:
        return self.first_seen_at.isoformat()

    @computed_field
    @property
    def updated_at(self) -> str:
        return self.last_seen_at.isoformat()

    @computed_field
    @property
    def tags(self) -> list[str]:
        """Auto-generate tags from job metadata."""
        t = []
        if self.role_cluster:
            t.append(self.role_cluster)
        if self.geography_bucket:
            t.append(self.geography_bucket.replace("_", " "))
        if self.matched_role and self.matched_role != self.title:
            t.append(self.matched_role)
        return t


class JobDescriptionOut(BaseModel):
    # Regression finding 168: `parsed_requirements`, `parsed_nice_to_have`,
    # and `parsed_tech_stack` shipped as `list[str] = []` but were never
    # populated — the handler hard-coded `[]` at both return sites and the
    # pipeline had no extraction step. The frontend rendered them behind
    # `length > 0` guards, so they never appeared on screen either. Removed
    # rather than stubbed so the API contract reflects what the server
    # actually produces. If bullet-point extraction lands later, add the
    # fields back together with the parser that populates them.
    id: UUID | None = None
    job_id: UUID | None = None
    raw_text: str = ""

    model_config = {"from_attributes": True}


class JobStatusUpdate(BaseModel):
    # Restricted to the documented status vocabulary (see JOB_STATUS_VALUES).
    # FastAPI returns a 422 with the allowed values if a client sends
    # something else — no more silent persistence of typos / unknown states.
    status: JobStatusLiteral


class BulkActionRequest(BaseModel):
    job_ids: list[UUID]
    action: JobStatusLiteral
