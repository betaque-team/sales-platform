import type {
  User,
  Job,
  JobDescription,
  Review,
  Company,
  CompanyDetail,
  CompanyContact,
  JobRelevantContact,
  WarmLead,
  FundingSignal,
  PipelineResponse,
  PipelineStageConfig,
  AnalyticsOverview,
  SourceDistribution,
  TrendDataPoint,
  FunnelStep,
  PaginatedResponse,
  ReviewQueueResponse,
  JobFilters,
  BulkActionPayload,
  ReviewPayload,
  ScoreBreakdown,
  PlatformStats,
  PlatformBoard,
  ScanLogEntry,
  Resume,
  ResumeScoreSummary,
  ResumeCustomization,
  CompanyScore,
  ManagedUser,
  RoleInfo,
  ScanTaskResult,
  ScanTaskStatus,
  RoleCluster,
  ActiveResume,
  PlatformCredential,
  AnswerBookEntry,
  Application,
  ApplicationStats,
  ApplyReadiness,
  JobQuestionsPreview,
  Feedback,
  FeedbackCreate,
  AlertConfig,
  CoverLetterResult,
  InterviewPrepResult,
  SkillGapResponse,
  SalaryInsights,
  TimingIntelligence,
  NetworkingSuggestion,
  AIUsage,
  UserInsightsResponse,
  ProductInsightsResponse,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_URL || "/api/v1";

// Regression finding 207: exported so consuming pages (JobDetailPage,
// CompanyDetailPage, ResumeScorePage, etc.) can narrow on `.status`
// and render error-class-specific UX instead of collapsing every
// failure into a generic "not found" state.
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// F207: de-dup concurrent 401 handling. Several TanStack Query hooks on
// the same page can fire in parallel and all resolve to 401 at roughly
// the same tick — without this guard, each one would call
// `window.location.assign(...)` and the last write wins, but we'd also
// spam the console with redirect warnings. The first 401 wins; everyone
// else gets their throw and then the page unloads.
let _redirectingToLogin = false;

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${BASE_URL}${endpoint}`;
  const config: RequestInit = {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    credentials: "include",
    ...options,
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const err = new ApiError(
      response.status,
      body.detail || body.message || `Request failed with status ${response.status}`
    );

    // F207: mid-session 401 means the JWT cookie expired (24h TTL) or
    // was invalidated server-side. Without a global redirect, every
    // detail page collapses the 401 into TanStack Query's generic
    // error, which downstream components misread as "record not
    // found" (the classic symptom: "jobs are not opening — shows Job
    // not found even for a valid id"). Hard-navigate to /login so
    // AuthProvider re-initializes cleanly.
    //
    // Guardrails:
    //   - skip on /login itself (the login page's own pre-auth
    //     /auth/me probe returns 401 for unauthenticated visitors —
    //     redirecting from there would loop);
    //   - skip when `window` is undefined (SSR / test contexts);
    //   - skip concurrent 401s (see `_redirectingToLogin`).
    if (
      response.status === 401 &&
      typeof window !== "undefined" &&
      !window.location.pathname.startsWith("/login") &&
      !_redirectingToLogin
    ) {
      _redirectingToLogin = true;
      const next = encodeURIComponent(
        window.location.pathname + window.location.search
      );
      // assign (not replace) so Back still works after sign-in.
      window.location.assign(`/login?next=${next}`);
    }

    throw err;
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    // Booleans are allowed through so `is_classified=false` serialises as
    // the literal string "false" instead of being dropped by the `value
    // !== ""` guard (the previous `Record<string, string | number | …>`
    // signature would have coerced `false` to `"false"` but only after
    // a callsite-side `String(false)`, which callers were forgetting).
    if (value !== undefined && value !== "") {
      searchParams.set(key, String(value));
    }
  }
  const qs = searchParams.toString();
  return qs ? `?${qs}` : "";
}

