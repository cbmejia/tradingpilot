import type { AgentAnalysisOut, EvaluationOut } from "../api/types";
import { EmptyState } from "./EmptyState";
import { ErrorNotice } from "./ErrorNotice";

interface ScoreBreakdownProps {
  evaluation: EvaluationOut | undefined;
  analysis: AgentAnalysisOut | undefined;
}

/**
 * One row = one component score, displayed next to the exact
 * categorical evidence that produced it (docs/rubric.md) -- never just
 * a bare number. `evidence` is plain display text built from fields the
 * API already returned; nothing here recomputes a score.
 */
function ScoreRow({
  label,
  score,
  evidence,
}: {
  label: string;
  score: number | null;
  evidence: string;
}) {
  return (
    <div
      data-testid={`score-row-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`}
      className="flex items-center justify-between gap-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2"
    >
      <div>
        <p className="text-sm font-medium text-slate-200">{label}</p>
        <p className="text-xs text-slate-500">{evidence}</p>
      </div>
      <p className="whitespace-nowrap text-lg font-bold text-slate-100">
        {score ?? "—"}
        <span className="text-xs font-normal text-slate-500">/20</span>
      </p>
    </div>
  );
}

const DASH = "—";

export function ScoreBreakdown({ evaluation, analysis }: ScoreBreakdownProps) {
  if (!evaluation) {
    return <EmptyState message="No evaluation yet." />;
  }

  if (evaluation.status !== "SUCCESS") {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-red-400">
          Status: {evaluation.status}
        </p>
        <ErrorNotice title="Evaluation failed" message={evaluation.error_message} />
      </div>
    );
  }

  const ratioText =
    evaluation.risk_reward_ratio === null ? DASH : evaluation.risk_reward_ratio.toFixed(2);

  return (
    <div className="flex flex-col gap-2">
      <ScoreRow
        label="Trend"
        score={evaluation.trend_score}
        evidence={`${analysis?.trend_direction ?? DASH} · ${analysis?.trend_quality ?? DASH}`}
      />
      <ScoreRow
        label="Structure"
        score={evaluation.structure_score}
        evidence={analysis?.structure_quality ?? DASH}
      />
      <ScoreRow
        label="Entry"
        score={evaluation.entry_score}
        evidence={analysis?.setup_quality ?? DASH}
      />
      <ScoreRow
        label="Risk/Reward"
        score={evaluation.risk_reward_score}
        evidence={`ratio ${ratioText}`}
      />
      <ScoreRow
        label="Timing/Context"
        score={evaluation.timing_context_score}
        evidence={analysis?.context_risk ?? DASH}
      />

      <div className="mt-1 flex items-center justify-between rounded-md border border-sky-500/30 bg-sky-500/10 px-3 py-2">
        <p className="text-sm font-semibold text-slate-100">Total</p>
        <p className="text-xl font-bold text-slate-100">
          {evaluation.total_score ?? DASH}
          <span className="text-xs font-normal text-slate-500">/100</span>
        </p>
      </div>
    </div>
  );
}
