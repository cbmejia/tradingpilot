import type { GuardrailResultOut } from "../api/types";
import { EmptyState } from "./EmptyState";

interface GuardrailResultsPanelProps {
  results: GuardrailResultOut[];
}

export function GuardrailResultsPanel({ results }: GuardrailResultsPanelProps) {
  if (results.length === 0) {
    return <EmptyState message="Guardrails have not run yet." />;
  }

  return (
    <ul className="flex flex-col gap-2">
      {results.map((result) => (
        <li
          key={result.id}
          className="flex items-start gap-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2"
        >
          <span
            className={
              "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-slate-950 " +
              (result.passed ? "bg-emerald-500" : "bg-red-500")
            }
          >
            {result.passed ? "✓" : "✕"}
          </span>
          <div>
            <p className="text-sm font-medium text-slate-200">
              {result.guardrail_name.replace(/_/g, " ")}
            </p>
            <p className="text-xs text-slate-500">{result.reason ?? "No reason provided."}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}
