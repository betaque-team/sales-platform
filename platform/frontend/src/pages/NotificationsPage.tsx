import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card } from "@/components/Card";
import { Button } from "@/components/Button";
import { Badge } from "@/components/Badge";
import { Bell, Plus, Trash2, TestTube2, Loader2, Mail, MessageSquare, CheckCircle, AlertTriangle } from "lucide-react";
import { getAlerts, createAlert, updateAlert, deleteAlert, testAlert, getSmtpStatus } from "@/lib/api";
import type { AlertConfig } from "@/lib/types";

export function NotificationsPage() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; success: boolean; message: string } | null>(null);

  // Form state
  const [formName, setFormName] = useState("");
  const [formChannel, setFormChannel] = useState<"google_chat" | "email">("google_chat");
  const [formWebhookUrl, setFormWebhookUrl] = useState("");
  const [formEmails, setFormEmails] = useState("");
  const [formMinScore, setFormMinScore] = useState(70);

  const { data: alerts, isLoading } = useQuery({
    queryKey: ["alerts"],
    queryFn: getAlerts,
  });

  const { data: smtp } = useQuery({
    queryKey: ["smtp-status"],
    queryFn: getSmtpStatus,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createAlert({
        name: formName,
        channel: formChannel,
        webhook_url: formChannel === "google_chat" ? formWebhookUrl : undefined,
        email_recipients: formChannel === "email" ? formEmails : undefined,
        min_relevance_score: formMinScore,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      resetForm();
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
    mutationFn: async (id: string) => {
      setTestingId(id);
      setTestResult(null);
      const result = await testAlert(id);
      return { id, ...result };
    },
    onSuccess: (result) => {
      setTestResult({ id: result.id, success: true, message: result.message });
    },
    onError: (_err, id) => {
      setTestResult({ id, success: false, message: "Failed to send test notification. Check configuration." });
    },
    onSettled: () => setTestingId(null),
  });

  function resetForm() {
    setShowForm(false);
    setFormName("");
    setFormChannel("google_chat");
    setFormWebhookUrl("");
    setFormEmails("");
    setFormMinScore(70);
  }

  const activeCount = alerts?.items?.filter((a) => a.is_active).length ?? 0;
  const gchatCount = alerts?.items?.filter((a) => a.channel === "google_chat").length ?? 0;
  const emailCount = alerts?.items?.filter((a) => a.channel === "email").length ?? 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Notifications</h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage group notification channels for job alerts. Notifications are sent when scans find new high-scoring jobs.
          </p>
        </div>
        <Button variant="primary" onClick={() => setShowForm(true)} disabled={showForm}>
          <Plus className="h-4 w-4 mr-1.5" />
          Add Channel
        </Button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="!p-4">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-green-100 p-2">
              <Bell className="h-5 w-5 text-green-600" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{activeCount}</p>
              <p className="text-xs text-gray-500">Active Channels</p>
            </div>
          </div>
        </Card>
        <Card className="!p-4">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-blue-100 p-2">
              <MessageSquare className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{gchatCount}</p>
              <p className="text-xs text-gray-500">Google Chat</p>
            </div>
          </div>
        </Card>
        <Card className="!p-4">
          <div className="flex items-center gap-3">
            <div className={`rounded-lg p-2 ${smtp?.configured ? "bg-purple-100" : "bg-gray-100"}`}>
              <Mail className={`h-5 w-5 ${smtp?.configured ? "text-purple-600" : "text-gray-400"}`} />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{emailCount}</p>
              <p className="text-xs text-gray-500">
                Email {!smtp?.configured && <span className="text-amber-600">(SMTP not configured)</span>}
              </p>
            </div>
          </div>
        </Card>
      </div>

      {/* SMTP status banner */}
      {smtp && !smtp.configured && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <AlertTriangle className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-800">SMTP not configured</p>
            <p className="text-xs text-amber-600 mt-1">
              To use the email channel, set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, and SMTP_FROM_EMAIL in your .env file and restart the backend.
            </p>
          </div>
        </div>
      )}

      {/* Create form */}
      {showForm && (
        <Card>
          <h3 className="text-base font-semibold text-gray-900 mb-4">New Notification Channel</h3>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate();
            }}
            className="space-y-4"
          >
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
              <input
                type="text"
                required
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                className="input w-full"
                placeholder="e.g., Sales Team Alerts"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Channel</label>
              <div className="flex gap-3">
                <label className={`flex items-center gap-2 rounded-lg border-2 px-4 py-3 cursor-pointer transition-colors ${formChannel === "google_chat" ? "border-primary-500 bg-primary-50" : "border-gray-200 hover:border-gray-300"}`}>
                  <input type="radio" name="channel" value="google_chat" checked={formChannel === "google_chat"} onChange={() => setFormChannel("google_chat")} className="sr-only" />
                  <MessageSquare className="h-5 w-5 text-blue-600" />
                  <span className="text-sm font-medium">Google Chat</span>
                </label>
                <label className={`flex items-center gap-2 rounded-lg border-2 px-4 py-3 cursor-pointer transition-colors ${formChannel === "email" ? "border-primary-500 bg-primary-50" : "border-gray-200 hover:border-gray-300"} ${!smtp?.configured ? "opacity-50" : ""}`}>
                  <input type="radio" name="channel" value="email" checked={formChannel === "email"} onChange={() => setFormChannel("email")} disabled={!smtp?.configured} className="sr-only" />
                  <Mail className="h-5 w-5 text-purple-600" />
                  <span className="text-sm font-medium">Email</span>
                  {!smtp?.configured && <span className="text-xs text-amber-600">(SMTP needed)</span>}
                </label>
              </div>
            </div>

            {formChannel === "google_chat" && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Webhook URL</label>
                <input
                  type="url"
                  required
                  value={formWebhookUrl}
                  onChange={(e) => setFormWebhookUrl(e.target.value)}
                  className="input w-full text-sm"
                  placeholder="https://chat.googleapis.com/v1/spaces/..."
                />
                <p className="text-xs text-gray-500 mt-1">
                  Create a webhook in your Google Chat space: Space settings &rarr; Integrations &rarr; Webhooks
                </p>
              </div>
            )}

            {formChannel === "email" && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Recipients (comma-separated)</label>
                <input
                  type="text"
                  required
                  value={formEmails}
                  onChange={(e) => setFormEmails(e.target.value)}
                  className="input w-full text-sm"
                  placeholder="team@company.com, lead@company.com"
                />
              </div>
            )}

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
                  value={formMinScore}
                  onChange={(e) => setFormMinScore(Number(e.target.value))}
                  className="flex-1"
                />
                <span className="text-sm font-semibold text-gray-900 w-10 text-right">{formMinScore}</span>
              </div>
              <p className="text-xs text-gray-500 mt-1">Only notify about jobs with at least this relevance score.</p>
            </div>

            {createMutation.isError && (
              <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-700">
                Failed to create notification channel. Check your inputs.
              </div>
            )}

            <div className="flex gap-2 pt-2">
              <Button type="submit" variant="primary" loading={createMutation.isPending}>
                Create Channel
              </Button>
              <Button type="button" variant="secondary" onClick={resetForm}>
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      {/* Existing channels */}
      <Card>
        <h3 className="text-base font-semibold text-gray-900 mb-4">Configured Channels</h3>

        {isLoading && <p className="text-sm text-gray-400">Loading...</p>}

        {!isLoading && !alerts?.items?.length && (
          <div className="text-center py-8">
            <Bell className="h-10 w-10 text-gray-300 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No notification channels configured yet.</p>
            <p className="text-xs text-gray-400 mt-1">Click "Add Channel" to set up Google Chat or email alerts.</p>
          </div>
        )}

        <div className="space-y-3">
          {alerts?.items?.map((a: AlertConfig) => (
            <div key={a.id} className="flex items-center gap-4 rounded-lg border border-gray-200 p-4">
              {/* Channel icon */}
              <div className={`rounded-lg p-2.5 flex-shrink-0 ${a.channel === "google_chat" ? "bg-blue-100" : "bg-purple-100"}`}>
                {a.channel === "google_chat" ? (
                  <MessageSquare className="h-5 w-5 text-blue-600" />
                ) : (
                  <Mail className="h-5 w-5 text-purple-600" />
                )}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-gray-900">{a.name}</span>
                  <Badge variant={a.is_active ? "success" : "default"}>
                    {a.is_active ? "Active" : "Paused"}
                  </Badge>
                  <Badge variant="info">
                    Score &ge; {a.min_relevance_score}
                  </Badge>
                </div>
                <div className="text-xs text-gray-500 mt-1 truncate">
                  {a.channel === "google_chat" ? a.webhook_url : a.email_recipients}
                </div>
                {a.last_triggered_at && (
                  <div className="text-xs text-gray-400 mt-0.5">
                    Last sent: {new Date(a.last_triggered_at).toLocaleString()}
                  </div>
                )}
              </div>

              {/* Test result */}
              {testResult?.id === a.id && (
                <div className={`text-xs px-2 py-1 rounded ${testResult.success ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
                  {testResult.success ? (
                    <span className="flex items-center gap-1"><CheckCircle className="h-3 w-3" /> Sent</span>
                  ) : (
                    "Failed"
                  )}
                </div>
              )}

              {/* Actions */}
              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  onClick={() => testMutation.mutate(a.id)}
                  disabled={testingId === a.id}
                  className="rounded p-2 text-gray-400 hover:bg-gray-100 hover:text-primary-600"
                  title="Send test notification"
                >
                  {testingId === a.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <TestTube2 className="h-4 w-4" />}
                </button>
                <button
                  onClick={() => toggleMutation.mutate({ id: a.id, active: !a.is_active })}
                  className={`rounded px-2.5 py-1 text-xs font-medium ${
                    a.is_active
                      ? "bg-green-100 text-green-700 hover:bg-green-200"
                      : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  }`}
                >
                  {a.is_active ? "On" : "Off"}
                </button>
                <button
                  onClick={() => {
                    if (confirm(`Delete notification channel "${a.name}"?`)) {
                      deleteMutation.mutate(a.id);
                    }
                  }}
                  className="rounded p-2 text-gray-400 hover:bg-red-50 hover:text-red-600"
                  title="Delete"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
