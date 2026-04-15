import { NavLink, useLocation } from "react-router-dom";
import { clsx } from "clsx";
import {
  LayoutDashboard,
  Briefcase,
  Star,
  List,
  ClipboardCheck,
  Building2,
  GitBranch,
  BarChart3,
  Settings,
  LogOut,
  Radio,
  Activity,
  FileText,
  Users,
  Tags,
  Send,
  BookOpen,
  KeyRound,
  MessageSquarePlus,
  HelpCircle,
  Brain,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { logout } from "@/lib/api";

const navigation = [
  { name: "Dashboard", to: "/", icon: LayoutDashboard },
  { name: "Relevant Jobs", to: "/jobs?role_cluster=relevant", icon: Star },
  { name: "All Jobs", to: "/jobs", icon: List },
  { name: "Review Queue", to: "/review", icon: ClipboardCheck },
  { name: "Companies", to: "/companies", icon: Building2 },
  { name: "Platforms", to: "/platforms", icon: Radio },
  { name: "Resume Score", to: "/resume-score", icon: FileText },
  { name: "Answer Book", to: "/answer-book", icon: BookOpen },
  { name: "Credentials", to: "/credentials", icon: KeyRound },
  { name: "Applications", to: "/applications", icon: Send },
  { name: "Pipeline", to: "/pipeline", icon: GitBranch },
  { name: "Analytics", to: "/analytics", icon: BarChart3 },
  { name: "Intelligence", to: "/intelligence", icon: Brain },
  { name: "Feedback", to: "/feedback", icon: MessageSquarePlus },
  { name: "Docs", to: "/docs", icon: HelpCircle },
  { name: "Settings", to: "/settings", icon: Settings },
];

const adminNavigation = [
  { name: "Monitoring", to: "/monitoring", icon: Activity },
  { name: "Role Clusters", to: "/role-clusters", icon: Tags },
];

const superAdminNavigation = [
  { name: "User Management", to: "/users", icon: Users },
];

export function Sidebar() {
  const { user } = useAuth();
  const location = useLocation();

  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      window.location.href = "/login";
    }
  };

  return (
    <div className="flex h-full w-64 flex-col bg-primary-950">
      <div className="flex h-16 items-center gap-2 border-b border-primary-800 px-6">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-500">
          <Briefcase className="h-4 w-4 text-white" />
        </div>
        <span className="text-lg font-bold text-white">Sales Platform</span>
      </div>

      <nav className="flex-1 space-y-1 px-3 py-4">
        {navigation.map((item) => {
          // Custom active check for items with query params
          const isActive = item.to.includes("?")
            ? location.pathname + location.search === item.to
            : item.to === "/"
              ? location.pathname === "/"
              : location.pathname === item.to && !location.search.includes("role_cluster=relevant");

          return (
            <NavLink
              key={item.name}
              to={item.to}
              className={clsx(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary-700/50 text-white"
                  : "text-white/90 hover:bg-primary-800 hover:text-white"
              )}
            >
              <item.icon className="h-5 w-5 flex-shrink-0" />
              {item.name}
            </NavLink>
          );
        })}

        {(user?.role === "admin" || user?.role === "super_admin") && (
          <>
            <div className="my-2 border-t border-primary-800" />
            <p className="px-3 py-1 text-xs font-semibold text-white/70 uppercase">Admin</p>
            {adminNavigation.map((item) => (
              <NavLink
                key={item.name}
                to={item.to}
                className={({ isActive }) =>
                  clsx(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-primary-700/50 text-white"
                      : "text-white/90 hover:bg-primary-800 hover:text-white"
                  )
                }
              >
                <item.icon className="h-5 w-5 flex-shrink-0" />
                {item.name}
              </NavLink>
            ))}
          </>
        )}

        {user?.role === "super_admin" && (
          <>
            {superAdminNavigation.map((item) => (
              <NavLink
                key={item.name}
                to={item.to}
                className={({ isActive }) =>
                  clsx(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-primary-700/50 text-white"
                      : "text-white/90 hover:bg-primary-800 hover:text-white"
                  )
                }
              >
                <item.icon className="h-5 w-5 flex-shrink-0" />
                {item.name}
              </NavLink>
            ))}
          </>
        )}
      </nav>

      <div className="border-t border-primary-800 p-3">
        <div className="flex items-center gap-3 rounded-lg px-3 py-2">
          {user?.picture ? (
            <img
              src={user.picture}
              alt={user.name}
              className="h-8 w-8 rounded-full ring-2 ring-primary-700"
            />
          ) : (
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-700 text-primary-200 text-sm font-medium">
              {user?.name?.charAt(0)?.toUpperCase() || "U"}
            </div>
          )}
          <div className="flex-1 min-w-0">
            <p className="truncate text-sm font-medium text-white">
              {user?.name || "User"}
            </p>
            <p className="truncate text-xs text-white/80">
              {user?.email || ""}
            </p>
          </div>
          <button
            onClick={handleLogout}
            className="rounded-lg p-1.5 text-white/70 hover:bg-primary-800 hover:text-white transition-colors"
            title="Sign out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
