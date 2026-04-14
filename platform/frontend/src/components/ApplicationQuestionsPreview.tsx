import { useQuery } from "@tanstack/react-query";
import { ClipboardList, CheckCircle2, AlertTriangle } from "lucide-react";
import { Card } from "@/components/Card";
import { getJobQuestions } from "@/lib/api";
import type { PreparedQuestion } from "@/lib/types";

const confidenceColors: Record<string, { dot: string; text: string; bg: string }> = {
  high: { dot: "bg-green-500", text: "text-green-700", bg: "bg-green-50" },
  medium: { dot: "bg-amber-500", text: "text-amber-700", bg: "bg-amber-50" },
  low: { dot: "bg-gray-400", text: "text-gray-500", bg: "bg-gray-50" },
};

export function ApplicationQuestionsPreview({ jobId }: { jobId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["job-questions", jobId],
    queryFn: () => getJobQuestions(jobId),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

  if (isLoading) {
    return (
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <ClipboardList className="h-4 w-4 text-primary-600" />
          <h3 className="text-base font-semibold text-gray-900">Application Questions</h3>
        </div>
        <div className="flex items-center justify-center py-6">
          <div className="spinner h-5 w-5" />
        </div>
      </Card>
    );
  }

  if (error || !data || data.questions.length === 0) {
    return null;
  }

  const { questions, coverage } = data;
  const pct = coverage.total > 0 ? Math.round((coverage.answered / coverage.total) * 100) : 0;

  return (
    <Card>
      <div className="flex items-center gap-2 mb-3">
        <ClipboardList className="h-4 w-4 text-primary-600" />
        <h3 className="text-base font-semibold text-gray-900">Application Questions</h3>
      </div>

      {/* Coverage progress */}
      <div className="mb-3">
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="text-gray-600">
            <span className="font-semibold">{coverage.answered}/{coverage.total}</span> ready
          </span>
          <span className={`font-bold ${pct >= 80 ? "text-green-600" : pct >= 50 ? "text-amber-600" : "text-gray-500"}`}>
            {pct}%
          </span>
        </div>
        <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              pct >= 80 ? "bg-green-500" : pct >= 50 ? "bg-amber-500" : "bg-gray-400"
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Stats row */}
      <div className="flex gap-3 text-[10px] text-gray-500 mb-3">
        {coverage.high_confidence > 0 && (
          <span className="flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3 text-green-500" />
            {coverage.high_confidence} high confidence
          </span>
        )}
        {coverage.new_entries > 0 && (
          <span className="flex items-center gap-1">
            <AlertTriangle className="h-3 w-3 text-amber-500" />
            {coverage.new_entries} new in answer book
          </span>
        )}
      </div>

      {/* Question list */}
      <div className="max-h-64 overflow-y-auto space-y-1.5">
        {questions.map((q: PreparedQuestion, idx: number) => {
          const colors = confidenceColors[q.confidence] || confidenceColors.low;
          const hasAnswer = q.answer && q.answer.trim() !== "";
          return (
            <div key={idx} className={`rounded border px-2.5 py-1.5 ${colors.bg} border-gray-100`}>
              <div className="flex items-start gap-2">
                <div className={`mt-1 h-2 w-2 rounded-full flex-shrink-0 ${colors.dot}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    {q.required && <span className="text-[9px] font-bold text-red-500">REQ</span>}
                    <p className="text-xs font-medium text-gray-700 truncate">{q.label}</p>
                  </div>
                  {hasAnswer ? (
                    <p className={`text-[11px] mt-0.5 truncate ${colors.text}`}>{q.answer}</p>
                  ) : (
                    <a
                      href="/answer-book"
                      className="text-[10px] font-medium text-primary-600 hover:text-primary-700"
                    >
                      Add answer
                    </a>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer link */}
      <div className="mt-3 pt-2 border-t border-gray-100 text-center">
        <a
          href="/answer-book"
          className="text-[11px] font-medium text-primary-600 hover:text-primary-700"
        >
          Manage Answer Book
        </a>
      </div>
    </Card>
  );
}
