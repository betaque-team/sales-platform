import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Tags,
  Plus,
  ToggleLeft,
  ToggleRight,
  Trash2,
  Check,
  X,
  Star,
  Edit3,
} from "lucide-react";
import { Card } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import {
  getRoleClusters,
  createRoleCluster,
  updateRoleCluster,
  deleteRoleCluster,
} from "@/lib/api";
import type { RoleCluster } from "@/lib/types";

export function RoleClustersPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const [form, setForm] = useState({
    name: "",
    display_name: "",
    is_relevant: true,
    keywords: "",
    approved_roles: "",
  });

  const { data, isLoading } = useQuery({
    queryKey: ["role-clusters"],
    queryFn: getRoleClusters,
  });

  const createMutation = useMutation({
    mutationFn: () => createRoleCluster(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["role-clusters"] });
      setShowCreate(false);
      setForm({ name: "", display_name: "", is_relevant: true, keywords: "", approved_roles: "" });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (params: { id: string; data: Partial<RoleCluster> }) =>
      updateRoleCluster(params.id, params.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["role-clusters"] });
      setEditingId(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteRoleCluster(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["role-clusters"] });
      setConfirmDelete(null);
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="spinner h-8 w-8" />
      </div>
    );
  }

  const clusters = data?.items || [];
  const relevantNames = data?.relevant_clusters || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Role Clusters</h1>
          <p className="mt-1 text-sm text-gray-500">
            Configure which job categories count as "relevant" positions
          </p>
        </div>
        <Button variant="primary" onClick={() => setShowCreate(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Add Cluster
        </Button>
      </div>

      {/* Current relevant summary */}
      <div className="rounded-lg border border-primary-200 bg-primary-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <Star className="h-4 w-4 text-primary-600" />
          <span className="text-sm font-medium text-primary-800">
            Relevant clusters: {relevantNames.length > 0 ? relevantNames.join(", ") : "infra, security (default)"}
          </span>
        </div>
        <p className="mt-1 text-xs text-primary-600">
          Jobs in these clusters appear in "Relevant Jobs" and are scored for ATS resume matching.
        </p>
      </div>

      {/* Create form */}
      {showCreate && (
        <Card>
          <h3 className="text-base font-semibold text-gray-900 mb-4">Add New Role Cluster</h3>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate();
            }}
            className="space-y-4"
          >
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Cluster Name</label>
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="input w-full"
                  placeholder="e.g. data_engineering"
                />
                <p className="mt-1 text-xs text-gray-400">Lowercase, no spaces (used as internal ID)</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
                <input
                  type="text"
                  required
                  value={form.display_name}
                  onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                  className="input w-full"
                  placeholder="e.g. Data Engineering / Analytics"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Matching Keywords</label>
              <textarea
                value={form.keywords}
                onChange={(e) => setForm({ ...form, keywords: e.target.value })}
                className="input w-full"
                rows={2}
                placeholder="data engineer, data analyst, analytics, etl, data pipeline, airflow, spark"
              />
              <p className="mt-1 text-xs text-gray-400">Comma-separated keywords for job title matching</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Approved Role Titles</label>
              <textarea
                value={form.approved_roles}
                onChange={(e) => setForm({ ...form, approved_roles: e.target.value })}
                className="input w-full"
                rows={2}
                placeholder="Data Engineer, Analytics Engineer, Data Architect"
              />
              <p className="mt-1 text-xs text-gray-400">Comma-separated exact role titles for high-confidence matching</p>
            </div>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={form.is_relevant}
                  onChange={(e) => setForm({ ...form, is_relevant: e.target.checked })}
                  className="rounded border-gray-300"
                />
                <span className="text-sm text-gray-700">Include in "Relevant Jobs"</span>
              </label>
            </div>
            <div className="flex gap-3">
              <Button type="submit" variant="primary" loading={createMutation.isPending}>
                Create Cluster
              </Button>
              <Button type="button" variant="secondary" onClick={() => setShowCreate(false)}>
                Cancel
              </Button>
              {createMutation.isError && (
                <p className="text-sm text-red-600 self-center">{(createMutation.error as Error).message}</p>
              )}
            </div>
          </form>
        </Card>
      )}

      {/* Clusters list */}
      <div className="space-y-3">
        {clusters.map((cluster) => (
          <ClusterCard
            key={cluster.id}
            cluster={cluster}
            isEditing={editingId === cluster.id}
            confirmDelete={confirmDelete === cluster.id}
            onEdit={() => setEditingId(editingId === cluster.id ? null : cluster.id)}
            onToggleRelevant={() =>
              updateMutation.mutate({ id: cluster.id, data: { is_relevant: !cluster.is_relevant } })
            }
            onToggleActive={() =>
              updateMutation.mutate({ id: cluster.id, data: { is_active: !cluster.is_active } })
            }
            onSave={(data) => updateMutation.mutate({ id: cluster.id, data })}
            onDelete={() => {
              if (confirmDelete === cluster.id) {
                deleteMutation.mutate(cluster.id);
              } else {
                setConfirmDelete(cluster.id);
              }
            }}
            onCancelDelete={() => setConfirmDelete(null)}
          />
        ))}
      </div>

      {clusters.length === 0 && (
        <Card>
          <div className="py-8 text-center text-gray-500">
            <Tags className="mx-auto h-8 w-8 text-gray-300 mb-2" />
            <p className="text-sm">No role clusters configured yet.</p>
            <p className="text-xs text-gray-400 mt-1">
              Default "infra" and "security" clusters will be used. Add clusters to customize.
            </p>
          </div>
        </Card>
      )}
    </div>
  );
}

