import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";
import { Card } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { BackendErrorBanner } from "@/components/BackendErrorBanner";
import { User, Mail, Shield, Calendar, Lock, Check, Bell, Trash2, TestTube2, Loader2 } from "lucide-react";
import { changePassword, getAlerts, createAlert, updateAlert, deleteAlert, testAlert } from "@/lib/api";

export function SettingsPage() {
  const { user } = useAuth();
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState(false);
  const [passwordLoading, setPasswordLoading] = useState(false);

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError("");
    setPasswordSuccess(false);

    if (newPassword.length < 6) {
      setPasswordError("New password must be at least 6 characters");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("Passwords do not match");
      return;
    }

    setPasswordLoading(true);
    try {
      await changePassword(currentPassword, newPassword);
      setPasswordSuccess(true);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setShowPasswordForm(false);
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : "Failed to change password");
    } finally {
      setPasswordLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="mt-1 text-sm text-gray-500">
          Manage your account and preferences
        </p>
      </div>

      <div className="max-w-2xl">
        <Card>
          <h3 className="text-base font-semibold text-gray-900 mb-6">
            Profile
          </h3>
          <div className="flex items-start gap-6">
            {user?.picture ? (
              <img
                src={user.picture}
                alt={user.name}
                className="h-16 w-16 rounded-full ring-2 ring-gray-100"
              />
            ) : (
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary-100 text-primary-700 text-xl font-bold">
                {user?.name?.charAt(0)?.toUpperCase() || "U"}
              </div>
            )}
            <div className="flex-1 space-y-4">
              <div className="flex items-center gap-3">
                <User className="h-4 w-4 text-gray-400" />
                <div>
                  <p className="text-xs text-gray-500">Name</p>
                  <p className="text-sm font-medium text-gray-900">
                    {user?.name || "Unknown"}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Mail className="h-4 w-4 text-gray-400" />
                <div>
                  <p className="text-xs text-gray-500">Email</p>
                  <p className="text-sm font-medium text-gray-900">
                    {user?.email || "Unknown"}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Shield className="h-4 w-4 text-gray-400" />
                <div>
                  <p className="text-xs text-gray-500">Role</p>
                  <Badge
                    variant={
                      user?.role === "admin"
                        ? "primary"
                        : user?.role === "reviewer"
                        ? "success"
                        : "gray"
                    }
                  >
                    {user?.role || "viewer"}
                  </Badge>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Calendar className="h-4 w-4 text-gray-400" />
                <div>
                  <p className="text-xs text-gray-500">Member Since</p>
                  <p className="text-sm font-medium text-gray-900">
                    {user?.created_at
                      ? new Date(user.created_at).toLocaleDateString("en-US", {
                          month: "long",
                          day: "numeric",
                          year: "numeric",
                        })
                      : "Unknown"}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </Card>

        {/* Password Management — only shown for password-based accounts */}
        {user?.has_password && <Card className="mt-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Lock className="h-5 w-5 text-gray-400" />
              <h3 className="text-base font-semibold text-gray-900">Password</h3>
            </div>
            {!showPasswordForm && (
              <Button variant="secondary" size="sm" onClick={() => setShowPasswordForm(true)}>
                Change Password
              </Button>
            )}
          </div>

          {passwordSuccess && (
            <div className="mb-4 flex items-center gap-2 rounded-lg bg-green-50 border border-green-200 px-4 py-3">
              <Check className="h-4 w-4 text-green-600" />
              <p className="text-sm text-green-700">Password changed successfully</p>
            </div>
          )}

          {showPasswordForm ? (
            <form onSubmit={handleChangePassword} className="space-y-4">
              {passwordError && (
                <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                  {passwordError}
                </div>
              )}
              {/* Regression finding 43: added id/name/autocomplete/htmlFor
                  for password manager autofill and screen-reader a11y. */}
              <div>
                <label htmlFor="current-password" className="block text-sm font-medium text-gray-700 mb-1">
                  Current Password
                </label>
                <input
                  id="current-password"
                  name="current-password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="input w-full"
                />
              </div>
              <div>
                <label htmlFor="new-password" className="block text-sm font-medium text-gray-700 mb-1">
                  New Password
                </label>
                <input
                  id="new-password"
                  name="new-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={6}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="input w-full"
                  placeholder="Min 6 characters"
                />
              </div>
              <div>
                <label htmlFor="confirm-password" className="block text-sm font-medium text-gray-700 mb-1">
                  Confirm New Password
                </label>
                <input
                  id="confirm-password"
                  name="confirm-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="input w-full"
                />
              </div>
              <div className="flex gap-3">
                <Button type="submit" variant="primary" loading={passwordLoading}>
                  Update Password
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    setShowPasswordForm(false);
                    setPasswordError("");
                    setCurrentPassword("");
                    setNewPassword("");
                    setConfirmPassword("");
                  }}
                >
                  Cancel
                </Button>
              </div>
            </form>
          ) : (
            <p className="text-sm text-gray-500">
              Secure your account with a strong password.
            </p>
          )}
        </Card>}

        {!user?.has_password && (
          <Card className="mt-6">
            <div className="flex items-center gap-2 mb-2">
              <Lock className="h-5 w-5 text-gray-400" />
              <h3 className="text-base font-semibold text-gray-900">Password</h3>
            </div>
            <p className="text-sm text-gray-500">
              You signed in with Google. No password is set for this account.
            </p>
          </Card>
        )}

        {/* Job Alerts */}
        <AlertSettings />
      </div>
    </div>
  );
}

