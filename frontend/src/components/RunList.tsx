import type { RunSummary } from "../api/types";
import { EmptyState } from "./EmptyState";
import { StatusBadge } from "./StatusBadge";
import { SourceModeBadge } from "./DemoBadge";

/**
 * RunSummary (GET /runs) has no mode/guardrail_outcome field of its own
 * -- only GET /runs/{id} does. `isDemo` is filled in by App.tsx after a
 * follow-up GET /runs/{id} per visible row (undefined while that fetch
 * is still in flight); `status` doubles as the guardrail-outcome display
 * because backend/orchestrator.py sets Run.status to the guardrail
 * outcome itself (BLOCKED/REQUIRES_REVIEW/READY_FOR_REVIEW) once
 * analysis finishes, and to APPROVED/REJECTED after a human decision --
 * so it already carries the same information a dedicated field would.
 */
export interface RunListItem extends RunSummary {
  isDemo?: boolean;
}

interface RunListProps {
  items: RunListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  error: string | null;
}

export function RunList({ items, selectedId, onSelect, error }: RunListProps) {
  if (error) {
    return (
      <p className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
        {error}
      </p>
    );
  }

  if (items.length === 0) {
    return <EmptyState message="No runs yet. Analyze one to see it here." />;
  }

  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <li key={item.id}>
          <button
            type="button"
            onClick={() => onSelect(item.id)}
            className={
              "flex w-full flex-col gap-1 rounded-md border px-3 py-2 text-left transition " +
              (item.id === selectedId
                ? "border-sky-500 bg-sky-500/10"
                : "border-slate-800 bg-slate-950 hover:border-slate-700")
            }
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-slate-100">
                {item.symbol} <span className="text-slate-500">{item.timeframe}</span>
              </span>
              <StatusBadge status={item.status} />
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-slate-500">
                {new Date(item.created_at).toLocaleString()}
              </span>
              {item.isDemo && <SourceModeBadge mode="DEMO" />}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}
