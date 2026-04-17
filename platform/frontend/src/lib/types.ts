export interface User {
  id: string;
  email: string;
  name: string;
  picture: string;
  role: "super_admin" | "admin" | "reviewer" | "viewer";
  active_resume_id?: string;
  has_password?: boolean;
  created_at: string;
}

export interface ManagedUser {
  id: string;
  email: string;
  name: string;
  avatar_url: string;
  role: "super_admin" | "admin" | "reviewer" | "viewer";
  is_active: boolean;
  has_password: boolean;
  has_google: boolean;
  created_at: string | null;
  last_login_at: string | null;
}

export interface RoleInfo {
  name: string;
  description: string;
}

export interface ScanTaskResult {
  task_id: string;
  status: string;
  platform?: string;
  scope?: string;
  boards?: number;
  board?: string;
}

export interface ScanTaskStatus {
  task_id: string;
  status: string;
  result?: any;
}

export type JobStatus =
  | "new"
  | "under_review"
  | "accepted"
  | "rejected"
  | "expired";

export interface Job {
  id: string;
  company_id: string;
  company_name: string;
  title: string;
  url: string;
  source_platform: string;
  remote_scope: string;
  location_restriction: string;
  employment_type: string | null;
  salary_range: string | null;
  status: JobStatus;
  relevance_score: number;
  role_cluster: "infra" | "security";
  geography_bucket: "global_remote" | "usa_only" | "uae_only";
  tags: string[];
  resume_score?: number | null;
  // Team-wide best resume fit — set by /jobs/review-queue (see the
  // handler comment in backend/app/api/v1/jobs.py for the ordering
  // tier it drives). `null` means no resume has scored this job yet.
  max_resume_score?: number | null;
  first_seen_at?: string;
  resume_fit?: {
    overall_score: number;
    keyword_score: number;
    role_match_score: number;
    format_score: number;
    matched_keywords: string[];
    missing_keywords: string[];
    suggestions: string[];
  } | null;
  scraped_at: string;
  created_at: string;
  updated_at: string;
}

export interface JobDescription {
  id: string;
  job_id: string;
  raw_text: string;
  // Regression finding 168: previously declared `parsed_requirements`,
  // `parsed_nice_to_have`, `parsed_tech_stack` — backend shipped them
  // as always-empty arrays (no extraction ever wired up) and the UI
  // rendered them behind `length > 0` guards that were never true.
  // Fields removed from both sides of the contract; add back together
  // with a real parser if that work lands.
}

export interface Review {
  id: string;
  job_id: string;
  reviewer_id: string;
  reviewer_name: string;
  decision: "accept" | "reject" | "skip";
  comment: string;
  tags: string[];
  created_at: string;
}

export interface Company {
  id: string;
  name: string;
  slug: string;
  website: string | null;
  logo_url: string;
  industry: string;
  employee_count: string;
  funding_stage: string;
  headquarters: string;
  description: string;
  is_target: boolean;
  tags: string[];
  domain: string;
  founded_year: number | null;
  total_funding: string;
  linkedin_url: string;
  twitter_url: string;
  tech_stack: string[];
  enrichment_status: "pending" | "enriching" | "enriched" | "failed";
  enriched_at: string | null;
  funded_at: string | null;
  funding_news_url: string;
  ats_boards: ATSBoard[];
  job_count: number;
  accepted_count: number;
  contact_count: number;
  created_at: string;
  updated_at: string;
}

export type OutreachStatus = "not_contacted" | "emailed" | "replied" | "meeting_scheduled" | "not_interested";

