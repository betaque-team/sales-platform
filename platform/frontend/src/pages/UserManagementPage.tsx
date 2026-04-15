import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  UserPlus,
  Shield,
  Eye,
  ClipboardCheck,
  ToggleLeft,
  ToggleRight,
  Trash2,
  KeyRound,
  Copy,
  Check,
  X,
} from "lucide-react";
import { Card } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import {
  getUsers,
  createUser,
  inviteUser,
  updateUser,
  deleteUser,
  adminResetPassword,
} from "@/lib/api";
import type { ManagedUser } from "@/lib/types";

const ROLE_ICONS: Record<string, React.ElementType> = {
  admin: Shield,
  reviewer: ClipboardCheck,
  viewer: Eye,
};

const ROLE_DESCRIPTIONS: Record<string, string> = {
  admin: "Full access: manage users, trigger scans, configure platform",
  reviewer: "Review jobs, manage pipeline, score resumes, view analytics",
  viewer: "View-only access to jobs, companies, and analytics",
};

export function UserManagementPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [showInvite, setShowInvite] = useState(false);
  const [tempPassword, setTempPassword] = useState<{ userId: string; password: string } | null>(null);
  const [inviteSuccess, setInviteSuccess] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  // Form state for creating new user
  const [newUser, setNewUser] = useState({ email: "", name: "", password: "", role: "viewer" });
  const [inviteData, setInviteData] = useState({ email: "", name: "", role: "viewer" });

  const { data, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: getUsers,
  });

  const createMutation = useMutation({
    mutationFn: () => createUser(newUser),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setShowCreate(false);
      setNewUser({ email: "", name: "", password: "", role: "viewer" });
    },
  });

  const inviteMutation = useMutation({
    mutationFn: () => inviteUser(inviteData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setShowInvite(false);
      setInviteSuccess(`Invited ${inviteData.email} — they can now sign in with Google SSO.`);
      setInviteData({ email: "", name: "", role: "viewer" });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (params: { userId: string; data: { role?: string; is_active?: boolean } }) =>
      updateUser(params.userId, params.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (userId: string) => deleteUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setConfirmDelete(null);
    },
  });

  const resetMutation = useMutation({
    mutationFn: (userId: string) => adminResetPassword(userId),
    onSuccess: (data, userId) => {
      setTempPassword({ userId, password: data.temp_password });
    },
  });

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="spinner h-8 w-8" />
      </div>
    );
  }

  const users = data?.items || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">User Management</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage users, roles, and access permissions
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => { setShowCreate(true); setShowInvite(false); }}>
            <UserPlus className="mr-2 h-4 w-4" />
            Create User
          </Button>
          <Button variant="primary" onClick={() => { setShowInvite(true); setShowCreate(false); }}>
            <UserPlus className="mr-2 h-4 w-4" />
            Invite (SSO)
          </Button>
        </div>
      </div>

      {/* Role overview cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {(["admin", "reviewer", "viewer"] as const).map((role) => {
          const Icon = ROLE_ICONS[role];
          const count = users.filter((u) => u.role === role && u.is_active).length;
          return (
            <Card key={role} className="flex items-center gap-4">
              <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                role === "admin" ? "bg-primary-50" : role === "reviewer" ? "bg-green-50" : "bg-gray-100"
              }`}>
                <Icon className={`h-5 w-5 ${
                  role === "admin" ? "text-primary-600" : role === "reviewer" ? "text-green-600" : "text-gray-500"
                }`} />
              </div>
              <div>
                <p className="text-xs text-gray-500 capitalize">{role}s</p>
                <p className="text-lg font-bold text-gray-900">{count}</p>
                <p className="text-xs text-gray-400">{ROLE_DESCRIPTIONS[role]}</p>
              </div>
            </Card>
          );
        })}
      </div>

      {/* Temp password alert */}
      {tempPassword && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-amber-800">Temporary Password Generated</p>
              <p className="mt-1 text-sm text-amber-700">
                Share this with the user. They should change it on first login.
              </p>
              <div className="mt-2 flex items-center gap-2">
                <code className="rounded bg-white px-3 py-1.5 text-sm font-mono text-amber-900 border border-amber-200">
                  {tempPassword.password}
                </code>
                <button
                  onClick={() => copyToClipboard(tempPassword.password)}
                  className="rounded p-1.5 text-amber-600 hover:bg-amber-100"
                >
                  <Copy className="h-4 w-4" />
                </button>
              </div>
            </div>
            <button onClick={() => setTempPassword(null)} className="text-amber-400 hover:text-amber-600">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>
      )}

      {/* Invite success banner */}
      {inviteSuccess && (
        <div className="rounded-lg border border-green-200 bg-green-50 p-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-green-800">{inviteSuccess}</p>
            <button onClick={() => setInviteSuccess(null)} className="text-green-400 hover:text-green-600">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>
      )}

      {/* Invite user form (SSO) */}
      {showInvite && (
        <Card>
          <h3 className="text-base font-semibold text-gray-900 mb-1">Invite User (Google SSO)</h3>
          <p className="text-sm text-gray-500 mb-4">Create a stub account. The user signs in with Google using this email.</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              inviteMutation.mutate();
            }}
            className="grid grid-cols-1 gap-4 sm:grid-cols-3"
          >
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
              <input
                type="email"
                required
                value={inviteData.email}
                onChange={(e) => setInviteData({ ...inviteData, email: e.target.value })}
                className="input w-full"
                placeholder="user@company.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
              <input
                type="text"
                required
                value={inviteData.name}
                onChange={(e) => setInviteData({ ...inviteData, name: e.target.value })}
                className="input w-full"
                placeholder="Full Name"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
              <select
                value={inviteData.role}
                onChange={(e) => setInviteData({ ...inviteData, role: e.target.value })}
                className="input w-full"
              >
                <option value="viewer">Viewer</option>
                <option value="reviewer">Reviewer</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="sm:col-span-3 flex items-center gap-3">
              <Button type="submit" variant="primary" loading={inviteMutation.isPending}>
                Send Invite
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setShowInvite(false);
                  setInviteData({ email: "", name: "", role: "viewer" });
                }}
              >
                Cancel
              </Button>
              {inviteMutation.isError && (
                <p className="text-sm text-red-600">
                  {(inviteMutation.error as Error).message}
                </p>
              )}
            </div>
          </form>
        </Card>
      )}

      {/* Create user form */}
      {showCreate && (
        <Card>
          <h3 className="text-base font-semibold text-gray-900 mb-4">Create New User</h3>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate();
            }}
            className="grid grid-cols-1 gap-4 sm:grid-cols-2"
          >
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
              <input
                type="email"
                required
                value={newUser.email}
                onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
                className="input w-full"
                placeholder="user@company.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
              <input
                type="text"
                required
                value={newUser.name}
                onChange={(e) => setNewUser({ ...newUser, name: e.target.value })}
                className="input w-full"
                placeholder="Full Name"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
              <input
                type="password"
                required
                minLength={6}
                value={newUser.password}
                onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                className="input w-full"
                placeholder="Min 6 characters"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
              <select
                value={newUser.role}
                onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}
                className="input w-full"
              >
                <option value="viewer">Viewer</option>
                <option value="reviewer">Reviewer</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="sm:col-span-2 flex items-center gap-3">
              <Button type="submit" variant="primary" loading={createMutation.isPending}>
                Create User
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setShowCreate(false);
                  setNewUser({ email: "", name: "", password: "", role: "viewer" });
                }}
              >
                Cancel
              </Button>
              {createMutation.isError && (
                <p className="text-sm text-red-600">
                  {(createMutation.error as Error).message}
                </p>
              )}
            </div>
          </form>
        </Card>
      )}

      {/* Users table */}
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs text-gray-500 uppercase">
                <th className="pb-3 pr-4">User</th>
                <th className="pb-3 pr-4">Role</th>
                <th className="pb-3 pr-4">Status</th>
                <th className="pb-3 pr-4">Auth</th>
                <th className="pb-3 pr-4">Last Login</th>
                <th className="pb-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {users.map((u) => (
                <UserRow
                  key={u.id}
                  user={u}
                  confirmDelete={confirmDelete}
                  onRoleChange={(role) =>
                    updateMutation.mutate({ userId: u.id, data: { role } })
                  }
                  onToggleActive={() =>
                    updateMutation.mutate({ userId: u.id, data: { is_active: !u.is_active } })
                  }
                  onResetPassword={() => resetMutation.mutate(u.id)}
                  onDelete={() => {
                    if (confirmDelete === u.id) {
                      deleteMutation.mutate(u.id);
                    } else {
                      setConfirmDelete(u.id);
                    }
                  }}
                  onCancelDelete={() => setConfirmDelete(null)}
                />
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function UserRow({
  user,
  confirmDelete,
  onRoleChange,
  onToggleActive,
  onResetPassword,
  onDelete,
  onCancelDelete,
}: {
  user: ManagedUser;
  confirmDelete: string | null;
  onRoleChange: (role: string) => void;
  onToggleActive: () => void;
  onResetPassword: () => void;
  onDelete: () => void;
  onCancelDelete: () => void;
}) {
  return (
    <tr className={!user.is_active ? "opacity-50" : ""}>
      <td className="py-3 pr-4">
        <div className="flex items-center gap-3">
          {user.avatar_url ? (
            <img src={user.avatar_url} alt={user.name} className="h-8 w-8 rounded-full" />
          ) : (
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-100 text-primary-700 text-sm font-medium">
              {user.name?.charAt(0)?.toUpperCase() || "U"}
            </div>
          )}
          <div>
            <p className="font-medium text-gray-900">{user.name}</p>
            <p className="text-xs text-gray-500">{user.email}</p>
          </div>
        </div>
      </td>
      <td className="py-3 pr-4">
        <select
          value={user.role}
          onChange={(e) => onRoleChange(e.target.value)}
          className="rounded border border-gray-200 bg-white px-2 py-1 text-xs font-medium"
        >
          <option value="admin">Admin</option>
          <option value="reviewer">Reviewer</option>
          <option value="viewer">Viewer</option>
        </select>
      </td>
      <td className="py-3 pr-4">
        <Badge variant={user.is_active ? "success" : "danger"}>
          {user.is_active ? "Active" : "Inactive"}
        </Badge>
      </td>
      <td className="py-3 pr-4">
        <div className="flex gap-1">
          {user.has_password && (
            <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">Password</span>
          )}
          {user.has_google && (
            <span className="rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-700">Google</span>
          )}
          {!user.has_password && !user.has_google && (
            <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">Invited</span>
          )}
        </div>
      </td>
      <td className="py-3 pr-4 text-xs text-gray-500">
        {user.last_login_at
          ? new Date(user.last_login_at).toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })
          : "Never"}
      </td>
      <td className="py-3 text-right">
        <div className="flex items-center justify-end gap-1">
          <button
            onClick={onToggleActive}
            className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            title={user.is_active ? "Deactivate" : "Activate"}
          >
            {user.is_active ? <ToggleRight className="h-4 w-4 text-green-500" /> : <ToggleLeft className="h-4 w-4" />}
          </button>
          <button
            onClick={onResetPassword}
            className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            title="Reset Password"
          >
            <KeyRound className="h-4 w-4" />
          </button>
          {confirmDelete === user.id ? (
            <div className="flex items-center gap-1">
              <button
                onClick={onDelete}
                className="rounded p-1.5 text-red-600 hover:bg-red-50"
                title="Confirm Delete"
              >
                <Check className="h-4 w-4" />
              </button>
              <button
                onClick={onCancelDelete}
                className="rounded p-1.5 text-gray-400 hover:bg-gray-100"
                title="Cancel"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <button
              onClick={onDelete}
              className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"
              title="Delete User"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
