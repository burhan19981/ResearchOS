/** Small, dependency-free formatting helpers shared across features. */

export function humanizeToken(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    // Split on underscores/whitespace (RUN_STATUS) and on
    // lower-to-upper boundaries (PascalCase entity type names like
    // "ResearchQuestion") so both vocabularies read the same way.
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes}m ${remaining}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

export function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined) return "—";
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(digits).replace(/0+$/, "").replace(/\.$/, "");
}
