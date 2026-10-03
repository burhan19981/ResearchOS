import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useProjectContext } from "./ProjectContext";

/**
 * The one hook every project-scoped page uses to determine which
 * project id to load data for. A `:projectId` route param (e.g.
 * `/dashboard/projects/:projectId`) takes precedence and syncs it into
 * the shared `ProjectContext` (so the top-bar selector and every other
 * open view stay consistent with a deep-linked URL); otherwise it
 * falls back to whatever project is currently selected in the top bar.
 */
export function useEffectiveProjectId(): number | null {
  const params = useParams<{ projectId?: string }>();
  const { selectedProjectId, setSelectedProjectId } = useProjectContext();
  const routeProjectId = params.projectId ? Number(params.projectId) : null;

  useEffect(() => {
    if (routeProjectId !== null && routeProjectId !== selectedProjectId) {
      setSelectedProjectId(routeProjectId);
    }
    // Only re-sync when the URL's project id actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeProjectId]);

  return routeProjectId ?? selectedProjectId;
}
