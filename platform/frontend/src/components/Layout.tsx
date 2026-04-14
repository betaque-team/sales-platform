import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { ResumeSwitcher } from "./ResumeSwitcher";

interface LayoutProps {
  children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header bar with centered brand + resume switcher */}
        <header className="flex h-12 items-center border-b border-gray-200 bg-white px-6">
          <div className="flex-1" />
          <span className="text-sm font-bold tracking-wide text-gray-900">reventlabs</span>
          <div className="flex-1 flex justify-end">
            <ResumeSwitcher />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-7xl px-6 py-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
