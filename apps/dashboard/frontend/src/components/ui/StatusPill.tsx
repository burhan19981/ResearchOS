import { AlertTriangle, CheckCircle2, CircleDashed, Info, XCircle } from "lucide-react";
import { humanizeToken } from "@/lib/format";
import { statusTone, type StatusTone } from "@/lib/statusTone";

const TONE_CLASSES: Record<StatusTone, string> = {
  success: "bg-status-success/15 text-status-success border-status-success/30",
  warning: "bg-status-warning/15 text-status-warning border-status-warning/30",
  danger: "bg-status-danger/15 text-status-danger border-status-danger/30",
  info: "bg-accent/15 text-accent border-accent/30",
  neutral: "bg-status-neutral/15 text-text-secondary border-status-neutral/30",
};

const TONE_ICONS: Record<StatusTone, typeof CheckCircle2> = {
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
  info: Info,
  neutral: CircleDashed,
};

interface StatusPillProps {
  status: string | null | undefined;
  label?: string;
}

/**
 * Status is always communicated via icon + text + color together —
 * never color alone (Dashboard V1 spec section 27).
 */
export function StatusPill({ status, label }: StatusPillProps) {
  const tone = statusTone(status);
  const Icon = TONE_ICONS[tone];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      <Icon size={12} aria-hidden="true" />
      {label ?? humanizeToken(status)}
    </span>
  );
}
