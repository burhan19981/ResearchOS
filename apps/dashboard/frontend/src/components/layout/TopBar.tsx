import { Microscope } from "lucide-react";
import { useProject } from "@/api/hooks";
import { useProjectContext } from "@/lib/ProjectContext";
import { StatusPill } from "@/components/ui/StatusPill";
import { ProjectSelector } from "./ProjectSelector";

export function TopBar() {
  const { selectedProjectId } = useProjectContext();
  const { data: project } = useProject(selectedProjectId);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface-1 px-4">
      <a href="/dashboard" className="flex items-center gap-2 text-sm font-semibold text-text-primary">
        <Microscope size={18} className="text-accent" aria-hidden="true" />
        ResearchOS
      </a>
      <div className="flex items-center gap-4">
        {project ? <StatusPill status={project.status} /> : null}
        <ProjectSelector />
        <div className="flex items-center gap-2 rounded-full border border-border bg-surface-2 py-1 pl-1 pr-3 text-xs text-text-secondary">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent/20 text-[11px] font-semibold text-accent">
            PI
          </span>
          Dashboard User
        </div>
      </div>
    </header>
  );
}
