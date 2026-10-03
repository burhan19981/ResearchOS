import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
      <p className="text-sm font-medium text-text-primary">Page not found.</p>
      <Link to="/dashboard" className="text-sm text-accent hover:underline">
        Return to Overview
      </Link>
    </div>
  );
}
