import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

const STORAGE_KEY = "researchos.dashboard.selectedProjectId";

interface ProjectContextValue {
  selectedProjectId: number | null;
  setSelectedProjectId: (id: number | null) => void;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

function readStoredProjectId(): number | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  } catch {
    // localStorage can throw in a locked-down/private browsing context —
    // fall back to "no project selected yet" rather than crashing.
    return null;
  }
}

/**
 * The one place the dashboard's "currently selected project" lives.
 * Every project-scoped page reads `selectedProjectId` from here (never
 * from a prop drilled independently down every route) so switching
 * projects in the top-bar selector consistently reloads every
 * project-scoped view using the new project's id — never mixing
 * records between projects (Dashboard V1 spec section 7).
 */
export function ProjectProvider({ children }: { children: ReactNode }) {
  const [selectedProjectId, setSelectedProjectIdState] = useState<number | null>(readStoredProjectId);

  useEffect(() => {
    try {
      if (selectedProjectId === null) {
        window.localStorage.removeItem(STORAGE_KEY);
      } else {
        window.localStorage.setItem(STORAGE_KEY, String(selectedProjectId));
      }
    } catch {
      // Best-effort persistence only.
    }
  }, [selectedProjectId]);

  const value = useMemo<ProjectContextValue>(
    () => ({ selectedProjectId, setSelectedProjectId: setSelectedProjectIdState }),
    [selectedProjectId],
  );

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export function useProjectContext(): ProjectContextValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) {
    throw new Error("useProjectContext must be used within a ProjectProvider.");
  }
  return ctx;
}
