import {
  Activity,
  ClipboardCheck,
  FileSearch,
  FlaskConical,
  GitBranch,
  LayoutDashboard,
  Lightbulb,
  ListChecks,
  ScrollText,
  Search,
  Sparkles,
} from "lucide-react";
import { NavLink } from "react-router-dom";

interface NavItem {
  label: string;
  to: string;
  icon: typeof LayoutDashboard;
  end?: boolean;
}

interface NavSection {
  title?: string;
  items: NavItem[];
}

const SECTIONS: NavSection[] = [
  { items: [{ label: "Overview", to: "/dashboard", icon: LayoutDashboard, end: true }] },
  {
    title: "Research",
    items: [
      { label: "Pipeline", to: "/dashboard/pipeline", icon: GitBranch },
      { label: "Evidence", to: "/dashboard/evidence", icon: FileSearch },
      { label: "Gaps", to: "/dashboard/evidence/gaps", icon: Search },
      { label: "Novelty", to: "/dashboard/evidence/novelty", icon: Sparkles },
      { label: "Planning", to: "/dashboard/planning", icon: Lightbulb },
    ],
  },
  {
    title: "Experiments",
    items: [
      { label: "Experiments & Runs", to: "/dashboard/experiments", icon: FlaskConical },
      { label: "Analysis", to: "/dashboard/analysis", icon: Activity },
      { label: "Reviews", to: "/dashboard/analysis/reviews", icon: ListChecks },
    ],
  },
  {
    items: [
      { label: "Approvals", to: "/dashboard/approvals", icon: ClipboardCheck },
      { label: "Audit", to: "/dashboard/audit", icon: ScrollText },
    ],
  },
];

export function Sidebar() {
  return (
    <nav aria-label="Primary" className="flex h-full w-56 shrink-0 flex-col gap-4 overflow-y-auto border-r border-border bg-surface-1 px-3 py-4">
      {SECTIONS.map((section, index) => (
        <div key={section.title ?? `section-${index}`}>
          {section.title ? (
            <h3 className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">{section.title}</h3>
          ) : null}
          <ul className="flex flex-col gap-0.5">
            {section.items.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors ${
                      isActive
                        ? "bg-accent/15 text-accent font-medium"
                        : "text-text-secondary hover:bg-surface-2 hover:text-text-primary"
                    }`
                  }
                >
                  <item.icon size={16} aria-hidden="true" />
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}