export interface CompanyContact {
  id: string;
  company_id: string;
  first_name: string;
  last_name: string;
  title: string;
  role_category: string;
  department: string;
  seniority: string;
  email: string;
  email_status: "unverified" | "valid" | "invalid" | "catch_all";
  email_verified_at: string | null;
  phone: string;
  linkedin_url: string;
  twitter_url: string;
  telegram_id: string;
  source: string;
  confidence_score: number;
  is_decision_maker: boolean;
  outreach_status: OutreachStatus;
  outreach_note: string;
  last_outreach_at: string | null;
  last_verified_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface FundingSignal {
  company_id: string;
  company_name: string;
  domain: string;
  industry: string;
  total_funding: string;
  funding_stage: string;
  funded_at: string | null;
  days_since_funded: number | null;
  funding_news_url: string;
  employee_count: string;
  is_target: boolean;
  total_contacts: number;
  decision_makers: number;
  verified_contacts: number;
  open_roles: number;
}

export interface WarmLead {
  company_id: string;
  company_name: string;
  domain: string;
  industry: string;
  total_funding: string;
  funding_stage: string;
  is_target: boolean;
  new_jobs_30d: number;
  new_jobs_7d: number;
  top_relevance_score: number;
  total_contacts: number;
  verified_contacts: number;
  decision_makers: number;
}

export interface CompanyOffice {
  id: string;
  company_id: string;
  label: string;
  address: string;
  city: string;
  state: string;
  country: string;
  is_headquarters: boolean;
  source: string;
}

export interface CompanyDetail extends Company {
  contacts: CompanyContact[];
  offices: CompanyOffice[];
  actively_hiring: boolean;
  hiring_velocity: string;
  total_open_roles: number;
  enrichment_error: string;
}

export interface JobRelevantContact {
  contact: CompanyContact;
  relevance_reason: string;
  relevance_score: number;
}

export interface ATSBoard {
  id: string;
  company_id: string;
  platform: string;
  board_url: string;
  last_scraped_at: string | null;
}

export type PipelineStage = string;

export interface PipelineStageConfig {
  id: string;
  key: string;
  label: string;
  color: string;
  sort_order: number;
  is_active: boolean;
}

export interface PipelineItem {
  id: string;
  company_id: string | null;
  company_name: string;
  company_website: string;
  stage: PipelineStage;
  priority: number;
  assigned_to: string | null;
  resume_id: string | null;
  applied_by: string | null;
  applied_by_name: string | null;
  resume_label: string | null;
  notes: string;
  created_at: string;
  hiring_velocity: "high" | "medium" | "low";
  total_open_roles: number;
  accepted_jobs_count: number;
  last_job_at: string | null;
}

// F215: backend `/pipeline` now returns canonical `items: PipelineItem[]`
// (flat list) + `by_stage: Record<string, PipelineItem[]>` (kanban view).
// PipelinePage renders the kanban columns so it reads `by_stage`. Any
// future consumer that wants a generic pager can use `items`.
export interface PipelineResponse {
  stages: string[];
  stages_config: { key: string; label: string; color: string }[];
  items: PipelineItem[];
  by_stage: Record<string, PipelineItem[]>;
  total: number;
}

export interface AnalyticsOverview {
  total_jobs: number;
  total_companies: number;
  pipeline_active: number;
  reviewed_count: number;
  accepted_count: number;
  rejected_count: number;
  acceptance_rate: number;
  avg_relevance_score: number;
}

export interface SourceDistribution {
  platform: string;
  count: number;
}

export interface TrendDataPoint {
  day: string;
  date?: string;
  total: number;
  infra: number;
  security: number;
  accepted: number;
  // legacy
  count?: number;
  new_jobs?: number;
  rejected?: number;
}

export interface FunnelStep {
  stage: string;
  count: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// Review queue: prioritized list + per-date-bucket counts so the page
// can render "N today · N yesterday · N older" chips above the card.
// The three counts reconcile exactly with `total` because the stats
// query uses the same WHERE chain as the items query.
export interface ReviewQueueResponse extends PaginatedResponse<Job> {
  stats: {
    today: number;
    yesterday: number;
    older: number;
    total: number;
  };
}

// Multi-column sort: each entry is a (column key, direction) pair, in
// priority order. Position 0 is the primary sort, position 1 the
// secondary tiebreaker, etc. Serialised on the wire as
// `sort_by=relevance_score:desc,first_seen_at:desc` (comma-separated
// `key:dir` pairs); the backend parser at `jobs.py:_parse_sort_spec`
// validates each segment.
export interface SortKey {
  key: string;
  dir: "asc" | "desc";
}

export interface JobFilters {
  search?: string;
  status?: JobStatus | "";
  platform?: string;
  geography?: string;
  role_cluster?: string;
  // Regression finding 87: mirrors the backend `is_classified` query
  // param added alongside the configurable role-cluster catalog.
  // `true` → only jobs with a non-null/non-empty cluster; `false` →
  // only the unclassified pool (~90% of the DB). Used by the JobsPage
  // dropdown's synthetic "Unclassified" option and by the Monitoring
  // dashboard's unclassified count tile (which links here).
  is_classified?: boolean;
  // Authoritative sort state — when present, takes precedence over
  // the legacy `sort_by` / `sort_dir` pair. The API layer in
  // `lib/api.ts` serialises `sorts` into the wire-format `sort_by`
  // string (`key:dir,key:dir,...`) and drops `sort_dir`.
  sorts?: SortKey[];
  // Legacy single-sort fields. Kept so non-JobsPage callers (and any
  // pre-multi-sort code paths) continue to work unchanged. When
  // `sorts` is also set, `sorts` wins.
  sort_by?: string;
  sort_dir?: string;
  page?: number;
  page_size?: number;
}

// Regression finding 69: the bulk endpoint now accepts either a job_ids
// list (existing behavior — preserved for per-page select-all) OR a
// filter criteria object (new — for "Select all N matching"). Callers
// pick one path and the server rejects ambiguous or empty requests.
// Using a discriminated union guarantees the TS layer enforces the
// same XOR at the callsite, so a caller can't accidentally send both
// and rely on the backend to 400 it.
export interface BulkFilterCriteria {
  status?: string;
  platform?: string;
  geography_bucket?: string;
  role_cluster?: string;
  is_classified?: boolean;
  search?: string;
  company_id?: string;
}

// F69 follow-up — `action` must match the backend's `JobStatusLiteral`
// (tightened in F99: `new | under_review | accepted | rejected | hidden
// | archived`). Before this fix, the frontend sent verbs (`accept |
// reject | reset`) that didn't match the Literal, and every bulk action
// 422'd in prod with `literal_error` — silently, because the UI showed
// the loading spinner, logged the error to the console, and invalidated
// the query regardless. Aligning types here; the verb→status mapping
// lives at the JobsPage call site so button labels stay human-friendly.
export type BulkActionStatus =
  | "new"
  | "under_review"
  | "accepted"
  | "rejected"
  | "hidden"
  | "archived";

export type BulkActionPayload =
  | {
      job_ids: string[];
      action: BulkActionStatus;
      filter?: never;
    }
  | {
      filter: BulkFilterCriteria;
      action: BulkActionStatus;
      job_ids?: never;
    };

export interface ReviewPayload {
  decision: "accept" | "reject" | "skip";
  comment: string;
  tags: string[];
}

export interface ScoreBreakdownSignal {
  signal: string;
  weight: number;
  raw: number;
  weighted: number;
  detail: string;
}

export interface ScoreBreakdown {
  total: number;
  breakdown: ScoreBreakdownSignal[];
}

export interface PlatformStats {
  name: string;
  total_boards: number;
  active_boards: number;
  total_jobs: number;
  new_jobs: number;
  accepted_jobs: number;
  rejected_jobs: number;
  avg_score: number;
  last_scan: string | null;
  total_errors: number;
}

export interface PlatformBoard {
  id: string;
  company_id: string;
  company_name: string;
  platform: string;
  slug: string;
  is_active: boolean;
  last_scanned_at: string | null;
}

export interface ScanLogEntry {
  id: string;
  source: string;
  platform: string;
  started_at: string;
  completed_at: string | null;
  jobs_found: number;
  new_jobs: number;
  updated_jobs: number;
  errors: number;
  error_message: string;
  duration_ms: number;
}

export interface Resume {
  id: string;
  label: string;
  filename: string;
  file_type: "pdf" | "docx";
  word_count: number;
  status: "processing" | "ready" | "error";
  uploaded_at: string;
  text_preview?: string;
  is_active?: boolean;
}

export interface ResumeScore {
  id: string;
  job_id: string;
  job_title: string;
  company_name: string;
  role_cluster: string;
  overall_score: number;
  keyword_score: number;
  role_match_score: number;
  format_score: number;
  matched_keywords: string[];
  missing_keywords: string[];
  suggestions: string[];
  scored_at?: string;
}

export interface ResumeScoreSummary {
  resume_id: string;
  scores: ResumeScore[];
  average_score: number;
  best_score?: number;
  above_70?: number;
  top_missing_keywords?: string[];
  jobs_scored: number;
  total_filtered?: number;
  page?: number;
  page_size?: number;
  total_pages?: number;
}

export interface ResumeScoreTaskResponse {
  task_id: string;
  resume_id: string;
  status: string;
  message: string;
}

export interface ResumeScoreTaskStatus {
  status: "pending" | "progress" | "completed" | "failed";
  current?: number;
  total?: number;
  jobs_scored?: number;
  error?: string;
}

export interface ResumeCustomization {
  resume_id: string;
  job_id: string;
  job_title: string;
  target_score: number;
  customized_text: string;
  changes_made: string[];
  improvement_notes: string;
  error: boolean;
}

export interface CompanyScore {
  company_id: string;
  company_name: string;
  is_target: boolean;
  total_jobs: number;
  relevant_jobs: number;
  remote_jobs: number;
  avg_relevance_score: number;
  company_score: number;
}

export interface RoleCluster {
  id: string;
  name: string;
  display_name: string;
  is_relevant: boolean;
  is_active: boolean;
  keywords: string;
  approved_roles: string;
  keywords_list: string[];
  approved_roles_list: string[];
  sort_order: number;
  created_at: string | null;
  updated_at: string | null;
}

// Resume Persona
export interface ActiveResume {
  id: string;
  label: string;
  filename: string;
  file_type: string;
  word_count: number;
  status: string;
  uploaded_at: string;
  score_summary: {
    jobs_scored: number;
    average_score: number;
    best_score: number;
    above_70: number;
    // F96: ISO timestamp of the most recent ResumeScore row. `null`
    // means no scores yet (fresh upload, scoring task queued or
    // pending). The frontend can render "Scoring…" when null and
    // "Scored N days ago / Rescore now" when the age crosses a
    // staleness threshold (e.g. >7 days) — before this was a
    // response field, the UI had no way to distinguish a healthy
    // rescore cycle from a silent failure.
    last_scored_at?: string | null;
  };
}

// Platform Credentials
export interface PlatformCredential {
  id: string;
  resume_id: string;
  platform: string;
  email: string;
  has_password: boolean;
  profile_url: string;
  is_verified: boolean;
  last_used_at: string | null;
  created_at: string;
}

// Answer Book
export type AnswerCategory = "personal_info" | "work_auth" | "experience" | "skills" | "preferences" | "custom";

export interface AnswerBookEntry {
  id: string;
  user_id: string;
  resume_id: string | null;
  category: AnswerCategory;
  question: string;
  question_key: string;
  answer: string;
  source: string;
  is_override: boolean;
  usage_count: number;
  created_at: string;
  updated_at: string;
}

// Applications
export type ApplicationStatus = "prepared" | "submitted" | "applied" | "interview" | "offer" | "rejected" | "withdrawn";
export type ApplyMethod = "api_submit" | "manual_copy" | "career_page";
export type ApplicationSubmissionSource = "manual_prepare" | "review_queue";

export interface Application {
  id: string;
  job_id: string;
  job_title: string;
  company_name: string;
  platform: string;
  job_url: string;
  resume_id: string;
  resume_label: string;
  status: ApplicationStatus;
  apply_method: ApplyMethod;
  applied_at: string | null;
  submitted_at: string | null;
  created_at: string;
  notes: string;
  // Feature C — provenance + top-level snapshot score. Full snapshot
  // (resume text + components) is only on GET /applications/{id}.
  submission_source?: ApplicationSubmissionSource;
  applied_resume_score_overall?: number | null;
}

// Full application detail — shape of GET /applications/{id}. Adds the
// apply-time snapshot columns introduced for Feature C.
export interface ApplicationDetail {
  id: string;
  job: { id: string; title: string; company_name: string; platform: string; url: string };
  resume: { id: string; label: string };
  status: ApplicationStatus;
  apply_method: ApplyMethod;
  prepared_answers: unknown[];
  submitted_at: string | null;
  applied_at: string | null;
  platform_response: unknown;
  notes: string;
  created_at: string;
  submission_source: ApplicationSubmissionSource;
  applied_resume_text: string | null;
  applied_resume_score_snapshot: {
    overall: number;
    keyword: number;
    role_match: number;
    format: number;
  } | null;
  ai_customization_log_id: string | null;
}

export interface ApplicationStats {
  total: number;
  prepared: number;
  submitted: number;
  applied: number;
  interview: number;
  offer: number;
  rejected: number;
  withdrawn: number;
}

export interface PreparedAnswer {
  field_key: string;
  label: string;
  field_type: "text" | "textarea" | "select" | "multi_select" | "file" | "boolean";
  required: boolean;
  options: { value: string; label: string }[];
  description: string;
  answer: string;
  match_source: "base" | "override" | "unmatched";
  question_key: string;
  confidence: "high" | "medium" | "low";
}

export interface ApplyReadiness {
  resume: { ready: boolean; id?: string; label?: string };
  credentials: { ready: boolean; platform: string; email?: string };
  answer_book: { ready: boolean; count: number };
  resume_score: { available: boolean; score?: number };
  existing_application: { exists: boolean; id?: string | null; status?: string | null };
  can_apply: boolean;
}

export interface PreparedQuestion {
  field_key: string;
  label: string;
  field_type: string;
  required: boolean;
  options: string[];
  description: string;
  answer: string;
  match_source: string;
  question_key: string;
  confidence: "high" | "medium" | "low";
}

export interface JobQuestionsPreview {
  questions: PreparedQuestion[];
  coverage: {
    total: number;
    answered: number;
    high_confidence: number;
    new_entries: number;
  };
}

// Feedback
export type FeedbackCategory = "bug" | "feature_request" | "improvement" | "question";
export type FeedbackPriority = "low" | "medium" | "high" | "critical";
export type FeedbackStatus = "open" | "in_progress" | "resolved" | "closed";

export interface FeedbackAttachment {
  filename: string;
  original_name: string;
  size: number;
  content_type: string;
  uploaded_at: string;
}

export interface FeedbackUser {
  id: string;
  email: string;
  name: string;
  avatar_url: string;
}

export interface Feedback {
  id: string;
  user_id: string;
  category: FeedbackCategory;
  priority: FeedbackPriority;
  status: FeedbackStatus;
  title: string;
  description: string;
  steps_to_reproduce: string | null;
  expected_behavior: string | null;
  actual_behavior: string | null;
  use_case: string | null;
  proposed_solution: string | null;
  impact: string | null;
  screenshot_url?: string;
  attachments: FeedbackAttachment[];
  admin_notes: string | null;
  resolved_by: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  user: FeedbackUser | null;
  resolver: FeedbackUser | null;
}

export interface FeedbackCreate {
  category: FeedbackCategory;
  priority: FeedbackPriority;
  title: string;
  description: string;
  steps_to_reproduce?: string;
  expected_behavior?: string;
  actual_behavior?: string;
  use_case?: string;
  proposed_solution?: string;
  impact?: string;
  screenshot_url?: string;
}

// ── Alert Configuration ─────────────────────────────────────────────────────
export interface AlertConfig {
  id: string;
  channel: string;
  webhook_url: string;
  min_relevance_score: number;
  role_clusters: string[] | null;
  geography_filter: string | null;
  is_active: boolean;
  last_triggered_at: string | null;
  created_at: string;
}

// ── Cover Letter ────────────────────────────────────────────────────────────
export interface CoverLetterResult {
  cover_letter: string;
  key_points: string[];
  customization_notes: string;
  tone: string;
  job_title: string;
  company_name: string;
}

// ── Interview Prep ──────────────────────────────────────────────────────────
export interface InterviewQuestion {
  category: string;
  question: string;
  why_asked: string;
  suggested_answer: string;
  tips: string;
}

export interface InterviewTalkingPoint {
  topic: string;
  relevance: string;
  how_to_present: string;
}

export interface InterviewResearchItem {
  topic: string;
  why: string;
  question_to_ask: string;
}

export interface InterviewPrepResult {
  job_title: string;
  company_name: string;
  questions: InterviewQuestion[];
  talking_points: InterviewTalkingPoint[];
  company_research: InterviewResearchItem[];
  red_flags: string[];
}

// ── Intelligence ────────────────────────────────────────────────────────────
export interface SkillGapItem {
  skill: string;
  category: string;
  demand_count: number;
  demand_pct: number;
  on_resume: boolean;
  gap: boolean;
}

export interface SkillGapResponse {
  skills: SkillGapItem[];
  summary: {
    jobs_analyzed: number;
    total_skills_tracked: number;
    skills_on_resume: number;
    skills_missing: number;
    coverage_pct: number;
  };
  top_missing: SkillGapItem[];
  category_breakdown: { category: string; total: number; have: number; missing: number }[];
  has_resume: boolean;
}

export interface SalaryInsights {
  overall: { min: number; max: number; avg: number; median: number; count: number };
  by_cluster: Record<string, { min: number; max: number; avg: number; median: number; count: number }>;
  by_geography: Record<string, { min: number; max: number; avg: number; median: number; count: number }>;
  distribution: { range: string; count: number }[];
  top_paying: { min: number; max: number; mid: number; title: string; company: string; role_cluster: string; raw: string }[];
  total_with_salary: number;
  total_jobs: number;
}

export interface TimingIntelligence {
  posting_by_day: { day: string; count: number }[];
  posting_by_hour: { hour: number; count: number }[];
  freshness_distribution: { bucket: string; count: number }[];
  avg_review_hours: number;
  platform_velocity: { platform: string; total_90d: number; last_7d: number; last_30d: number }[];
  recommendations: {
    best_day: string;
    peak_posting_hours: string;
    ideal_apply_window: string;
    // F65: backend-computed metadata accompanying `ideal_apply_window`.
    // `_data_driven=true` means the text was derived from real accepted-
    // review timings and the UI can show it without a disclaimer;
    // `=false` means it's the generic heuristic fallback because sample
    // size was too small. `_sample_size` drives the "low-confidence"
    // badge when < 30 accepted reviews backed the number; the two
    // *_hours fields are surfaced as a subtitle so viewers can see the
    // actual median/p75 that produced the range.
    ideal_apply_window_data_driven?: boolean;
    ideal_apply_window_sample_size?: number;
    ideal_apply_window_median_hours?: number | null;
    ideal_apply_window_p75_hours?: number | null;
    fastest_platforms: string[];
  };
}

export interface NetworkingSuggestion {
  contact_id: string;
  name: string;
  title: string;
  company: string;
  company_id?: string;
  email: string;
  email_status: string;
  linkedin_url: string;
  is_decision_maker: boolean;
  outreach_status: string;
  relevance_reason: string;
  relevance_score?: number;
  suggested_approach: string;
  open_roles?: number;
  top_relevance_score?: number;
}

// ── VM monitoring (from /api/v1/monitoring/vm) ──────────────────────────────

export interface VmGuardrail {
  name: string;
  severity: "critical" | "warn" | "info";
  message: string;
}

export interface VmContainer {
  name: string;
  image: string;
  state: string;   // running|exited|paused|...
  status: string;  // human-readable (e.g. "Up 2 days (healthy)")
  started_at: string;
}

export interface VmContainerStat {
  name: string;
  cpu_percent: number;
  memory_percent: number;
  memory_usage: string;  // raw "123MiB / 1GiB" from docker stats
  net_io: string;        // raw "1.5MB / 2.3MB"
  block_io: string;      // raw "100kB / 0B"
  pids: number;
}

export interface VmTopProcess {
  pid: number;
  user: string;
  cpu_percent: number;
  memory_percent: number;
  command: string;
}

export interface VmMount {
  mount: string;
  total_bytes: number;
  used_bytes: number;
  available_bytes: number;
  used_percent: number;
}

export interface VmLastDeploy {
  release: string;
  previous: string | null;
  deployed_at: string;
}

export interface VmMetricsUnavailable {
  available: false;
  reason: string;
  free_tier: {
    max_ocpus: number;
    max_memory_gb: number;
    max_disk_gb: number;
    max_egress_tb_month: number;
  };
}

export interface VmMetricsAvailable {
  available: true;
  overall_status: "ok" | "warn" | "critical";
  snapshot_age_seconds: number | null;
  timestamp: string;
  host_uptime_seconds: number;
  cpu: {
    cores: number;
    load_1m: number;
    load_5m: number;
    load_15m: number;
    utilization_percent: number;
  };
  memory: {
    total_bytes: number;
    used_bytes: number;
    available_bytes: number;
    used_percent: number;
    swap_total_bytes: number;
    swap_used_bytes: number;
  };
  network: {
    interfaces: Array<{ name: string; rx_bytes: number; tx_bytes: number }>;
    total_rx_bytes: number;
    total_tx_bytes: number;
    projected_monthly_egress_tb: number | null;
    projected_egress_pct_of_free_tier: number | null;
  };
  disk: {
    mount: string;
    total_bytes: number;
    used_bytes: number;
    available_bytes: number;
    used_percent: number;
    free_tier_used_percent: number;
    inode_total?: number;
    inode_used?: number;
    inode_used_percent?: number;
    mounts?: VmMount[];
    breakdown?: {
      docker_bytes: number | null;
      backups_bytes: number | null;
      logs_bytes: number | null;
    };
  };
  cloudflared: {
    running: boolean;
    pid: number | null;
    uptime_seconds: number | null;
    connections: number | null;
  };
  keepalive: {
    last_run: string | null;
    seconds_since: number | null;
  };
  containers: VmContainer[];
  container_stats: VmContainerStat[];
  top_processes: {
    by_cpu: VmTopProcess[];
    by_memory: VmTopProcess[];
  };
  oom_kills_1h: number;
  last_deploy: VmLastDeploy | null;
  backups: {
    count: number;
    total_size_bytes: number;
    newest: string | null;
    oldest: string | null;
  };
  free_tier: {
    max_ocpus: number;
    max_memory_gb: number;
    max_disk_gb: number;
    max_egress_tb_month: number;
  };
  guardrails: VmGuardrail[];
  guardrail_counts: { critical: number; warn: number };
}

export type VmMetrics = VmMetricsAvailable | VmMetricsUnavailable;
