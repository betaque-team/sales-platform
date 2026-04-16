import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronRight,
  ChevronLeft,
  Building2,
  Briefcase,
  AlertCircle,
  Plus,
  Pencil,
  Trash2,
  Check,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Card } from "@/components/Card";
import { Badge } from "@/components/Badge";
import {
  getPipeline,
  updatePipelineClient,
  getPipelineStages,
  createPipelineStage,
  updatePipelineStage,
  deletePipelineStage,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { PipelineItem } from "@/lib/types";
import { formatCount } from "@/lib/format";

const STAGE_COLORS = [
  "bg-blue-500",
  "bg-purple-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-green-500",
  "bg-red-500",
  "bg-cyan-500",
  "bg-pink-500",
  "bg-orange-500",
  "bg-teal-500",
  "bg-indigo-500",
  "bg-rose-500",
];

function getPriorityVariant(priority: number): "danger" | "warning" | "gray" {
  if (priority >= 7) return "danger";
  if (priority >= 4) return "warning";
  return "gray";
}

const velocityStyles: Record<string, { bg: string; text: string; label: string }> = {
  high: { bg: "bg-green-100", text: "text-green-700", label: "High" },
  medium: { bg: "bg-amber-100", text: "text-amber-700", label: "Medium" },
  low: { bg: "bg-gray-100", text: "text-gray-600", label: "Low" },
};

function PipelineCard({
  item,
  onMove,
  isMoving,
  isAdmin,
  stageOrder,
}: {
  item: PipelineItem;
  onMove: (id: string, stage: string) => void;
  isMoving: boolean;
  isAdmin: boolean;
  stageOrder: string[];
}) {
  const currentIdx = stageOrder.indexOf(item.stage);
  const canMoveLeft = currentIdx > 0;
  const canMoveRight = currentIdx < stageOrder.length - 1;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-gray-100">
            <Building2 className="h-4 w-4 text-gray-500" />
          </div>
          <div>
            {/* Regression finding 56: company name is now a Link so cards
                are right-clickable / middle-clickable to the company page. */}
            {item.company_id ? (
              <Link
                to={`/companies/${item.company_id}`}
                className="text-sm font-semibold text-gray-900 leading-tight hover:text-primary-600 transition-colors"
                onClick={(e) => e.stopPropagation()}
              >
                {item.company_name}
              </Link>
            ) : (
              <p className="text-sm font-semibold text-gray-900 leading-tight">
                {item.company_name}
              </p>
            )}
            {item.total_open_roles > 0 && (
              <p className="text-xs text-gray-500 mt-0.5">
                {formatCount(item.total_open_roles)} open role{item.total_open_roles !== 1 ? "s" : ""}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {item.hiring_velocity && (() => {
            const v = velocityStyles[item.hiring_velocity] || velocityStyles.low;
            return (
              <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ${v.bg} ${v.text}`}>
                {v.label}
              </span>
            );
          })()}
          <Badge variant={getPriorityVariant(item.priority)}>
            {item.priority}
          </Badge>
        </div>
      </div>

      <div className="flex items-center gap-3 text-xs text-gray-500 mb-2">
        <div className="flex items-center gap-1">
          <Briefcase className="h-3 w-3" />
          <span>{formatCount(item.accepted_jobs_count)} accepted</span>
        </div>
        <span>&middot;</span>
        <span>{formatCount(item.total_open_roles)} total</span>
      </div>

      {item.notes && (
        <p className="text-xs text-gray-600 mb-2 line-clamp-2">{item.notes}</p>
      )}

      {isAdmin && (item.applied_by_name || item.resume_label) && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-500 mb-2">
          {item.applied_by_name && (
            <span>Assigned: <span className="font-medium text-gray-700">{item.applied_by_name}</span></span>
          )}
          {item.resume_label && (
            <span>Resume: <span className="font-medium text-gray-700">{item.resume_label}</span></span>
          )}
        </div>
      )}

      {item.last_job_at && (
        <p className="text-[11px] text-gray-400 mb-2">
          Last job:{" "}
          {new Date(item.last_job_at).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
          })}
        </p>
      )}

      <div className="flex items-center justify-between border-t border-gray-100 pt-2 mt-1">
        <button
          onClick={() => canMoveLeft && onMove(item.id, stageOrder[currentIdx - 1])}
          disabled={!canMoveLeft || isMoving}
          className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-30 disabled:pointer-events-none transition-colors"
          title="Move to previous stage"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="text-xs text-gray-400">
          {new Date(item.created_at).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          })}
        </span>
        <button
          onClick={() => canMoveRight && onMove(item.id, stageOrder[currentIdx + 1])}
          disabled={!canMoveRight || isMoving}
          className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-30 disabled:pointer-events-none transition-colors"
          title="Move to next stage"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function AddStageForm({ onAdd, onCancel }: { onAdd: (data: { key: string; label: string; color: string }) => void; onCancel: () => void }) {
  const [label, setLabel] = useState("");
  const [color, setColor] = useState(STAGE_COLORS[0]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!label.trim()) return;
    const key = label.trim().toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");
    onAdd({ key, label: label.trim(), color });
  };

  return (
    <form onSubmit={handleSubmit} className="min-w-[280px] max-w-[320px] flex-shrink-0 rounded-xl border-2 border-dashed border-gray-300 p-4 space-y-3">
      <input
        type="text"
        placeholder="Stage name..."
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-gray-900 focus:outline-none focus:ring-1 focus:ring-gray-900"
        autoFocus
      />
      <div className="flex flex-wrap gap-1.5">
        {STAGE_COLORS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setColor(c)}
            className={`h-5 w-5 rounded-full ${c} ${color === c ? "ring-2 ring-offset-1 ring-gray-900" : ""}`}
          />
        ))}
      </div>
      <div className="flex gap-2">
        <button type="submit" className="flex items-center gap-1 rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800">
          <Check className="h-3 w-3" /> Add
        </button>
        <button type="button" onClick={onCancel} className="flex items-center gap-1 rounded-md bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-200">
          <X className="h-3 w-3" /> Cancel
        </button>
      </div>
    </form>
  );
}

function StageHeader({
  stage,
  count,
  isAdmin,
  onRename,
  onDelete,
}: {
  stage: { key: string; label: string; color: string };
  count: number;
  isAdmin: boolean;
  onRename: (label: string) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(stage.label);

  const handleSave = () => {
    if (label.trim() && label.trim() !== stage.label) {
      onRename(label.trim());
    }
    setEditing(false);
  };

  return (
    <div className="mb-3 flex items-center gap-2">
      <div className={`h-2.5 w-2.5 rounded-full ${stage.color}`} />
      {editing ? (
        <div className="flex items-center gap-1 flex-1">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSave(); if (e.key === "Escape") setEditing(false); }}
            className="flex-1 rounded border border-gray-300 px-2 py-0.5 text-sm font-semibold focus:border-gray-900 focus:outline-none"
            autoFocus
          />
          <button onClick={handleSave} className="p-0.5 text-green-600 hover:text-green-700"><Check className="h-3.5 w-3.5" /></button>
          <button onClick={() => setEditing(false)} className="p-0.5 text-gray-400 hover:text-gray-600"><X className="h-3.5 w-3.5" /></button>
        </div>
      ) : (
        <>
          <h3 className="text-sm font-semibold text-gray-700">{stage.label}</h3>
          {isAdmin && (
            <div className="flex items-center gap-0.5 ml-1">
              <button onClick={() => setEditing(true)} className="p-0.5 text-gray-300 hover:text-gray-600 transition-colors" title="Rename stage">
                <Pencil className="h-3 w-3" />
              </button>
              <button onClick={onDelete} className="p-0.5 text-gray-300 hover:text-red-500 transition-colors" title="Remove stage">
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          )}
        </>
      )}
      <span className="ml-auto rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
        {count}
      </span>
    </div>
  );
}

export function PipelinePage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const queryClient = useQueryClient();
  const [showAddStage, setShowAddStage] = useState(false);

  const { data: pipeline, isLoading } = useQuery({
    queryKey: ["pipeline"],
    queryFn: getPipeline,
  });

  const { data: stagesData } = useQuery({
    queryKey: ["pipeline-stages"],
    queryFn: getPipelineStages,
    enabled: isAdmin,
  });

  const moveMutation = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: string }) =>
      updatePipelineClient(id, stage),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });

  const addStageMutation = useMutation({
    mutationFn: createPipelineStage,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
      queryClient.invalidateQueries({ queryKey: ["pipeline-stages"] });
      setShowAddStage(false);
    },
  });

  const renameStageMutation = useMutation({
    mutationFn: ({ id, label }: { id: string; label: string }) =>
      updatePipelineStage(id, { label }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
      queryClient.invalidateQueries({ queryKey: ["pipeline-stages"] });
    },
  });

  const deleteStageMutation = useMutation({
    mutationFn: deletePipelineStage,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
      queryClient.invalidateQueries({ queryKey: ["pipeline-stages"] });
    },
  });

  const handleMove = (id: string, stage: string) => {
    moveMutation.mutate({ id, stage });
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="spinner h-8 w-8" />
      </div>
    );
  }

  // Use stages_config from API response (dynamic from database)
  const stagesConfig = pipeline?.stages_config || [];
  const stageOrder = stagesConfig.map((s) => s.key);
  const stages = pipeline?.items || {};

  // Build a lookup from key to stage config ID (for rename/delete)
  const stageIdMap: Record<string, string> = {};
  if (stagesData?.items) {
    for (const s of stagesData.items) {
      stageIdMap[s.key] = s.id;
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Pipeline</h1>
          <p className="mt-1 text-sm text-gray-500">
            {pipeline?.total ?? 0} companies in pipeline
          </p>
        </div>
        {isAdmin && (
          <button
            onClick={() => setShowAddStage(true)}
            className="flex items-center gap-1.5 rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 transition-colors"
          >
            <Plus className="h-4 w-4" />
            Add Stage
          </button>
        )}
      </div>

      <div className="flex gap-4 overflow-x-auto pb-4">
        {stagesConfig.map((stage) => {
          const items = stages[stage.key] || [];
          return (
            <div
              key={stage.key}
              className="flex min-w-[280px] max-w-[320px] flex-shrink-0 flex-col"
            >
              <StageHeader
                stage={stage}
                count={items.length}
                isAdmin={isAdmin}
                onRename={(label) => {
                  const id = stageIdMap[stage.key];
                  if (id) renameStageMutation.mutate({ id, label });
                }}
                onDelete={() => {
                  const id = stageIdMap[stage.key];
                  if (id && confirm(`Remove "${stage.label}" stage? Items in this stage will be preserved but hidden.`)) {
                    deleteStageMutation.mutate(id);
                  }
                }}
              />

              <div className="flex-1 space-y-2 rounded-xl bg-gray-50 p-2 min-h-[200px]">
                {items.length > 0 ? (
                  items.map((item) => (
                    <PipelineCard
                      key={item.id}
                      item={item}
                      onMove={handleMove}
                      isMoving={moveMutation.isPending}
                      isAdmin={isAdmin}
                      stageOrder={stageOrder}
                    />
                  ))
                ) : (
                  <div className="flex h-full items-center justify-center py-8">
                    <p className="text-xs text-gray-400">No companies</p>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {showAddStage && isAdmin && (
          <AddStageForm
            onAdd={(data) => {
              addStageMutation.mutate({ ...data, sort_order: stagesConfig.length });
            }}
            onCancel={() => setShowAddStage(false)}
          />
        )}
      </div>

      {pipeline && pipeline.total === 0 && stagesConfig.length > 0 && (
        <Card>
          <div className="py-10 text-center">
            <AlertCircle className="mx-auto h-10 w-10 text-gray-300" />
            <p className="mt-3 text-sm font-medium text-gray-900">
              Pipeline is empty
            </p>
            <p className="mt-1 text-sm text-gray-500">
              Accept some jobs to start building your company pipeline.
            </p>
          </div>
        </Card>
      )}
    </div>
  );
}