function ClusterCard({
  cluster,
  isEditing,
  confirmDelete,
  onEdit,
  onToggleRelevant,
  onToggleActive,
  onSave,
  onDelete,
  onCancelDelete,
}: {
  cluster: RoleCluster;
  isEditing: boolean;
  confirmDelete: boolean;
  onEdit: () => void;
  onToggleRelevant: () => void;
  onToggleActive: () => void;
  onSave: (data: Partial<RoleCluster>) => void;
  onDelete: () => void;
  onCancelDelete: () => void;
}) {
  const [editForm, setEditForm] = useState({
    display_name: cluster.display_name,
    keywords: cluster.keywords,
    approved_roles: cluster.approved_roles,
  });

  return (
    <Card className={!cluster.is_active ? "opacity-60" : ""}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h3 className="text-base font-semibold text-gray-900">{cluster.display_name}</h3>
            <Badge variant="gray">{cluster.name}</Badge>
            {cluster.is_relevant && (
              <Badge variant="primary">Relevant</Badge>
            )}
            {!cluster.is_active && (
              <Badge variant="danger">Inactive</Badge>
            )}
          </div>

          {!isEditing && (
            <div className="mt-2 space-y-1">
              {cluster.keywords_list.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  <span className="text-xs text-gray-500 mr-1">Keywords:</span>
                  {cluster.keywords_list.slice(0, 10).map((kw) => (
                    <span key={kw} className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
                      {kw}
                    </span>
                  ))}
                  {cluster.keywords_list.length > 10 && (
                    <span className="text-xs text-gray-400">+{cluster.keywords_list.length - 10} more</span>
                  )}
                </div>
              )}
              {cluster.approved_roles_list.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  <span className="text-xs text-gray-500 mr-1">Roles:</span>
                  {cluster.approved_roles_list.slice(0, 5).map((role) => (
                    <span key={role} className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">
                      {role}
                    </span>
                  ))}
                  {cluster.approved_roles_list.length > 5 && (
                    <span className="text-xs text-gray-400">+{cluster.approved_roles_list.length - 5} more</span>
                  )}
                </div>
              )}
            </div>
          )}

          {isEditing && (
            <div className="mt-3 space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Display Name</label>
                <input
                  type="text"
                  value={editForm.display_name}
                  onChange={(e) => setEditForm({ ...editForm, display_name: e.target.value })}
                  className="input w-full text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Keywords (comma-separated)</label>
                <textarea
                  value={editForm.keywords}
                  onChange={(e) => setEditForm({ ...editForm, keywords: e.target.value })}
                  className="input w-full text-sm"
                  rows={2}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Approved Roles (comma-separated)</label>
                <textarea
                  value={editForm.approved_roles}
                  onChange={(e) => setEditForm({ ...editForm, approved_roles: e.target.value })}
                  className="input w-full text-sm"
                  rows={2}
                />
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => onSave(editForm)}
                >
                  Save
                </Button>
                <Button size="sm" variant="secondary" onClick={onEdit}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-1 ml-4">
          <button
            onClick={onToggleRelevant}
            className={`rounded p-1.5 ${cluster.is_relevant ? "text-primary-600 hover:bg-primary-50" : "text-gray-400 hover:bg-gray-100"}`}
            title={cluster.is_relevant ? "Remove from relevant" : "Add to relevant"}
          >
            <Star className="h-4 w-4" fill={cluster.is_relevant ? "currentColor" : "none"} />
          </button>
          <button
            onClick={onToggleActive}
            className="rounded p-1.5 text-gray-400 hover:bg-gray-100"
            title={cluster.is_active ? "Deactivate" : "Activate"}
          >
            {cluster.is_active ? <ToggleRight className="h-4 w-4 text-green-500" /> : <ToggleLeft className="h-4 w-4" />}
          </button>
          <button
            onClick={onEdit}
            className="rounded p-1.5 text-gray-400 hover:bg-gray-100"
            title="Edit"
          >
            <Edit3 className="h-4 w-4" />
          </button>
          {confirmDelete ? (
            <div className="flex items-center gap-1">
              <button onClick={onDelete} className="rounded p-1.5 text-red-600 hover:bg-red-50" title="Confirm">
                <Check className="h-4 w-4" />
              </button>
              <button onClick={onCancelDelete} className="rounded p-1.5 text-gray-400 hover:bg-gray-100" title="Cancel">
                <X className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <button
              onClick={onDelete}
              className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"
              title="Delete"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </Card>
  );
}
