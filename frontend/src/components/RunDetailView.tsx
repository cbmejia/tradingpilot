import type { RunDetail } from "../api/types";
import { Card } from "./Card";
import { StatusBadge } from "./StatusBadge";
import { SourceModeBadge } from "./DemoBadge";
import { ChartCapturePanel } from "./ChartCapturePanel";
import { MarketDataPanel } from "./MarketDataPanel";
import { AgentAnalysisPanel } from "./AgentAnalysisPanel";
import { ScoreBreakdown } from "./ScoreBreakdown";
import { GuardrailResultsPanel } from "./GuardrailResultsPanel";
import { ReviewPanel } from "./ReviewPanel";

/** Mirrors guardrails/rules.py's own SYNTHETIC_DATA check: a run is
 * demo-sourced if EITHER its capture or its market data came from DEMO
 * mode -- never inferred from just one of the two. */
function isDemoRun(run: RunDetail): boolean {
  return run.captures[0]?.capture_mode === "DEMO" || run.market_data[0]?.mode === "DEMO";
}

interface RunDetailViewProps {
  run: RunDetail;
  onApprove: (comment: string) => void;
  onReject: (comment: string) => void;
  reviewBusy: boolean;
}

export function RunDetailView({ run, onApprove, onReject, reviewBusy }: RunDetailViewProps) {
  const demo = isDemoRun(run);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold text-slate-100">
          {run.symbol} <span className="text-slate-500">{run.timeframe}</span>
        </h2>
        <StatusBadge status={run.status} />
        {demo && <SourceModeBadge mode="DEMO" />}
        <span className="text-xs text-slate-500">run {run.id}</span>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Chart capture">
          <ChartCapturePanel runId={run.id} capture={run.captures[0]} />
        </Card>
        <Card title="Market snapshot">
          <MarketDataPanel marketData={run.market_data[0]} />
        </Card>
      </div>

      <Card title="Agent analysis" subtitle="Prose for a human reviewer, plus the categories the rubric scores from">
        <AgentAnalysisPanel analysis={run.analyses[0]} />
      </Card>

      <Card
        title="Evaluation"
        subtitle="Each score shown next to the observation that produced it"
      >
        <ScoreBreakdown evaluation={run.evaluations[0]} analysis={run.analyses[0]} />
      </Card>

      <Card title="Guardrails" subtitle="All eleven checks, every time">
        <GuardrailResultsPanel results={run.guardrail_results} />
      </Card>

      <Card title="Human review">
        <ReviewPanel
          guardrailOutcome={run.guardrail_outcome}
          humanReview={run.human_review}
          onApprove={onApprove}
          onReject={onReject}
          busy={reviewBusy}
          isDemo={demo}
        />
      </Card>
    </div>
  );
}
