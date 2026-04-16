import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getAnswerBook, createAnswer, updateAnswer, deleteAnswer, importAnswersFromResume, getActiveResume, getAnswerBookCoverage } from "@/lib/api";
import type { AnswerCategory } from "@/lib/types";
import { BookOpen, Plus, Trash2, Edit3, Save, X, Download } from "lucide-react";

const CATEGORY_LABELS: Record<string, string> = {
  personal_info: "Personal Info",
  work_auth: "Work Authorization",
  experience: "Experience",
  skills: "Skills",
  preferences: "Preferences",
  custom: "Custom",
};

export function AnswerBookPage() {
  const [activeCategory, setActiveCategory] = useState<string>("");
  const [showOverrides, setShowOverrides] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editAnswer, setEditAnswer] = useState("");
  const [newQ, setNewQ] = useState("");
  const [newA, setNewA] = useState("");
  const [newCat, setNewCat] = useState<AnswerCategory>("personal_info");
  const queryClient = useQueryClient();

  const { data: activeResume } = useQuery({
    queryKey: ["active-resume"],
    queryFn: getActiveResume,
  });

  const { data, isLoading } = useQuery({
    queryKey: ["answer-book", activeCategory],
    queryFn: () => getAnswerBook(activeCategory || undefined),
  });

  const { data: coverage } = useQuery({
    queryKey: ["answer-book-coverage"],
    queryFn: getAnswerBookCoverage,
  });

  const createMutation = useMutation({
    mutationFn: createAnswer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["answer-book"] });
      setShowAdd(false);
      setNewQ("");
      setNewA("");
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, answer }: { id: string; answer: string }) => updateAnswer(id, { answer }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["answer-book"] });
      setEditingId(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteAnswer,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["answer-book"] }),
  });

  const importMutation = useMutation({
    mutationFn: importAnswersFromResume,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["answer-book"] });
      alert(`Extracted ${data.extracted} fields, added ${data.added} new entries`);
    },
  });

  const entries = data?.items ?? [];
  const categories = data?.categories ?? Object.keys(CATEGORY_LABELS);
  const filtered = showOverrides ? entries.filter((e) => e.is_override) : entries;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Answer Book</h1>
          <p className="text-sm text-gray-500 mt-1">
            Pre-fill answers for job applications.
            {activeResume?.active_resume && (
              <span className="ml-1 text-primary-600 font-medium">
                Active: {activeResume.active_resume.label || activeResume.active_resume.filename}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {activeResume?.active_resume && (
            <button
              onClick={() => importMutation.mutate(activeResume.active_resume!.id)}
              disabled={importMutation.isPending}
              className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              <Download className="h-4 w-4" />
              Import from Resume
            </button>
          )}
          <button
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700"
          >
            <Plus className="h-4 w-4" />
            Add Entry
          </button>
        </div>
      </div>

      {/* Coverage Panel */}
      {coverage && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-900">Coverage</h3>
            <span className="text-xs text-gray-500">{coverage.total_entries} entries total</span>
          </div>
          <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
            {Object.entries(coverage.categories).map(([cat, stats]: [string, any]) => {
              const pct = stats.count > 0 ? Math.round((stats.with_answer / stats.count) * 100) : 0;
              return (
                <div key={cat} className="text-center">
                  <div className="h-1.5 rounded-full bg-gray-100 mb-1 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${pct === 100 ? "bg-green-500" : pct > 0 ? "bg-amber-400" : "bg-gray-200"}`}
                      style={{ width: `${pct || 0}%` }}
                    />
                  </div>
                  <p className="text-[10px] font-medium text-gray-600">{CATEGORY_LABELS[cat] || cat}</p>
                  <p className="text-[10px] text-gray-400">{stats.with_answer}/{stats.count}</p>
                </div>
              );
            })}
          </div>
          {coverage.top_used.length > 0 && (
            <div className="mt-3 border-t border-gray-100 pt-2">
              <p className="text-[10px] font-medium text-gray-500 uppercase mb-1">Most Used</p>
              <div className="flex flex-wrap gap-1">
                {coverage.top_used.slice(0, 5).map((t: any) => (
                  <span key={t.question_key} className="rounded-full bg-primary-50 px-2 py-0.5 text-[10px] text-primary-700">
                    {t.question} ({t.usage_count}x)
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Category tabs + override toggle */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1 rounded-lg border border-gray-200 bg-white p-1">
          <button
            onClick={() => setActiveCategory("")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              !activeCategory ? "bg-primary-100 text-primary-700" : "text-gray-600 hover:bg-gray-50"
            }`}
          >
            All
          </button>
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeCategory === cat ? "bg-primary-100 text-primary-700" : "text-gray-600 hover:bg-gray-50"
              }`}
            >
              {CATEGORY_LABELS[cat] || cat}
            </button>
          ))}
        </div>
        {activeResume?.active_resume && (
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={showOverrides}
              onChange={(e) => setShowOverrides(e.target.checked)}
              className="rounded border-gray-300"
            />
            Show overrides only
          </label>
        )}
      </div>

      {/* Add entry form */}
      {showAdd && (
        <div className="rounded-lg border border-primary-200 bg-primary-50 p-4 space-y-3">
          {/* Regression finding 81: bare <label> elements weren't associated with
              their controls, so screen readers announced the inputs without
              context. Pair each label with htmlFor + id on the corresponding
              input/select/textarea. */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="answer-new-category" className="block text-xs font-medium text-gray-600 mb-1">
                Category
              </label>
              <select
                id="answer-new-category"
                value={newCat}
                onChange={(e) => setNewCat(e.target.value as AnswerCategory)}
                className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-sm"
              >
                {categories.map((c) => (
                  <option key={c} value={c}>{CATEGORY_LABELS[c] || c}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Scope</label>
              <p className="text-sm text-gray-500 mt-1">Base (shared across all resumes)</p>
            </div>
          </div>
          <div>
            <label htmlFor="answer-new-question" className="block text-xs font-medium text-gray-600 mb-1">
              Question
            </label>
            <input
              id="answer-new-question"
              value={newQ}
              onChange={(e) => setNewQ(e.target.value)}
              placeholder="e.g., What is your email address?"
              className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label htmlFor="answer-new-answer" className="block text-xs font-medium text-gray-600 mb-1">
              Answer
            </label>
            <textarea
              id="answer-new-answer"
              value={newA}
              onChange={(e) => setNewA(e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-sm"
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => createMutation.mutate({ question: newQ, answer: newA, category: newCat })}
              disabled={!newQ.trim() || createMutation.isPending}
              className="flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              <Save className="h-4 w-4" /> Save
            </button>
            <button
              onClick={() => setShowAdd(false)}
              className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
            >
              <X className="h-4 w-4" /> Cancel
            </button>
          </div>
        </div>
      )}

      {/* Entries list */}
      <div className="space-y-2">
        {isLoading ? (
          <div className="text-center py-8 text-gray-400">Loading...</div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-8 text-gray-400">
            <BookOpen className="h-8 w-8 mx-auto mb-2" />
            <p>No entries yet. Add questions and answers to pre-fill applications.</p>
          </div>
        ) : (
          filtered.map((entry) => (
            <div key={entry.id} className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                      {CATEGORY_LABELS[entry.category] || entry.category}
                    </span>
                    {entry.is_override && (
                      <span className="rounded bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">
                        Override
                      </span>
                    )}
                    <span className="text-xs text-gray-400">{entry.source}</span>
                    {entry.usage_count > 0 && (
                      <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-600">
                        Used {entry.usage_count}x
                      </span>
                    )}
                  </div>
                  <p className="text-sm font-medium text-gray-900">{entry.question}</p>
                  {editingId === entry.id ? (
                    <div className="mt-2 flex gap-2">
                      <textarea
                        value={editAnswer}
                        onChange={(e) => setEditAnswer(e.target.value)}
                        rows={2}
                        className="flex-1 rounded-lg border border-gray-200 px-3 py-1.5 text-sm"
                      />
                      <div className="flex flex-col gap-1">
                        <button
                          onClick={() => updateMutation.mutate({ id: entry.id, answer: editAnswer })}
                          className="rounded p-1.5 text-green-600 hover:bg-green-50"
                          aria-label="Save answer"
                          title="Save"
                        >
                          <Save className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="rounded p-1.5 text-gray-400 hover:bg-gray-100"
                          aria-label="Cancel edit"
                          title="Cancel"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p className="mt-1 text-sm text-gray-600">{entry.answer || <em className="text-gray-400">No answer</em>}</p>
                  )}
                </div>
                {editingId !== entry.id && (
                  <div className="flex gap-1">
                    <button
                      onClick={() => { setEditingId(entry.id); setEditAnswer(entry.answer); }}
                      className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                      aria-label="Edit answer"
                      title="Edit answer"
                    >
                      <Edit3 className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => {
                        if (window.confirm(`Delete this ${entry.category} answer? This cannot be undone.`)) {
                          deleteMutation.mutate(entry.id);
                        }
                      }}
                      className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"
                      aria-label="Delete answer"
                      title="Delete answer"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
