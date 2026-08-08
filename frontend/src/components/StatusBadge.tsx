// A small colored pill for any of this app's fixed-set status strings --
// run status, guardrail outcome, capture/market-data/analysis/evaluation
// status, review decision. One place that maps a status word to a
// color, so the same word always looks the same everywhere it appears.

const STYLES: Record<string, string> = {
  SUCCESS: "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30",
  READY_FOR_REVIEW: "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30",
  APPROVED: "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30",
  REQUIRES_REVIEW: "bg-amber-500/15 text-amber-400 ring-amber-500/30",
  ANALYZING: "bg-sky-500/15 text-sky-400 ring-sky-500/30",
  CREATED: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  FAILED: "bg-red-500/15 text-red-400 ring-red-500/30",
  BLOCKED: "bg-red-500/15 text-red-400 ring-red-500/30",
  REJECTED: "bg-red-500/15 text-red-400 ring-red-500/30",
};

const DEFAULT_STYLE = "bg-slate-500/15 text-slate-300 ring-slate-500/30";

interface StatusBadgeProps {
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const style = STYLES[status] ?? DEFAULT_STYLE;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ring-1 ${style}`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