// Jobs
export async function getJobs(
  filters: JobFilters = {}
): Promise<PaginatedResponse<Job>> {
  // Multi-sort wire serialisation. When `sorts` is non-empty we emit
  // `sort_by=key:dir,key:dir,...` and omit `sort_dir` (the per-segment
  // direction inside `sort_by` is authoritative). When `sorts` is
  // empty/missing, fall back to the legacy `sort_by` + `sort_dir`
  // pair so non-JobsPage callers and any pre-multi-sort code paths
  // continue to work unchanged. Backend parser at
  // `backend/app/api/v1/jobs.py:_parse_sort_spec` accepts both forms.
  let sortByParam: string | undefined = filters.sort_by;
  let sortDirParam: string | undefined = filters.sort_dir;
  if (filters.sorts && filters.sorts.length > 0) {
    sortByParam = filters.sorts.map((s) => `${s.key}:${s.dir}`).join(",");
    sortDirParam = undefined;
  }
  const query = buildQuery({
    search: filters.search,
    status: filters.status,
    platform: filters.platform,
    geography: filters.geography,
    role_cluster: filters.role_cluster,
    // F87: wire the backend `is_classified` param so the JobsPage
    // dropdown's synthetic "Unclassified" option can actually filter
    // down to the (huge) unclassified pool without hand-crafting a
    // URL. Backend accepts true/false and filters role_cluster IS
    // NULL / != '' accordingly.
    is_classified: filters.is_classified,
    sort_by: sortByParam,
    sort_dir: sortDirParam,
    page: filters.page,
    page_size: filters.page_size,
  });
  return request<PaginatedResponse<Job>>(`/jobs${query}`);
}

export async function getJob(id: string): Promise<Job> {
  return request<Job>(`/jobs/${id}`);
}

export async function getJobDescription(
  jobId: string
): Promise<JobDescription> {
  return request<JobDescription>(`/jobs/${jobId}/description`);
}

export async function getJobScoreBreakdown(jobId: string): Promise<ScoreBreakdown> {
  return request<ScoreBreakdown>(`/jobs/${jobId}/score-breakdown`);
}

export async function getJobReviews(jobId: string): Promise<Review[]> {
  return request<Review[]>(`/jobs/${jobId}/reviews`);
}

