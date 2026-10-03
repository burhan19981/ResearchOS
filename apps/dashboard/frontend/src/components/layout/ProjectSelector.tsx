import { ChevronDown } from "lucide-react";
import { useEffect } from "react";
import { useProjects } from "@/api/hooks";
import { useProjectContext } from "@/lib/ProjectContext";

/**
 * The project selector — the one control that determines which
 * project's data every other page loads (Dashboard V1 spec section
 * 7). Changing it updates `ProjectContext`, and every project-scoped
 * query key includes the selected project id, so the switch
 * propagates to every open view automatically via React Query.
 */
export function ProjectSelector() {
  const { data: projects, isLoading } = useProjects();
  const { selectedProjectId, setSelectedProjectId } = useProjectContext();

  useEffect(() => {
    if (selectedProjectId === null && projects && projects.length > 0) {
      setSelectedProjectId(projects[0].id);
    }
  }, [projects, selectedProjectId, setSelectedProjectId]);

  if (isLoading) {
    return <div className="h-8 w-48 animate-pulse rounded-md bg-surface-2" />;
  }

  if (!projects || projects.length === 0) {
    return <span className="text-sm text-text-muted">No projects yet</span>;
  }

  return (
    <div className="relative">
      <label htmlFor="project-selector" className="sr-only">
        Select project
      </label>
      <select
        id="project-selector"
        value={selectedProjectId ?? ""}
        onChange={(event) => setSelectedProjectId(Number(event.target.value))}
        className="appearance-none rounded-md border border-border bg-surface-2 py-1.5 pl-3 pr-8 text-sm font-medium text-text-primary hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent"
      >
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.title}
          </option>
        ))}
      </select>
      <ChevronDown size={14} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted" aria-hidden="true" />
    </div>
  );
}
