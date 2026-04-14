import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getCredentials, saveCredential, deleteCredential, getActiveResume } from "@/lib/api";
import type { PlatformCredential } from "@/lib/types";
import { KeyRound, Plus, Trash2, Save, X, Check, AlertTriangle, Eye, EyeOff } from "lucide-react";

const PLATFORM_LABELS: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  workable: "Workable",
  smartrecruiters: "SmartRecruiters",
  recruitee: "Recruitee",
  bamboohr: "BambooHR",
  jobvite: "Jobvite",
  wellfound: "Wellfound",
  himalayas: "Himalayas",
};

export function CredentialsPage() {
  const queryClient = useQueryClient();
  const [editingPlatform, setEditingPlatform] = useState<string | null>(null);
  const [formEmail, setFormEmail] = useState("");
  const [formPassword, setFormPassword] = useState("");
  const [formProfileUrl, setFormProfileUrl] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const { data: activeResume } = useQuery({
    queryKey: ["active-resume"],
    queryFn: getActiveResume,
  });

  const resumeId = activeResume?.active_resume?.id;

  const { data, isLoading } = useQuery({
    queryKey: ["credentials", resumeId],
    queryFn: () => getCredentials(resumeId!),
    enabled: !!resumeId,
  });

  const saveMutation = useMutation({
    mutationFn: (args: { platform: string; email: string; password: string; profile_url: string }) =>
      saveCredential(resumeId!, args),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      setEditingPlatform(null);
      resetForm();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (platform: string) => deleteCredential(resumeId!, platform),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
    },
  });

  const resetForm = () => {
    setFormEmail("");
    setFormPassword("");
    setFormProfileUrl("");
    setShowPassword(false);
  };

  const startEdit = (platform: string, existing?: PlatformCredential) => {
    setEditingPlatform(platform);
    setFormEmail(existing?.email || "");
    setFormPassword("");
    setFormProfileUrl(existing?.profile_url || "");
    setShowPassword(false);
  };

  const handleSave = (platform: string) => {
    if (!formEmail.trim()) return;
    saveMutation.mutate({
      platform,
      email: formEmail.trim(),
      password: formPassword,
      profile_url: formProfileUrl.trim(),
    });
  };

  const credByPlatform: Record<string, PlatformCredential> = {};
  for (const c of data?.items || []) {
    credByPlatform[c.platform] = c;
  }

  const platforms = data?.supported_platforms || Object.keys(PLATFORM_LABELS);

  if (!activeResume?.active_resume) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Platform Credentials</h1>
          <p className="text-sm text-gray-500 mt-1">Manage your ATS platform login credentials per resume persona.</p>
        </div>
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-center">
          <AlertTriangle className="h-8 w-8 text-amber-500 mx-auto mb-3" />
          <p className="text-sm font-medium text-amber-800">No active resume selected</p>
          <p className="text-xs text-amber-600 mt-1">
            Use the resume switcher in the header to select a persona before managing credentials.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Platform Credentials</h1>
        <p className="text-sm text-gray-500 mt-1">
          Manage login credentials for each ATS platform.
          <span className="ml-1 text-primary-600 font-medium">
            Active: {activeResume.active_resume.label || activeResume.active_resume.filename}
          </span>
        </p>
      </div>

      {isLoading ? (
        <div className="text-center py-8 text-gray-400">Loading...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {platforms.map((platform) => {
            const cred = credByPlatform[platform];
            const isEditing = editingPlatform === platform;

            return (
              <div
                key={platform}
                className={`rounded-lg border bg-white p-4 ${
                  cred ? "border-green-200" : "border-gray-200"
                }`}
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <KeyRound className={`h-4 w-4 ${cred ? "text-green-600" : "text-gray-400"}`} />
                    <span className="font-medium text-gray-900">
                      {PLATFORM_LABELS[platform] || platform}
                    </span>
                  </div>
                  {cred && !isEditing && (
                    <span className="flex items-center gap-1 text-xs text-green-600">
                      <Check className="h-3.5 w-3.5" />
                      Configured
                    </span>
                  )}
                  {!cred && !isEditing && (
                    <span className="text-xs text-gray-400">Not configured</span>
                  )}
                </div>

                {isEditing ? (
                  <div className="space-y-2">
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-0.5">Email *</label>
                      <input
                        type="email"
                        value={formEmail}
                        onChange={(e) => setFormEmail(e.target.value)}
                        placeholder="your@email.com"
                        className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-0.5">
                        Password {cred?.has_password ? "(leave blank to keep current)" : "*"}
                      </label>
                      <div className="relative">
                        <input
                          type={showPassword ? "text" : "password"}
                          value={formPassword}
                          onChange={(e) => setFormPassword(e.target.value)}
                          placeholder={cred?.has_password ? "********" : "Enter password"}
                          className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-sm pr-9"
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassword(!showPassword)}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                        >
                          {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-0.5">Profile URL (optional)</label>
                      <input
                        type="url"
                        value={formProfileUrl}
                        onChange={(e) => setFormProfileUrl(e.target.value)}
                        placeholder="https://..."
                        className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-sm"
                      />
                    </div>
                    <div className="flex gap-2 pt-1">
                      <button
                        onClick={() => handleSave(platform)}
                        disabled={!formEmail.trim() || saveMutation.isPending}
                        className="flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                      >
                        <Save className="h-3.5 w-3.5" /> Save
                      </button>
                      <button
                        onClick={() => { setEditingPlatform(null); resetForm(); }}
                        className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
                      >
                        <X className="h-3.5 w-3.5" /> Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div>
                    {cred ? (
                      <div className="space-y-1.5">
                        <p className="text-sm text-gray-600">{cred.email}</p>
                        <div className="flex items-center gap-2 text-xs text-gray-400">
                          {cred.has_password && <span>Password saved</span>}
                          {cred.profile_url && (
                            <a href={cred.profile_url} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">
                              Profile
                            </a>
                          )}
                        </div>
                        <div className="flex gap-2 pt-1">
                          <button
                            onClick={() => startEdit(platform, cred)}
                            className="text-xs font-medium text-primary-600 hover:text-primary-700"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => deleteMutation.mutate(platform)}
                            disabled={deleteMutation.isPending}
                            className="flex items-center gap-0.5 text-xs text-red-500 hover:text-red-700"
                          >
                            <Trash2 className="h-3 w-3" /> Remove
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button
                        onClick={() => startEdit(platform)}
                        className="flex items-center gap-1.5 text-sm font-medium text-primary-600 hover:text-primary-700"
                      >
                        <Plus className="h-4 w-4" /> Add Credentials
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