export async function updateJobStatus(
  id: string,
  status: string
): Promise<Job> {
  return request<Job>(`/jobs/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export async function bulkAction(payload: BulkActionPayload): Promise<void> {
  return request<void>("/jobs/bulk-action", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// Feature A — manual job link submission. Paste an ATS URL, server
// parses the hostname, fetches the single posting, and runs it through
// the same scoring/classification pipeline the scanners use. Returns
// the upserted job with `is_new` telling the UI whether it was a brand-
// new import or an idempotent re-submission.
export interface SubmitJobLinkResult {
  id: string;
  title: string;
  company_name: string;
  platform: string;
  is_new: boolean;
  status: string;
  url: string;
}

export async function submitJobLink(url: string): Promise<SubmitJobLinkResult> {
  return request<SubmitJobLinkResult>("/jobs/submit-link", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

// Review Queue
export async function getReviewQueue(): Promise<ReviewQueueResponse> {
  return request<ReviewQueueResponse>("/jobs/review-queue");
}

export async function submitReview(
  jobId: string,
  payload: ReviewPayload
): Promise<Review> {
  return request<Review>("/reviews", {
    method: "POST",
    body: JSON.stringify({ job_id: jobId, ...payload }),
  });
}

// Feature C — Applied action from the review queue. Atomically:
//   * upserts an Application with status="applied" + snapshot columns
//   * flips Job.status to "accepted"
//   * creates/updates the company pipeline row
// Returns the Application id so the UI can link to the detail page.
export interface ApplyFromReviewPayload {
  notes?: string;
  resume_id?: string;
  customized_resume_text?: string;
  ai_customization_log_id?: string;
}

export interface ApplyFromReviewResult {
  application_id: string;
  job_id: string;
  status: "applied";
  application_is_new: boolean;
}

export async function applyFromReview(
  jobId: string,
  payload: ApplyFromReviewPayload = {},
): Promise<ApplyFromReviewResult> {
  return request<ApplyFromReviewResult>("/reviews/apply", {
    method: "POST",
    body: JSON.stringify({ job_id: jobId, ...payload }),
  });
}

export async function getJobReviewsFromApi(jobId: string): Promise<{ items: Review[] }> {
  return request<{ items: Review[] }>(`/reviews?job_id=${jobId}`);
}

// Companies
export async function getCompanies(
  params: {
    search?: string;
    page?: number;
    is_target?: boolean;
    has_contacts?: boolean;
    actively_hiring?: boolean;
    recently_funded?: boolean;
    funding_stage?: string;
    sort_by?: string;
    // F100: backend now Literal-validates `sort_dir` alongside `sort_by`.
    // Callers that don't pass it get the backend default of "desc" —
    // same behavior as every other sort-capable endpoint in the app.
    sort_dir?: "asc" | "desc";
    per_page?: number;
  } = {}
): Promise<PaginatedResponse<Company>> {
  const query = buildQuery({
    search: params.search,
    page: params.page,
    is_target: params.is_target !== undefined ? String(params.is_target) : undefined,
    has_contacts: params.has_contacts !== undefined ? String(params.has_contacts) : undefined,
    actively_hiring: params.actively_hiring !== undefined ? String(params.actively_hiring) : undefined,
    recently_funded: params.recently_funded !== undefined ? String(params.recently_funded) : undefined,
    funding_stage: params.funding_stage,
    sort_by: params.sort_by,
    sort_dir: params.sort_dir,
    per_page: params.per_page,
  });
  return request<PaginatedResponse<Company>>(`/companies${query}`);
}

export async function getCompany(id: string): Promise<Company> {
  return request<Company>(`/companies/${id}`);
}

export async function getCompanyDetail(id: string): Promise<CompanyDetail> {
  return request<CompanyDetail>(`/companies/${id}/detail`);
}

export async function triggerCompanyEnrichment(id: string): Promise<{ task_id: string; status: string }> {
  return request<{ task_id: string; status: string }>(`/companies/${id}/enrich`, { method: "POST" });
}

export async function getCompanyEnrichmentStatus(id: string): Promise<{ enrichment_status: string; enriched_at: string | null; enrichment_error: string }> {
  return request<{ enrichment_status: string; enriched_at: string | null; enrichment_error: string }>(`/companies/${id}/enrichment-status`);
}

export async function getCompanyContacts(id: string, roleCategory?: string): Promise<{ items: CompanyContact[] }> {
  const query = roleCategory ? `?role_category=${roleCategory}` : "";
  return request<{ items: CompanyContact[] }>(`/companies/${id}/contacts${query}`);
}

export async function createCompanyContact(companyId: string, data: Partial<CompanyContact>): Promise<CompanyContact> {
  return request<CompanyContact>(`/companies/${companyId}/contacts`, { method: "POST", body: JSON.stringify(data) });
}

export async function updateCompanyContact(companyId: string, contactId: string, data: Partial<CompanyContact>): Promise<CompanyContact> {
  return request<CompanyContact>(`/companies/${companyId}/contacts/${contactId}`, { method: "PATCH", body: JSON.stringify(data) });
}

export async function deleteCompanyContact(companyId: string, contactId: string): Promise<void> {
  return request<void>(`/companies/${companyId}/contacts/${contactId}`, { method: "DELETE" });
}

export async function getRelevantContacts(companyId: string, jobId: string): Promise<{ items: JobRelevantContact[] }> {
  return request<{ items: JobRelevantContact[] }>(`/companies/${companyId}/relevant-contacts/${jobId}`);
}

export async function updateContactOutreach(
  companyId: string,
  contactId: string,
  data: { outreach_status: string; outreach_note?: string }
): Promise<CompanyContact> {
  return request<CompanyContact>(`/companies/${companyId}/contacts/${contactId}/outreach`, {
    method: "PATCH",
    body: JSON.stringify({ outreach_status: data.outreach_status, outreach_note: data.outreach_note || "" }),
  });
}

export async function draftContactEmail(
  companyId: string,
  contactId: string,
  jobId?: string
): Promise<{ subject: string; body: string; generated_by: string }> {
  const query = jobId ? `?job_id=${jobId}` : "";
  return request<{ subject: string; body: string; generated_by: string }>(
    `/companies/${companyId}/contacts/${contactId}/draft-email${query}`,
    { method: "POST" }
  );
}

export async function getWarmLeads(): Promise<{ items: WarmLead[] }> {
  return request<{ items: WarmLead[] }>("/analytics/warm-leads");
}

export async function getFundingSignals(days: number = 180): Promise<{ items: FundingSignal[]; total: number }> {
  return request<{ items: FundingSignal[]; total: number }>(`/analytics/funding-signals?days=${days}`);
}

export function exportContactsUrl(params: {
  role_category?: string;
  outreach_status?: string;
  has_email?: boolean;
  is_decision_maker?: boolean;
} = {}): string {
  const qs = new URLSearchParams();
  if (params.role_category) qs.set("role_category", params.role_category);
  if (params.outreach_status) qs.set("outreach_status", params.outreach_status);
  if (params.has_email !== undefined) qs.set("has_email", String(params.has_email));
  if (params.is_decision_maker !== undefined) qs.set("is_decision_maker", String(params.is_decision_maker));
  const BASE_URL = import.meta.env.VITE_API_URL || "/api/v1";
  return `${BASE_URL}/export/contacts${qs.toString() ? "?" + qs.toString() : ""}`;
}

// Pipeline
export async function getPipeline(): Promise<PipelineResponse> {
  return request<PipelineResponse>("/pipeline");
}

export async function updatePipelineClient(
  id: string,
  stage: string,
  notes?: string
): Promise<void> {
  return request<void>(`/pipeline/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ stage, notes }),
  });
}

// Pipeline Stages
export async function getPipelineStages(): Promise<{ items: PipelineStageConfig[] }> {
  return request<{ items: PipelineStageConfig[] }>("/pipeline/stages");
}

