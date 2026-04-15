import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { Card } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { User, Mail, Shield, Calendar, Lock, Check } from "lucide-react";
import { changePassword } from "@/lib/api";

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
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Current Password
                </label>
                <input
                  type="password"
                  required
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="input w-full"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  New Password
                </label>
                <input
                  type="password"
                  required
                  minLength={6}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="input w-full"
                  placeholder="Min 6 characters"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Confirm New Password
                </label>
                <input
                  type="password"
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

      </div>
    </div>
  );
}
