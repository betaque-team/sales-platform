import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@/components/Button";
import { login } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ReventlabsLogo } from "@/components/ReventlabsLogo";

export function LoginPage() {
  const navigate = useNavigate();
  const { refetch } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [searchParams] = useSearchParams();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (searchParams.get("error") === "not_invited") {
      setError("Access denied. Your account has not been invited to this platform. Contact your admin to get access.");
    }
  }, [searchParams]);

  // Regression finding 207: when the api.ts global interceptor
  // redirects an expired-session user here, it preserves the page they
  // were on in `?next=`. Honor it after successful sign-in so the user
  // lands back where they were (e.g., the job detail they were opening
  // when their cookie expired) instead of always bouncing to "/".
  //
  // Security: only accept a path-relative next (starts with "/" but
  // NOT "//"). This blocks `?next=//evil.com` (protocol-relative) and
  // `?next=https://evil.com` (absolute) which would otherwise let an
  // attacker craft a phishing link that lands authenticated users on
  // their domain. Fragment / query are fine and preserved via the
  // pathname+search round-trip in api.ts.
  const safeNext = (() => {
    const raw = searchParams.get("next");
    if (!raw) return "/";
    if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
    return raw;
  })();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      await refetch();
      navigate(safeNext);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleLogin = () => {
    window.location.href = "/api/v1/auth/google";
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="mx-auto flex h-14 items-center justify-center rounded-2xl bg-gray-900 px-5 mb-4 w-fit">
            <ReventlabsLogo className="h-5 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Sales Platform</h1>
          <p className="mt-2 text-sm text-gray-600">
            Sales intelligence platform for infrastructure, DevOps, security, and compliance roles.
          </p>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="text-center text-lg font-semibold text-gray-900 mb-6">
            Sign in to continue
          </h2>

          {error && (
            <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input w-full"
                placeholder="you@company.com"
              />
            </div>
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input w-full"
                placeholder="Enter your password"
              />
            </div>
            <Button
              type="submit"
              variant="primary"
              size="lg"
              className="w-full justify-center"
              loading={loading}
            >
              Sign In
            </Button>
          </form>

          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-200" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-white px-2 text-gray-400">or</span>
            </div>
          </div>

          <Button
            variant="secondary"
            size="lg"
            className="w-full justify-center gap-3"
            onClick={handleGoogleLogin}
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24">
              <path
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
                fill="#4285F4"
              />
              <path
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                fill="#34A853"
              />
              <path
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                fill="#FBBC05"
              />
              <path
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                fill="#EA4335"
              />
            </svg>
            Sign in with Google
          </Button>

          <p className="mt-4 text-center text-xs text-gray-500">
            Only authorized team members can access this platform.
          </p>
        </div>
      </div>
    </div>
  );
}
