// A DEMO-sourced run must never be mistakable for a LIVE one anywhere it
// appears (run list, detail view, review panel) -- this is the one
// component that renders that label, so its wording and styling can
// only ever say one thing in one place.

interface SourceModeBadgeProps {
  mode: string;
}

export function SourceModeBadge({ mode }: SourceModeBadgeProps) {
  if (mode === "DEMO") {
    return (
      <span
        role="status"
        className="inline-flex items-center gap-1 rounded-full bg-amber-500/20 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-amber-400 ring-1 ring-amber-500/50"
      >
        Demo data — not real
      </span>
    );
  }

  return (
    <span
      role="status"
      className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-emerald-400 ring-1 ring-emerald-500/30"
    >
      Live
    </span>
  );
}