export async function createPipelineStage(data: { key: string; label: string; color?: string; sort_order?: number }): Promise<any> {
  return request<any>("/pipeline/stages", { method: "POST", body: JSON.stringify(data) });
}

export async function updatePipelineStage(id: string, data: { label?: string; color?: string; sort_order?: number }): Promise<any> {
  return request<any>(`/pipeline/stages/${id}`, { method: "PATCH", body: JSON.stringify(data) });
}

export async function deletePipelineStage(id: string): Promise<any> {
  return request<any>(`/pipeline/stages/${id}`, { method: "DELETE" });
}

// Analytics
export async function getAnalyticsOverview(): Promise<AnalyticsOverview> {
  return request<AnalyticsOverview>("/analytics/overview");
}

export async function getAnalyticsSources(): Promise<SourceDistribution[]> {
  return request<SourceDistribution[]>("/analytics/sources");
}

export async function getAnalyticsTrends(
  days: number = 30
): Promise<TrendDataPoint[]> {
  return request<TrendDataPoint[]>(`/analytics/trends?days=${days}`);
}

export async function getAnalyticsFunnel(): Promise<{ stages: FunnelStep[] }> {
  return request<{ stages: FunnelStep[] }>("/analytics/funnel");
}

export async function getAiInsights(): Promise<{
  insights: string[];
  stats: Record<string, unknown>;
  ai_generated: boolean;
  generated_at: string;
}> {
  return request("/analytics/ai-insights");
}

// Platforms
export async function getPlatforms(): Promise<{ platforms: PlatformStats[] }> {
  return request<{ platforms: PlatformStats[] }>("/platforms");
}

// F223: backend now returns canonical pagination envelope, accepts
// page/page_size/search, and is admin-gated. Optional opts object
// preserves the existing `getPlatformBoards(platform)` call signature.
export async function getPlatformBoards(
  platform?: string,
  opts?: { page?: number; page_size?: number; search?: string }
): Promise<{ items: PlatformBoard[]; total: number; page: number; page_size: number; total_pages: number }> {
  const params = new URLSearchParams();
  if (platform) params.set("platform", platform);
  if (opts?.page) params.set("page", String(opts.page));
  if (opts?.page_size) params.set("page_size", String(opts.page_size));
  if (opts?.search) params.set("search", opts.search);
  const query = params.toString() ? `?${params.toString()}` : "";
  return request<{ items: PlatformBoard[]; total: number; page: number; page_size: number; total_pages: number }>(
    `/platforms/boards${query}`
  );
}

export async function toggleBoard(boardId: string): Promise<{ id: string; is_active: boolean }> {
  return request<{ id: string; is_active: boolean }>(`/platforms/boards/${boardId}/toggle`, { method: "POST" });
}

export async function addBoard(data: { company_name: string; platform: string; slug: string }): Promise<PlatformBoard> {
  return request<PlatformBoard>("/platforms/boards", { method: "POST", body: JSON.stringify(data) });
}

export async function deleteBoard(boardId: string): Promise<void> {
  return request<void>(`/platforms/boards/${boardId}`, { method: "DELETE" });
}

export async function triggerPlatformScan(platform: string): Promise<{ task_id: string }> {
  return request<{ task_id: string }>(`/platforms/scan/${platform}`, { method: "POST" });
}

