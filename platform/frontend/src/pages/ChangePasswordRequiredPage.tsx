import { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { Button } from "@/components/Button";
import { changePassword } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ReventlabsLogo } from "@/components/ReventlabsLogo";
import { Lock } from "lucide-react";

/**
 * F247 — full-screen "you must change your password" gate.
 *
 * Mounted at ``/change-password`` and used as a hard redirect target
 * by ``ProtectedRoute`` whenever ``user.must_change_password`` is
 * ``true`` (which happens after a super-admin force-resets the
 * user's password via ``POST /users/{id}/reset-password``).
 *
 * Why a dedicated page instead of a modal:
 * - Modals can be dismissed with Escape, an overlay click, or by
 *   directly typing a different URL into the address bar. Any of
 *   those would leave the user logged in with a known temp password
 *   they didn't have to rotate. A separate route + the gate in
 *   ``ProtectedRoute`` means there is no other reachable page until
 *   the change succeeds.
 * - No sidebar, no top-nav, nothing the user could click to
 *   navigate away. The only escape hatches are "log out" and
 *   "submit the form".
 *
 * After a successful change:
 * - The backend sets ``must_change_password=False`` and the
 *   ``changePassword`` API returns 200.
 * - ``refetch`` is called so ``useAuth().user`` re-reads via
 *   ``GET /auth/me`` and the gate clears.
 * - We navigate to ``/`` (dashboard).
 */
export function ChangePasswordRequiredPage() {
  const navigate = useNavigate();
  const { user, loading: authLoading, refetch } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [submitLoading, setSubmitLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    // Mirror the backend's 8-char minimum (auth.py:271). Showing the
    // validation client-side avoids a round-trip 400 with the same
    // message and gives faster feedback.
    if (newPassword.length < 8) {
      setError("New password must be at least 8 characters");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match");
      return;
    }
    if (newPassword === currentPassword) {
      setError("New password must be different from the temporary one");
      return;
    }

    setSubmitLoading(true);
    try {
      await changePassword(currentPassword, newPassword);
      // Refetch so the updated user (must_change_password=false) is
      // in the auth context — the next ProtectedRoute check passes.
      await refetch();
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to change password");
    } finally {
      setSubmitLoading(false);
    }
  };

  // While the auth context is still hydrating, show a small spinner
  // instead of flashing the form (which would briefly show a fully-
  // unauthenticated state before the cookie check resolves).
  if (authLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="spinner h-8 w-8" />
      </div>
    );
  }

  // Unauthed visit (someone typed the URL directly). Bounce to login
  // so the form doesn't render against an empty session — the API
  // call would 401 and the user would see a confusing error.
  if (!user) {
    return <Navigate to="/login" replace />;
  }

  // Already past the gate? Don't trap them on this page just because
  // they bookmarked it. The flag flips to false right after a
  // successful change, but a stale tab + a fresh login in another
  // window could land here when the prompt isn't needed anymore.
  if (!user.must_change_password) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-6">
          <div className="mx-auto flex h-14 items-center justify-center rounded-2xl bg-gray-900 px-5 mb-4 w-fit">
            <ReventlabsLogo className="h-5 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Choose a new password</h1>
          {user?.email && (
            <p className="mt-2 text-sm text-gray-600">
              Signed in as <span className="font-medium text-gray-900">{user.email}</span>
            </p>
          )}
        </div>

        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 mb-4 flex gap-3">
          <Lock className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
          <div className="text-sm text-amber-900">
            <p className="font-medium">Your password was reset by an administrator.</p>
            <p className="mt-1 text-amber-800">
              For your security, please choose a new password before continuing. The
              temporary password is now valid for this one-time change only.
            </p>
          </div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          {error && (
            <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="current" className="block text-sm font-medium text-gray-700 mb-1">
                Temporary password
              </label>
              <input
                id="current"
                type="password"
                required
                autoFocus
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                className="input w-full"
                placeholder="The password your admin just shared"
              />
            </div>
            <div>
              <label htmlFor="new" className="block text-sm font-medium text-gray-700 mb-1">
                New password
              </label>
              <input
                id="new"
                type="password"
                required
                minLength={8}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="input w-full"
                placeholder="At least 8 characters"
              />
            </div>
            <div>
              <label htmlFor="confirm" className="block text-sm font-medium text-gray-700 mb-1">
                Confirm new password
              </label>
              <input
                id="confirm"
                type="password"
                required
                minLength={8}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="input w-full"
                placeholder="Type it again"
              />
            </div>
            <Button
              type="submit"
              variant="primary"
              size="lg"
              className="w-full justify-center"
              loading={submitLoading}
            >
              Change password
            </Button>
          </form>

          <p className="mt-4 text-center text-xs text-gray-500">
            You can&rsquo;t use the rest of the app until you change this password.
          </p>
        </div>
      </div>
    </div>
  );
}
