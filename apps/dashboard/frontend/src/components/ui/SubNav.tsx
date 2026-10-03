import { NavLink } from "react-router-dom";

interface SubNavItem {
  label: string;
  to: string;
  end?: boolean;
}

export function SubNav({ items }: { items: SubNavItem[] }) {
  return (
    <nav aria-label="Section tabs" className="mb-5 flex gap-1 border-b border-border-subtle">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            `border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              isActive
                ? "border-accent text-text-primary"
                : "border-transparent text-text-secondary hover:text-text-primary"
            }`
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}
