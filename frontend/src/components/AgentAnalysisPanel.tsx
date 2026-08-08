import type { AgentAnalysisOut } from "../api/types";
import { EmptyState } from "./EmptyState";
import { ErrorNotice } from "./ErrorNotice";

interface AgentAnalysisPanelProps {
  analysis: AgentAnalysisOut | undefined;
}

function CategoricalPill({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-sm font-semibold text-slate-100">{value ?? "—"}</p>
    </div>
  );
}

export function AgentAnalysisPanel({ analysis }: AgentAnalysisPanelProps) {
  if (!analysis) {
    return <EmptyState message="No agent analysis yet." />;
  }

  if (analysis.status !== "SUCCESS") {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-red-400">
          Status: {analysis.status}
        </p>
        <ErrorNotice title="Agent analysis failed" message={analysis.error_message} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <CategoricalPill label="Trend direction" value={analysis.trend_direction} />
        <CategoricalPill label="Trend quality" value={analysis.trend_quality} />
        <CategoricalPill label="Structure" value={analysis.structure_quality} />
        <CategoricalPill label="Setup" value={analysis.setup_quality} />
        <CategoricalPill label="Context risk" value={analysis.context_risk} />
        <CategoricalPill label="Uncertainty" value={analysis.uncertainty} />
      </div>

      <div className="flex flex-col gap-3 text-sm text-slate-300">
        <p>{analysis.analysis_text}</p>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Trend</p>
          <p>{analysis.trend_assessment}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Structure</p>
          <p>{analysis.structure_assessment}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Setup</p>
          <p>{analysis.setup_assessment}</p>
        </div>
      </div>
    </div>
  );
}