// ── Alert Settings Section ──────────────────────────────────────────────────

function AlertSettings() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [minScore, setMinScore] = useState(70);
  const [testingId, setTestingId] = useState<string | null>(null);

  // F222: destructure full query so /alerts failures surface via banner.
  const alertsQ = useQuery({
    queryKey: ["alerts"],
    // F220(A): getAlerts now accepts {page, page_size} opts — wrap in a
    // thunk so TanStack Query doesn't pass its QueryFunctionContext into
    // the opts slot (TS 2769 on direct passing).
    queryFn: () => getAlerts(),
  });
  const alerts = alertsQ.data;

  const createMutation = useMutation({
    mutationFn: () => createAlert({ webhook_url: webhookUrl, min_relevance_score: minScore }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      setShowForm(false);
      setWebhookUrl("");
      setMinScore(70);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => updateAlert(id, { is_active: active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteAlert(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const testMutation = useMutation({
    mutationFn: (id: string) => {
      setTestingId(id);
      return testAlert(id);
    },
    onSettled: () => setTestingId(null),
  });

  return (
    <Card className="mt-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Bell className="h-5 w-5 text-gray-400" />
          <h3 className="text-base font-semibold text-gray-900">Job Alerts</h3>
        </div>
        {!showForm && (
          <Button variant="secondary" size="sm" onClick={() => setShowForm(true)}>
            Add Alert
          </Button>
        )}
      </div>

      <p className="text-sm text-gray-500 mb-4">
        Get notified in Google Chat when new high-scoring jobs are found during scans.
      </p>

      {/* F222: surfaces /alerts failures. */}
      <BackendErrorBanner queries={[alertsQ]} className="mb-3" />

      {/* Existing alerts */}
      {alerts?.items?.map((a) => (
        <div key={a.id} className="flex items-center gap-3 rounded-lg border border-gray-200 p-3 mb-2">
          <div className={`h-2.5 w-2.5 rounded-full flex-shrink-0 ${a.is_active ? "bg-green-500" : "bg-gray-300"}`} />
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-gray-900 truncate">
              Google Chat &middot; Score &ge; {a.min_relevance_score}
            </div>
            <div className="text-xs text-gray-500 truncate">{a.webhook_url}</div>
            {a.last_triggered_at && (
              <div className="text-xs text-gray-400">
                Last alert: {new Date(a.last_triggered_at).toLocaleDateString()}
              </div>
            )}
          </div>
          <div className="flex gap-1">
            <button
              onClick={() => testMutation.mutate(a.id)}
              disabled={testingId === a.id}
              className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-primary-600"
              title="Send test alert"
            >
              {testingId === a.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <TestTube2 className="h-4 w-4" />}
            </button>
            <button
              onClick={() => toggleMutation.mutate({ id: a.id, active: !a.is_active })}
              className={`rounded px-2 py-1 text-xs font-medium ${
                a.is_active ? "bg-green-100 text-green-700 hover:bg-green-200" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {a.is_active ? "On" : "Off"}
            </button>
            <button
              onClick={() => deleteMutation.mutate(a.id)}
              className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"
              title="Delete"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>
      ))}

      {testMutation.isSuccess && (
        <div className="mb-3 rounded-lg bg-green-50 border border-green-200 px-3 py-2 text-xs text-green-700">
          Test alert sent! Check your Google Chat group.
        </div>
      )}
      {testMutation.isError && (
        <div className="mb-3 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-700">
          Test failed. Check your webhook URL.
        </div>
      )}

      {/* New alert form */}
      {showForm && (
        <form
          onSubmit={(e) => { e.preventDefault(); createMutation.mutate(); }}
          className="space-y-3 rounded-lg border border-primary-200 bg-primary-50 p-4 mt-3"
        >
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Google Chat Webhook URL
            </label>
            <input
              type="url"
              required
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              className="input w-full text-sm"
              placeholder="https://chat.googleapis.com/v1/spaces/..."
            />
            <p className="text-xs text-gray-500 mt-1">
              Create a webhook in your Google Chat group: Space settings &rarr; Integrations &rarr; Webhooks
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Minimum Relevance Score
            </label>
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={30}
                max={90}
                step={5}
                value={minScore}
                onChange={(e) => setMinScore(Number(e.target.value))}
                className="flex-1"
              />
              <span className="text-sm font-semibold text-gray-900 w-10 text-right">{minScore}</span>
            </div>
          </div>
          <div className="flex gap-2">
            <Button type="submit" variant="primary" size="sm" loading={createMutation.isPending}>
              Save Alert
            </Button>
            <Button type="button" variant="secondary" size="sm" onClick={() => setShowForm(false)}>
              Cancel
            </Button>
          </div>
        </form>
      )}

      {!alerts?.items?.length && !showForm && (
        <p className="text-xs text-gray-400 mt-2">No alerts configured yet.</p>
      )}
    </Card>
  );
}
