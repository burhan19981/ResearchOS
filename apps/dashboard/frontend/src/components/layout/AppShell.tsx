import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function AppShell() {
  return (
    <div className="flex h-screen flex-col bg-surface-0">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main id="main-content" className="min-w-0 flex-1 overflow-y-auto px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
