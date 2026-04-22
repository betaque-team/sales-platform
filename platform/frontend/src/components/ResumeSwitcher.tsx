import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getResumes, switchResume, getActiveResume, clearActiveResume } from "../lib/api";
import { FileText, ChevronDown, Check, Star, XCircle } from "lucide-react";

export function ResumeSwitcher() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const { data: resumeData } = useQuery({
    queryKey: ["resumes"],
    queryFn: getResumes,
  });

  const { data: activeData } = useQuery({
    queryKey: ["active-resume"],
    queryFn: getActiveResume,
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["resumes"] });
    queryClient.invalidateQueries({ queryKey: ["active-resume"] });
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["job"] });
    queryClient.invalidateQueries({ queryKey: ["analytics"] });
    queryClient.invalidateQueries({ queryKey: ["applications"] });
    queryClient.invalidateQueries({ queryKey: ["application-stats"] });
    queryClient.invalidateQueries({ queryKey: ["answer-book"] });
    queryClient.invalidateQueries({ queryKey: ["resume-scores"] });
    queryClient.invalidateQueries({ queryKey: ["credentials"] });
    queryClient.invalidateQueries({ queryKey: ["apply-readiness"] });
    // F242: Intelligence page tabs are resume-sensitive but were missing
    // from the invalidation list — the Skill Gap tab in particular computes
    // `on_resume` + `coverage_pct` against `user.active_resume_id`, so
    // switching the persona and staying on /intelligence showed stale
    // coverage until a hard refresh. Test Reviewer filed the regression
    // on 2026-04-18. Invalidating by the first key element — TanStack
    // Query does prefix matching by default — wipes every `["skill-gaps",
    // <cluster>]` entry regardless of the cluster filter the user had
    // selected. Salary/timing/networking don't read the active resume
    // today, but they live on the same page and users expect consistent
    // freshness across tabs after a persona switch (cheap extra refetch).
    queryClient.invalidateQueries({ queryKey: ["skill-gaps"] });
    queryClient.invalidateQueries({ queryKey: ["salary-insights"] });
    queryClient.invalidateQueries({ queryKey: ["timing-intelligence"] });
    queryClient.invalidateQueries({ queryKey: ["networking-suggestions"] });
  };

  const switchMutation = useMutation({
    mutationFn: (resumeId: string) => switchResume(resumeId),
    onSuccess: () => {
      invalidateAll();
      setOpen(false);
    },
  });

  const clearMutation = useMutation({
    mutationFn: clearActiveResume,
    onSuccess: () => {
      invalidateAll();
      setOpen(false);
    },
  });

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const resumes = resumeData?.items ?? [];
  const active = activeData?.active_resume;

  if (resumes.length === 0) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-400">
        <FileText className="h-4 w-4" />
        <span>No resume uploaded</span>
      </div>
    );
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 transition-colors"
      >
        <FileText className="h-4 w-4 text-primary-600" />
        <span className="max-w-[160px] truncate">
          {active ? active.label || active.filename : "Select Resume"}
        </span>
        {active && active.score_summary.jobs_scored > 0 && (
          <span className="rounded-full bg-primary-100 px-1.5 py-0.5 text-xs font-medium text-primary-700">
            {Math.round(active.score_summary.average_score)}%
          </span>
        )}
        <ChevronDown className={`h-3.5 w-3.5 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-72 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
          <div className="px-3 py-2 text-xs font-medium uppercase text-gray-500">
            Resume Persona
          </div>
          {resumes.map((r) => {
            const isActive = active?.id === r.id;
            return (
              <button
                key={r.id}
                onClick={() => !isActive && switchMutation.mutate(r.id)}
                disabled={switchMutation.isPending}
                className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-gray-50 ${
                  isActive ? "bg-primary-50" : ""
                }`}
              >
                <FileText className={`h-4 w-4 flex-shrink-0 ${isActive ? "text-primary-600" : "text-gray-400"}`} />
                <div className="min-w-0 flex-1">
                  <div className={`truncate font-medium ${isActive ? "text-primary-700" : "text-gray-700"}`}>
                    {r.label || r.filename}
                  </div>
                  <div className="text-xs text-gray-500">
                    {r.file_type.toUpperCase()} · {r.word_count} words · {r.status}
                  </div>
                </div>
                {isActive && <Check className="h-4 w-4 flex-shrink-0 text-primary-600" />}
              </button>
            );
          })}
          <div className="border-t border-gray-100 mt-1 pt-1">
            {active && (
              <button
                onClick={() => clearMutation.mutate()}
                disabled={clearMutation.isPending}
                className="flex w-full items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50"
              >
                <XCircle className="h-4 w-4" />
                Exit Persona Mode
              </button>
            )}
            <a
              href="/resume-score"
              className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50"
              onClick={() => setOpen(false)}
            >
              <Star className="h-4 w-4" />
              Manage Resumes
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
