import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Upload,
  FileText,
  Zap,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  Sparkles,
  Trash2,
  Loader2,
  Copy,
  Search,
  SlidersHorizontal,
  ArrowUpDown,
  Edit3,
  Check,
} from "lucide-react";
import { Card } from "@/components/Card";
import { Button } from "@/components/Button";
import { Badge } from "@/components/Badge";
import { ScoreBar } from "@/components/ScoreBar";
import { Pagination } from "@/components/Pagination";
import {
  uploadResume,
  getResumes,
  deleteResume,
  scoreResume,
  getResumeScores,
  getScoreTaskStatus,
  customizeResume,
  switchResume,
  updateResumeLabel,
} from "@/lib/api";
import type { ResumeScore, ResumeCustomization } from "@/lib/types";

function ScoreBreakdownBar({ label, score, color }: { label: string; score: number; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-24 text-xs text-gray-500">{label}</span>
      <div className="flex-1 h-2 rounded-full bg-gray-100">
        <div
          className={`h-2 rounded-full ${color}`}
          style={{ width: `${Math.min(score, 100)}%` }}
        />
      </div>
      <span className="w-10 text-right text-xs font-semibold text-gray-700">{score}%</span>
    </div>
  );
}

function ScoreCard({
  score,
  onCustomize,
  isCustomizing,
}: {
  score: ResumeScore;
  onCustomize: (jobId: string) => void;
  isCustomizing: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  const scoreColor =
    score.overall_score >= 70
      ? "text-green-600"
      : score.overall_score >= 50
        ? "text-amber-600"
        : "text-red-600";

  return (
    <div className="border-b border-gray-50 last:border-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-5 py-3 hover:bg-gray-50 transition-colors text-left"
      >
        <div className="flex items-center gap-3 min-w-0 flex-1">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-gray-400 flex-shrink-0" />
          ) : (
            <ChevronRight className="h-4 w-4 text-gray-400 flex-shrink-0" />
          )}
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-gray-900">{score.job_title}</p>
            <p className="text-xs text-gray-500">
              {score.company_name}
              {score.role_cluster && (
                <span className="ml-1 text-gray-400">· {score.role_cluster}</span>
              )}
            </p>
          </div>
        </div>
        <div className="ml-4 flex items-center gap-3">
          <span className={`text-lg font-bold ${scoreColor}`}>{score.overall_score}%</span>
          <ScoreBar score={score.overall_score} />
        </div>
      </button>

      {expanded && (
        <div className="bg-gray-50 px-5 py-4 space-y-4">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <ScoreBreakdownBar label="Keywords" score={score.keyword_score} color="bg-blue-500" />
            <ScoreBreakdownBar label="Role Match" score={score.role_match_score} color="bg-purple-500" />
            <ScoreBreakdownBar label="Format" score={score.format_score} color="bg-green-500" />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <p className="text-xs font-semibold text-gray-600 mb-1">Matched Keywords</p>
              <div className="flex flex-wrap gap-1">
                {score.matched_keywords.slice(0, 15).map((kw) => (
                  <Badge key={kw} variant="success">{kw}</Badge>
                ))}
              </div>
            </div>
            <div>
              <p className="text-xs font-semibold text-gray-600 mb-1">Missing Keywords</p>
              <div className="flex flex-wrap gap-1">
                {score.missing_keywords.slice(0, 15).map((kw) => (
                  <Badge key={kw} variant="danger">{kw}</Badge>
                ))}
              </div>
            </div>
          </div>

          <div>
            <p className="text-xs font-semibold text-gray-600 mb-1">Suggestions</p>
            <ul className="space-y-1">
              {score.suggestions.map((s, i) => (
                <li key={i} className="text-xs text-gray-600 flex gap-2">
                  <span className="text-amber-500 mt-0.5">•</span>
                  {s}
                </li>
              ))}
            </ul>
          </div>

          <div className="flex justify-end">
            <Button
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                onCustomize(score.job_id);
              }}
              disabled={isCustomizing}
            >
              <Sparkles className="h-3.5 w-3.5 mr-1" />
              {isCustomizing ? "Customizing..." : "AI Customize Resume"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

const SCORE_RANGES = [
  { label: "All Scores", min: undefined, max: undefined },
  { label: "70%+", min: 70, max: undefined },
  { label: "50-69%", min: 50, max: 69.9 },
  { label: "Below 50%", min: undefined, max: 49.9 },
];

const SORT_OPTIONS = [
  { label: "Score (High to Low)", sort_by: "overall_score", sort_dir: "desc" },
  { label: "Score (Low to High)", sort_by: "overall_score", sort_dir: "asc" },
  { label: "Keyword Match", sort_by: "keyword_score", sort_dir: "desc" },
  { label: "Role Match", sort_by: "role_match_score", sort_dir: "desc" },
  { label: "Job Title A-Z", sort_by: "job_title", sort_dir: "asc" },
  { label: "Company A-Z", sort_by: "company_name", sort_dir: "asc" },
];

export function ResumeScorePage() {
  const queryClient = useQueryClient();
  const [selectedResumeId, setSelectedResumeId] = useState<string | null>(null);
  const [customization, setCustomization] = useState<ResumeCustomization | null>(null);
  const [targetScore, setTargetScore] = useState(85);
  const [customizingJobId, setCustomizingJobId] = useState<string | null>(null);
  const [scoringTaskId, setScoringTaskId] = useState<string | null>(null);
  const [scoringProgress, setScoringProgress] = useState<{ current: number; total: number } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Filters & pagination state
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [roleCluster, setRoleCluster] = useState("");
  const [scoreRange, setScoreRange] = useState(0); // index into SCORE_RANGES
  const [sortIdx, setSortIdx] = useState(0); // index into SORT_OPTIONS
  const [showFilters, setShowFilters] = useState(false);

  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearchInput = (val: string) => {
    setSearchInput(val);
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(() => {
      setSearch(val);
      setPage(1);
    }, 400);
  };

  const resetFilters = () => {
    setSearch("");
    setSearchInput("");
    setRoleCluster("");
    setScoreRange(0);
    setSortIdx(0);
    setPage(1);
  };

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Poll scoring task status
  useEffect(() => {
    if (!scoringTaskId || !selectedResumeId) return;

    const poll = async () => {
      try {
        const status = await getScoreTaskStatus(selectedResumeId, scoringTaskId);
        if (status.status === "progress") {
          setScoringProgress({ current: status.current || 0, total: status.total || 0 });
        } else if (status.status === "completed") {
          setScoringTaskId(null);
          setScoringProgress(null);
          stopPolling();
          setPage(1);
          queryClient.invalidateQueries({ queryKey: ["resume-scores"] });
        } else if (status.status === "failed") {
          setScoringTaskId(null);
          setScoringProgress(null);
          stopPolling();
        }
      } catch {
        // ignore poll errors
      }
    };

    pollRef.current = setInterval(poll, 2000);
    poll();

    return () => stopPolling();
  }, [scoringTaskId, selectedResumeId, queryClient, stopPolling]);

  const { data: resumesData } = useQuery({
    queryKey: ["resumes"],
    queryFn: getResumes,
  });

  const range = SCORE_RANGES[scoreRange];
  const sort = SORT_OPTIONS[sortIdx];

  const { data: scoresData, isLoading: scoresLoading } = useQuery({
    queryKey: ["resume-scores", selectedResumeId, page, search, roleCluster, scoreRange, sortIdx],
    queryFn: () =>
      getResumeScores(selectedResumeId!, {
        page,
        page_size: 25,
        search: search || undefined,
        role_cluster: roleCluster || undefined,
        min_score: range.min,
        max_score: range.max,
        sort_by: sort.sort_by,
        sort_dir: sort.sort_dir,
      }),
    enabled: !!selectedResumeId && !scoringTaskId,
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadResume(file),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["resumes"] });
      setSelectedResumeId(data.id);
    },
  });

  const scoreMutation = useMutation({
    mutationFn: scoreResume,
    onSuccess: (data) => {
      setScoringTaskId(data.task_id);
      setScoringProgress({ current: 0, total: 0 });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteResume,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["resumes"] });
      if (selectedResumeId) setSelectedResumeId(null);
    },
  });

  const customizeMutation = useMutation({
    mutationFn: ({ resumeId, jobId, target }: { resumeId: string; jobId: string; target: number }) =>
      customizeResume(resumeId, jobId, target),
    onSuccess: (data) => {
      setCustomization(data);
      setCustomizingJobId(null);
    },
    onError: () => {
      setCustomizingJobId(null);
    },
  });

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      uploadMutation.mutate(file);
    }
  };

  const handleCustomize = (jobId: string) => {
    if (!selectedResumeId) return;
    setCustomizingJobId(jobId);
    customizeMutation.mutate({
      resumeId: selectedResumeId,
      jobId,
      target: targetScore,
    });
  };

  const handleCopyCustomized = () => {
    if (customization?.customized_text) {
      navigator.clipboard.writeText(customization.customized_text);
    }
  };

  const [editingLabelId, setEditingLabelId] = useState<string | null>(null);
  const [labelInput, setLabelInput] = useState("");

  const switchMutation = useMutation({
    mutationFn: (resumeId: string) => switchResume(resumeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["resumes"] });
      queryClient.invalidateQueries({ queryKey: ["active-resume"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const labelMutation = useMutation({
    mutationFn: ({ id, label }: { id: string; label: string }) => updateResumeLabel(id, label),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["resumes"] });
      queryClient.invalidateQueries({ queryKey: ["active-resume"] });
      setEditingLabelId(null);
    },
  });

  const hasActiveFilters = search || roleCluster || scoreRange !== 0 || sortIdx !== 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Resume ATS Score</h1>
        <p className="mt-1 text-sm text-gray-500">
          Upload your resume and score it against relevant job openings
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left: Upload + Resume list */}
        <div className="space-y-4">
          {/* Upload */}
          <Card>
            <div className="flex items-center gap-2 mb-3">
              <Upload className="h-5 w-5 text-primary-500" />
              <h3 className="text-sm font-semibold text-gray-900">Upload Resume</h3>
            </div>
            <label className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-200 bg-gray-50 px-4 py-6 cursor-pointer hover:border-primary-300 hover:bg-primary-50 transition-colors">
              <FileText className="h-8 w-8 text-gray-400 mb-2" />
              <p className="text-sm text-gray-600">
                {uploadMutation.isPending ? "Uploading..." : "Click to upload PDF or DOCX"}
              </p>
              <p className="text-xs text-gray-400 mt-1">Max 5MB</p>
              <input
                type="file"
                className="hidden"
                accept=".pdf,.docx"
                onChange={handleFileUpload}
                disabled={uploadMutation.isPending}
              />
            </label>
            {uploadMutation.isError && (
              <p className="mt-2 text-xs text-red-600">
                {(uploadMutation.error as any)?.message || "Upload failed"}
              </p>
            )}
          </Card>

          {/* Resume list */}
          <Card padding="none">
            <div className="border-b border-gray-100 px-4 py-3">
              <h3 className="text-sm font-semibold text-gray-900">Your Resumes</h3>
            </div>
            {resumesData?.items && resumesData.items.length > 0 ? (
              <div className="divide-y divide-gray-50">
                {resumesData.items.map((r) => {
                  const isActive = r.is_active || resumesData.active_resume_id === r.id;
                  return (
                    <div
                      key={r.id}
                      className={`px-4 py-3 cursor-pointer transition-colors ${
                        selectedResumeId === r.id ? "bg-primary-50" : "hover:bg-gray-50"
                      }`}
                      onClick={() => {
                        setSelectedResumeId(r.id);
                        resetFilters();
                      }}
                    >
                      <div className="flex items-center justify-between">
                        <div className="min-w-0 flex-1">
                          {editingLabelId === r.id ? (
                            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                              <input
                                type="text"
                                value={labelInput}
                                onChange={(e) => setLabelInput(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") labelMutation.mutate({ id: r.id, label: labelInput });
                                  if (e.key === "Escape") setEditingLabelId(null);
                                }}
                                className="w-full rounded border border-gray-200 px-2 py-0.5 text-sm"
                                autoFocus
                              />
                              <button
                                onClick={() => labelMutation.mutate({ id: r.id, label: labelInput })}
                                className="p-0.5 text-green-600 hover:text-green-700"
                              >
                                <Check className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          ) : (
                            <div className="flex items-center gap-1.5">
                              <p className="truncate text-sm font-medium text-gray-900">
                                {r.label || r.filename}
                              </p>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setEditingLabelId(r.id);
                                  setLabelInput(r.label || r.filename.replace(/\.[^.]+$/, ""));
                                }}
                                className="p-0.5 text-gray-300 hover:text-gray-500"
                                title="Edit label"
                              >
                                <Edit3 className="h-3 w-3" />
                              </button>
                            </div>
                          )}
                          <p className="text-xs text-gray-500">
                            {r.label ? r.filename + " · " : ""}{r.word_count} words · {r.file_type.toUpperCase()}
                          </p>
                        </div>
                        <div className="flex items-center gap-2 ml-2">
                          {isActive ? (
                            <Badge variant="primary">Active</Badge>
                          ) : (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                switchMutation.mutate(r.id);
                              }}
                              className="rounded px-2 py-0.5 text-xs font-medium text-gray-500 border border-gray-200 hover:bg-primary-50 hover:text-primary-600 hover:border-primary-200"
                            >
                              Set Active
                            </button>
                          )}
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              // Regression finding 76: resume deletion is a
                              // destructive op that cascades to every
                              // ResumeScore row (thousands, representing
                              // ~minutes of Celery scoring time). A misclick
                              // was enough to wipe everything. Gate the call
                              // on a native confirm — cheap to add, hard to
                              // regress, and matches the confirm prompt
                              // already used by PlatformsPage board-delete.
                              if (
                                window.confirm(
                                  `Delete resume "${r.label || r.filename || "untitled"}"? This also deletes all of its job scores and cannot be undone.`,
                                )
                              ) {
                                deleteMutation.mutate(r.id);
                              }
                            }}
                            className="p-1 text-gray-400 hover:text-red-500"
                            aria-label="Delete resume"
                            title="Delete resume"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="py-8 text-center text-sm text-gray-400">
                No resumes uploaded yet
              </div>
            )}
          </Card>

          {/* Score controls */}
          {selectedResumeId && (
            <Card>
              <div className="flex items-center gap-2 mb-3">
                <Zap className="h-5 w-5 text-amber-500" />
                <h3 className="text-sm font-semibold text-gray-900">Score Settings</h3>
              </div>
              <div className="space-y-3">
                <div>
                  <label className="text-xs text-gray-500">AI Customization Target Score</label>
                  <div className="flex items-center gap-2 mt-1">
                    <input
                      type="range"
                      min={60}
                      max={95}
                      value={targetScore}
                      onChange={(e) => setTargetScore(Number(e.target.value))}
                      className="flex-1"
                    />
                    <span className="text-sm font-bold text-gray-900 w-10">{targetScore}%</span>
                  </div>
                </div>
                <Button
                  className="w-full"
                  onClick={() => scoreMutation.mutate(selectedResumeId)}
                  disabled={scoreMutation.isPending || !!scoringTaskId}
                >
                  {scoreMutation.isPending || scoringTaskId ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      {scoringProgress && scoringProgress.total > 0
                        ? `Scoring... ${scoringProgress.current}/${scoringProgress.total}`
                        : "Starting..."}
                    </>
                  ) : (
                    <>
                      <Zap className="h-4 w-4 mr-2" />
                      Score Against All Relevant Jobs
                    </>
                  )}
                </Button>
                {scoringProgress && scoringProgress.total > 0 && (
                  <div className="mt-2">
                    <div className="h-1.5 rounded-full bg-gray-100">
                      <div
                        className="h-1.5 rounded-full bg-primary-500 transition-all"
                        style={{ width: `${Math.round((scoringProgress.current / scoringProgress.total) * 100)}%` }}
                      />
                    </div>
                    <p className="text-xs text-gray-400 mt-1 text-center">
                      {Math.round((scoringProgress.current / scoringProgress.total) * 100)}% complete
                    </p>
                  </div>
                )}
              </div>
            </Card>
          )}
        </div>

        {/* Right: Score results */}
        <div className="lg:col-span-2 space-y-4">
          {scoresData && scoresData.jobs_scored > 0 ? (
            <>
              {/* Summary */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Card>
                  <p className="text-xs text-gray-500">Average Score</p>
                  <p className="text-2xl font-bold text-gray-900">{scoresData.average_score}%</p>
                </Card>
                <Card>
                  <p className="text-xs text-gray-500">Jobs Scored</p>
                  <p className="text-2xl font-bold text-gray-900">{scoresData.jobs_scored}</p>
                </Card>
                <Card>
                  <p className="text-xs text-gray-500">Best Match</p>
                  <p className="text-2xl font-bold text-green-600">
                    {scoresData.best_score ?? 0}%
                  </p>
                </Card>
                <Card>
                  <p className="text-xs text-gray-500">Above 70%</p>
                  <p className="text-2xl font-bold text-primary-600">
                    {scoresData.above_70 ?? 0}
                  </p>
                </Card>
              </div>

              {/* Top missing keywords */}
              {scoresData.top_missing_keywords && scoresData.top_missing_keywords.length > 0 && (
                <Card>
                  <p className="text-xs font-semibold text-gray-600 mb-2">
                    Most Commonly Missing Keywords
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {scoresData.top_missing_keywords.map((kw) => (
                      <Badge key={kw} variant="warning">{kw}</Badge>
                    ))}
                  </div>
                </Card>
              )}

              {/* Filters */}
              <Card>
                <div className="flex items-center gap-3 flex-wrap">
                  {/* Search */}
                  <div className="relative flex-1 min-w-[200px]">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                    <input
                      type="text"
                      value={searchInput}
                      onChange={(e) => handleSearchInput(e.target.value)}
                      placeholder="Search job title or company..."
                      className="input w-full pl-9 text-sm"
                    />
                  </div>

                  <button
                    onClick={() => setShowFilters(!showFilters)}
                    className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm transition-colors ${
                      showFilters || hasActiveFilters
                        ? "border-primary-300 bg-primary-50 text-primary-700"
                        : "border-gray-200 text-gray-600 hover:bg-gray-50"
                    }`}
                  >
                    <SlidersHorizontal className="h-4 w-4" />
                    Filters
                    {hasActiveFilters && (
                      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-primary-600 text-[10px] font-bold text-white">
                        {[search, roleCluster, scoreRange !== 0, sortIdx !== 0].filter(Boolean).length}
                      </span>
                    )}
                  </button>

                  {hasActiveFilters && (
                    <button
                      onClick={resetFilters}
                      className="text-xs text-gray-500 hover:text-gray-700 underline"
                    >
                      Clear all
                    </button>
                  )}
                </div>

                {showFilters && (
                  <div className="mt-3 grid grid-cols-1 gap-3 border-t border-gray-100 pt-3 sm:grid-cols-3">
                    {/* Role Cluster */}
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Role Cluster</label>
                      <select
                        value={roleCluster}
                        onChange={(e) => { setRoleCluster(e.target.value); setPage(1); }}
                        className="input w-full text-sm"
                      >
                        <option value="">All Clusters</option>
                        <option value="infra">Infra / Cloud / DevOps</option>
                        <option value="security">Security / Compliance</option>
                      </select>
                    </div>

                    {/* Score Range */}
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Score Range</label>
                      <select
                        value={scoreRange}
                        onChange={(e) => { setScoreRange(Number(e.target.value)); setPage(1); }}
                        className="input w-full text-sm"
                      >
                        {SCORE_RANGES.map((r, i) => (
                          <option key={i} value={i}>{r.label}</option>
                        ))}
                      </select>
                    </div>

                    {/* Sort */}
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Sort By</label>
                      <select
                        value={sortIdx}
                        onChange={(e) => { setSortIdx(Number(e.target.value)); setPage(1); }}
                        className="input w-full text-sm"
                      >
                        {SORT_OPTIONS.map((s, i) => (
                          <option key={i} value={i}>{s.label}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                )}
              </Card>

              {/* Score list */}
              <Card padding="none">
                <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
                  <h3 className="text-sm font-semibold text-gray-900">
                    ATS Scores by Job
                  </h3>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <ArrowUpDown className="h-3.5 w-3.5" />
                    {hasActiveFilters ? (
                      <span>
                        Showing {scoresData.total_filtered ?? scoresData.scores.length} of {scoresData.jobs_scored} jobs
                      </span>
                    ) : (
                      <span>{scoresData.jobs_scored} jobs scored</span>
                    )}
                  </div>
                </div>

                {scoresData.scores.length > 0 ? (
                  <div>
                    {scoresData.scores.map((score) => (
                      <ScoreCard
                        key={score.id || score.job_id}
                        score={score}
                        onCustomize={handleCustomize}
                        isCustomizing={customizingJobId === score.job_id}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="py-8 text-center text-sm text-gray-400">
                    No scores match your filters
                  </div>
                )}

                {scoresData.total_pages && scoresData.total_pages > 1 && (
                  <Pagination
                    page={scoresData.page || page}
                    totalPages={scoresData.total_pages}
                    onPageChange={setPage}
                  />
                )}
              </Card>
            </>
          ) : scoresLoading ? (
            <div className="flex items-center justify-center py-20">
              <div className="spinner h-8 w-8" />
            </div>
          ) : scoringTaskId ? (
            <Card>
              <div className="py-10 text-center">
                <Loader2 className="h-12 w-12 text-primary-400 mx-auto mb-3 animate-spin" />
                <p className="text-gray-600 font-medium">Scoring in progress...</p>
                {scoringProgress && scoringProgress.total > 0 && (
                  <p className="text-sm text-gray-400 mt-1">
                    {scoringProgress.current} of {scoringProgress.total} jobs scored
                  </p>
                )}
              </div>
            </Card>
          ) : selectedResumeId ? (
            <Card>
              <div className="py-10 text-center">
                <Zap className="h-12 w-12 text-gray-300 mx-auto mb-3" />
                <p className="text-gray-500">
                  Click "Score Against All Relevant Jobs" to analyze your resume
                </p>
              </div>
            </Card>
          ) : (
            <Card>
              <div className="py-10 text-center">
                <FileText className="h-12 w-12 text-gray-300 mx-auto mb-3" />
                <p className="text-gray-500">Upload a resume to get started</p>
              </div>
            </Card>
          )}

          {/* AI Customization result */}
          {customization && !customization.error && (
            <Card>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-5 w-5 text-purple-500" />
                  <h3 className="text-sm font-semibold text-gray-900">
                    AI-Customized Resume for: {customization.job_title}
                  </h3>
                </div>
                <Button size="sm" variant="ghost" onClick={handleCopyCustomized}>
                  <Copy className="h-3.5 w-3.5 mr-1" />
                  Copy
                </Button>
              </div>

              {customization.changes_made.length > 0 && (
                <div className="mb-3">
                  <p className="text-xs font-semibold text-gray-600 mb-1">Changes Made</p>
                  <ul className="space-y-0.5">
                    {customization.changes_made.map((c, i) => (
                      <li key={i} className="text-xs text-gray-600 flex gap-1.5">
                        <CheckCircle2 className="h-3.5 w-3.5 text-green-500 mt-0.5 flex-shrink-0" />
                        {c}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {customization.improvement_notes && (
                <div className="mb-3 rounded-lg bg-purple-50 p-3">
                  <p className="text-xs text-purple-800">{customization.improvement_notes}</p>
                </div>
              )}

              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 max-h-96 overflow-y-auto">
                <pre className="whitespace-pre-wrap text-xs text-gray-800 font-mono">
                  {customization.customized_text}
                </pre>
              </div>
            </Card>
          )}

          {customization?.error && (
            <Card>
              <div className="flex items-center gap-2 text-red-600">
                <XCircle className="h-5 w-5" />
                <p className="text-sm">{customization.improvement_notes}</p>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