// F217: backend now returns canonical pagination envelope
// `{items,total,page,page_size,total_pages}` and is admin-gated. The
// PlatformsPage "Scan Logs" drawer uses only the first ~30 items, so
// pass page_size=30 to avoid shipping 50 rows it slices down. If a
// future UI wants to page back, wire `page` through here.
export async function getScanLogs(
  platform?: string,
  opts?: { page?: number; page_size?: number }
): Promise<{
  items: ScanLogEntry[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}> {
  const q = buildQuery({
    platform,
    page: opts?.page,
    page_size: opts?.page_size ?? 30,
  });
  return request(`/platforms/scan-logs${q}`);
}

// Monitoring (admin only)
export async function getSystemHealth(): Promise<any> {
  return request<any>("/monitoring");
}

export async function getVmHealth(): Promise<import("./types").VmMetrics> {
  return request<import("./types").VmMetrics>("/monitoring/vm");
}

// Resume
export async function uploadResume(file: File, label?: string): Promise<Resume> {
  const formData = new FormData();
  formData.append("file", file);
  const labelParam = label ? `?label=${encodeURIComponent(label)}` : "";
  const url = `${BASE_URL}/resume/upload${labelParam}`;
  const response = await fetch(url, {
    method: "POST",
    credentials: "include",
    body: formData,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail || "Upload failed");
  }
  return response.json();
}

export async function getResumes(): Promise<{ items: Resume[]; active_resume_id: string | null }> {
  return request<{ items: Resume[]; active_resume_id: string | null }>("/resume");
}

export async function deleteResume(id: string): Promise<void> {
  return request<void>(`/resume/${id}`, { method: "DELETE" });
}

export async function scoreResume(resumeId: string): Promise<{ task_id: string; resume_id: string; status: string; message: string }> {
  return request<{ task_id: string; resume_id: string; status: string; message: string }>(`/resume/${resumeId}/score`, { method: "POST" });
}

export async function getScoreTaskStatus(resumeId: string, taskId: string): Promise<{ status: string; current?: number; total?: number; jobs_scored?: number; error?: string }> {
  return request<{ status: string; current?: number; total?: number; jobs_scored?: number; error?: string }>(`/resume/${resumeId}/score-status/${taskId}`);
}

export async function getResumeScores(
  resumeId: string,
  params: {
    page?: number;
    page_size?: number;
    role_cluster?: string;
    min_score?: number;
    max_score?: number;
    search?: string;
    sort_by?: string;
    sort_dir?: string;
  } = {}
): Promise<ResumeScoreSummary> {
  const query = buildQuery({
    page: params.page,
    page_size: params.page_size,
    role_cluster: params.role_cluster,
    min_score: params.min_score,
    max_score: params.max_score,
    search: params.search,
    sort_by: params.sort_by,
    sort_dir: params.sort_dir,
  });
  return request<ResumeScoreSummary>(`/resume/${resumeId}/scores${query}`);
}

export async function customizeResume(
  resumeId: string,
  jobId: string,
  targetScore: number,
): Promise<ResumeCustomization> {
  return request<ResumeCustomization>(`/resume/${resumeId}/customize`, {
    method: "POST",
    body: JSON.stringify({ job_id: jobId, target_score: targetScore }),
  });
}

// F236: per-feature AI usage snapshot. Single source of truth for the
// "X of Y left today" badges on the AI Tools panel + ResumeScorePage.
// Backend returns {has_api_key, reset_at_utc, features: {customize,
// cover_letter, interview_prep}: {used, limit, remaining}}.
export async function getAIUsage(): Promise<AIUsage> {
  return request<AIUsage>("/ai/usage");
}

// F237: AI Intelligence endpoints.
export async function getMyInsights(history = 0): Promise<UserInsightsResponse> {
  return request<UserInsightsResponse>(
    `/insights/me${history ? `?history=${history}` : ""}`,
  );
}

export async function getProductInsights(
  status: "pending" | "actioned" | "dismissed" | "all" = "pending",
  page = 1,
): Promise<ProductInsightsResponse> {
  return request<ProductInsightsResponse>(
    `/insights/product?status=${status}&page=${page}`,
  );
}

export async function actionProductInsight(
  insightId: string,
  status: "actioned" | "dismissed" | "duplicate",
  note?: string,
): Promise<{ id: string; actioned_status: string; actioned_at: string; actioned_note: string | null }> {
  return request(`/insights/${insightId}/action`, {
    method: "POST",
    body: JSON.stringify({ status, ...(note ? { note } : {}) }),
  });
}

export async function triggerInsightsRun(): Promise<{ task_id: string; status: string }> {
  return request("/insights/run", { method: "POST" });
}

// Company Scores
export async function getCompanyScores(): Promise<{ items: CompanyScore[] }> {
  return request<{ items: CompanyScore[] }>("/companies/scores");
}

// Auth
export async function login(email: string, password: string): Promise<{ token: string; user: User }> {
  return request<{ token: string; user: User }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function getMe(): Promise<User> {
  return request<User>("/auth/me");
}

export async function logout(): Promise<void> {
  return request<void>("/auth/logout", { method: "POST" });
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

export async function requestPasswordReset(email: string): Promise<{ ok: boolean; token?: string }> {
  return request<{ ok: boolean; token?: string }>("/auth/reset-password/request", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function confirmPasswordReset(token: string, newPassword: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/auth/reset-password/confirm", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword }),
  });
}

// User Management (admin)
export async function getUsers(): Promise<{ items: ManagedUser[]; total: number }> {
  return request<{ items: ManagedUser[]; total: number }>("/users");
}

export async function createUser(data: { email: string; name: string; password: string; role: string }): Promise<ManagedUser> {
  return request<ManagedUser>("/auth/register", { method: "POST", body: JSON.stringify(data) });
}

export async function updateUser(userId: string, data: { role?: string; is_active?: boolean }): Promise<ManagedUser> {
  return request<ManagedUser>(`/users/${userId}`, { method: "PATCH", body: JSON.stringify(data) });
}

export async function deleteUser(userId: string): Promise<void> {
  return request<void>(`/users/${userId}`, { method: "DELETE" });
}

export async function adminResetPassword(userId: string): Promise<{ ok: boolean; temp_password: string }> {
  return request<{ ok: boolean; temp_password: string }>(`/users/${userId}/reset-password`, { method: "POST" });
}

export async function getRoles(): Promise<{ roles: RoleInfo[] }> {
  return request<{ roles: RoleInfo[] }>("/users/roles");
}

// Scan Controls (admin)
export async function triggerFullScan(): Promise<ScanTaskResult> {
  return request<ScanTaskResult>("/platforms/scan/all", { method: "POST" });
}

export async function triggerPlatformScanByName(platform: string): Promise<ScanTaskResult> {
  return request<ScanTaskResult>(`/platforms/scan/${platform}`, { method: "POST" });
}

export async function triggerBoardScan(boardId: string): Promise<ScanTaskResult> {
  return request<ScanTaskResult>(`/platforms/scan/board/${boardId}`, { method: "POST" });
}

export async function getScanTaskStatus(taskId: string): Promise<ScanTaskStatus> {
  return request<ScanTaskStatus>(`/platforms/scan/status/${taskId}`);
}

export async function triggerDiscoveryScan(): Promise<ScanTaskResult> {
  return request<ScanTaskResult>("/platforms/scan/discover", { method: "POST" });
}

// Role Clusters (configurable relevant positions)
export async function getRoleClusters(): Promise<{ items: RoleCluster[]; relevant_clusters: string[] }> {
  return request<{ items: RoleCluster[]; relevant_clusters: string[] }>("/role-clusters");
}

export async function createRoleCluster(data: {
  name: string; display_name: string; is_relevant: boolean; keywords: string; approved_roles: string;
}): Promise<RoleCluster> {
  return request<RoleCluster>("/role-clusters", { method: "POST", body: JSON.stringify(data) });
}

export async function updateRoleCluster(id: string, data: Partial<RoleCluster>): Promise<RoleCluster> {
  return request<RoleCluster>(`/role-clusters/${id}`, { method: "PATCH", body: JSON.stringify(data) });
}

export async function deleteRoleCluster(id: string): Promise<void> {
  return request<void>(`/role-clusters/${id}`, { method: "DELETE" });
}

// Resume Persona
export async function switchResume(resumeId: string): Promise<{ active_resume_id: string; label: string }> {
  return request<{ active_resume_id: string; label: string }>(`/resume/switch/${resumeId}`, { method: "POST" });
}

export async function getActiveResume(): Promise<{ active_resume: ActiveResume | null }> {
  return request<{ active_resume: ActiveResume | null }>("/resume/active");
}

export async function clearActiveResume(): Promise<{ active_resume_id: null; message: string }> {
  return request<{ active_resume_id: null; message: string }>("/resume/clear-active", { method: "POST" });
}

export async function updateResumeLabel(resumeId: string, label: string): Promise<{ id: string; label: string }> {
  return request<{ id: string; label: string }>(`/resume/${resumeId}/label`, {
    method: "PATCH",
    body: JSON.stringify({ label }),
  });
}

// Platform Credentials
export async function getCredentials(resumeId: string): Promise<{ items: PlatformCredential[]; supported_platforms: string[] }> {
  return request<{ items: PlatformCredential[]; supported_platforms: string[] }>(`/credentials/${resumeId}`);
}

export async function saveCredential(resumeId: string, data: { platform: string; email: string; password?: string; profile_url?: string }): Promise<PlatformCredential> {
  return request<PlatformCredential>(`/credentials/${resumeId}`, { method: "POST", body: JSON.stringify(data) });
}

export async function deleteCredential(resumeId: string, platform: string): Promise<void> {
  return request<void>(`/credentials/${resumeId}/${platform}`, { method: "DELETE" });
}

// Answer Book
export async function getAnswerBook(category?: string): Promise<{ items: AnswerBookEntry[]; categories: string[]; active_resume_id: string | null }> {
  const query = category ? `?category=${category}` : "";
  return request<{ items: AnswerBookEntry[]; categories: string[]; active_resume_id: string | null }>(`/answer-book${query}`);
}

export async function createAnswer(data: { question: string; answer: string; category: string; resume_id?: string | null }): Promise<AnswerBookEntry> {
  return request<AnswerBookEntry>("/answer-book", { method: "POST", body: JSON.stringify(data) });
}

export async function updateAnswer(id: string, data: { answer?: string; question?: string; category?: string }): Promise<AnswerBookEntry> {
  return request<AnswerBookEntry>(`/answer-book/${id}`, { method: "PATCH", body: JSON.stringify(data) });
}

export async function deleteAnswer(id: string): Promise<void> {
  return request<void>(`/answer-book/${id}`, { method: "DELETE" });
}

export async function importAnswersFromResume(resumeId: string): Promise<{ extracted: number; added: number; fields: { question: string; answer: string }[] }> {
  return request<{ extracted: number; added: number; fields: { question: string; answer: string }[] }>(`/answer-book/import-from-resume/${resumeId}`, { method: "POST" });
}

// Apply Readiness
export async function getApplyReadiness(jobId: string): Promise<ApplyReadiness> {
  return request<ApplyReadiness>(`/applications/readiness/${jobId}`);
}

export async function syncAnswersToBook(appId: string, answers: { question_key: string; answer: string }[]): Promise<{ synced: number }> {
  return request<{ synced: number }>(`/applications/${appId}/sync-answers`, {
    method: "POST",
    body: JSON.stringify({ answers }),
  });
}

export async function getJobQuestions(jobId: string): Promise<JobQuestionsPreview> {
  return request<JobQuestionsPreview>(`/applications/questions/${jobId}`);
}

// Applications
export async function getApplicationByJob(jobId: string): Promise<any> {
  const response = await fetch(`${BASE_URL}/applications/by-job/${jobId}`, { credentials: "include" });
  if (!response.ok) return null;
  return response.json();
}

export async function prepareApplication(jobId: string): Promise<any> {
  return request<any>("/applications/prepare", { method: "POST", body: JSON.stringify({ job_id: jobId }) });
}

export async function getApplications(
  params: {
    status?: string;
    // F228 — provenance filter. Backend Literal-validates the value;
    // undefined / "" = no filter.
    submission_source?: "review_queue" | "manual_prepare";
    search?: string;
    page?: number;
    page_size?: number;
  } = {},
): Promise<PaginatedResponse<Application>> {
  const query = buildQuery(params);
  return request<PaginatedResponse<Application>>(`/applications${query}`);
}

export async function getApplication(id: string): Promise<any> {
  return request<any>(`/applications/${id}`);
}

export async function updateApplication(id: string, data: { status?: string; notes?: string; prepared_answers?: any[] }): Promise<any> {
  return request<any>(`/applications/${id}`, { method: "PATCH", body: JSON.stringify(data) });
}

export async function deleteApplication(id: string): Promise<void> {
  return request<void>(`/applications/${id}`, { method: "DELETE" });
}

export async function getApplicationStats(): Promise<ApplicationStats> {
  return request<ApplicationStats>("/applications/stats");
}

// Analytics -- application funnel
export async function getApplicationFunnel(): Promise<any> {
  return request<any>("/analytics/application-funnel");
}

export async function getApplicationsByPlatform(): Promise<any> {
  return request<any>("/analytics/applications-by-platform");
}

export async function getReviewInsights(): Promise<any> {
  return request<any>("/analytics/review-insights");
}

// Discovery -- bulk operations
export async function getDiscoveredCompanies(params: { status?: string; page?: number; per_page?: number } = {}): Promise<any> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.page) qs.set("page", String(params.page));
  if (params.per_page) qs.set("per_page", String(params.per_page));
  return request<any>(`/discovery/companies?${qs}`);
}

export async function importDiscoveredCompany(id: string): Promise<any> {
  return request<any>(`/discovery/companies/${id}/import`, { method: "POST" });
}

export async function bulkImportDiscovered(ids: string[]): Promise<any> {
  return request<any>("/discovery/companies/bulk-import", { method: "POST", body: JSON.stringify({ ids }) });
}

export async function bulkIgnoreDiscovered(ids: string[]): Promise<any> {
  return request<any>("/discovery/companies/bulk-ignore", { method: "POST", body: JSON.stringify({ ids }) });
}

export async function ignoreDiscoveredCompany(id: string): Promise<any> {
  return request<any>(`/discovery/companies/${id}`, { method: "PATCH", body: JSON.stringify({ status: "ignored" }) });
}

// Pipeline -- manual add
export async function addToPipeline(companyId: string, data: { stage?: string; priority?: number; notes?: string } = {}): Promise<any> {
  return request<any>("/pipeline", { method: "POST", body: JSON.stringify({ company_id: companyId, ...data }) });
}

// Answer book coverage
export async function getAnswerBookCoverage(): Promise<any> {
  return request<any>("/answer-book/coverage");
}

// Feedback
export async function createFeedback(data: FeedbackCreate): Promise<Feedback> {
  return request<Feedback>("/feedback", { method: "POST", body: JSON.stringify(data) });
}

export async function getFeedbackList(params: { category?: string; status?: string; priority?: string; page?: number; page_size?: number } = {}): Promise<PaginatedResponse<Feedback>> {
  const query = buildQuery(params);
  return request<PaginatedResponse<Feedback>>(`/feedback${query}`);
}

export async function getFeedback(id: string): Promise<Feedback> {
  return request<Feedback>(`/feedback/${id}`);
}

export async function updateFeedback(id: string, data: { status?: string; priority?: string; admin_notes?: string }): Promise<Feedback> {
  return request<Feedback>(`/feedback/${id}`, { method: "PATCH", body: JSON.stringify(data) });
}

export async function getFeedbackStats(): Promise<any> {
  return request<any>("/feedback/stats");
}

export async function uploadFeedbackAttachment(feedbackId: string, file: File): Promise<any> {
  const formData = new FormData();
  formData.append("file", file);
  const resp = await fetch(`/api/v1/feedback/${feedbackId}/attachments`, {
    method: "POST",
    body: formData,
    credentials: "include",
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(err.detail || "Upload failed");
  }
  return resp.json();
}

export async function deleteFeedbackAttachment(feedbackId: string, filename: string): Promise<void> {
  return request(`/feedback/${feedbackId}/attachments/${filename}`, { method: "DELETE" });
}

// ── Job Alerts ──────────────────────────────────────────────────────────────
// F220(A): backend now returns canonical pagination envelope
// `{items,total,page,page_size,total_pages}`. Callers still destructuring
// only `items` keep working; pagination-aware callers get the counts.
export async function getAlerts(
  opts?: { page?: number; page_size?: number }
): Promise<{
  items: AlertConfig[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}> {
  const q = buildQuery({ page: opts?.page, page_size: opts?.page_size });
  return request(`/alerts${q}`);
}

export async function createAlert(data: {
  webhook_url: string; min_relevance_score?: number; role_clusters?: string[] | null; geography_filter?: string | null;
}): Promise<{ id: string }> {
  return request<{ id: string }>("/alerts", { method: "POST", body: JSON.stringify(data) });
}

export async function updateAlert(id: string, data: {
  webhook_url?: string; min_relevance_score?: number; role_clusters?: string[] | null;
  geography_filter?: string | null; is_active?: boolean;
}): Promise<{ id: string }> {
  return request<{ id: string }>(`/alerts/${id}`, { method: "PUT", body: JSON.stringify(data) });
}

export async function deleteAlert(id: string): Promise<void> {
  return request<void>(`/alerts/${id}`, { method: "DELETE" });
}

export async function testAlert(id: string): Promise<{ status: string; message: string }> {
  return request<{ status: string; message: string }>(`/alerts/${id}/test`, { method: "POST" });
}

// ── Cover Letter ────────────────────────────────────────────────────────────
export async function generateCoverLetter(jobId: string, tone: string = "professional", resumeId?: string): Promise<CoverLetterResult> {
  return request<CoverLetterResult>("/cover-letter/generate", {
    method: "POST",
    body: JSON.stringify({ job_id: jobId, tone, resume_id: resumeId || null }),
  });
}

// ── Interview Prep ──────────────────────────────────────────────────────────
export async function generateInterviewPrep(jobId: string, resumeId?: string): Promise<InterviewPrepResult> {
  return request<InterviewPrepResult>("/interview-prep/generate", {
    method: "POST",
    body: JSON.stringify({ job_id: jobId, resume_id: resumeId || null }),
  });
}

// ── Intelligence ────────────────────────────────────────────────────────────
export async function getSkillGaps(roleCluster?: string): Promise<SkillGapResponse> {
  const q = roleCluster ? `?role_cluster=${roleCluster}` : "";
  return request<SkillGapResponse>(`/intelligence/skill-gaps${q}`);
}

export async function getSalaryInsights(roleCluster?: string, geography?: string): Promise<SalaryInsights> {
  const params = new URLSearchParams();
  if (roleCluster) params.set("role_cluster", roleCluster);
  if (geography) params.set("geography", geography);
  const q = params.toString() ? `?${params}` : "";
  return request<SalaryInsights>(`/intelligence/salary${q}`);
}

export async function getTimingIntelligence(): Promise<TimingIntelligence> {
  return request<TimingIntelligence>("/intelligence/timing");
}

export async function getNetworkingSuggestions(jobId?: string): Promise<{ suggestions: NetworkingSuggestion[] }> {
  const q = jobId ? `?job_id=${jobId}` : "";
  return request<{ suggestions: NetworkingSuggestion[] }>(`/intelligence/networking${q}`);
}
