import type { RunDetail } from "../api/types";
import { Card } from "./Card";
import { StatusBadge } from "./StatusBadge";
import { SourceModeBadge } from "./DemoBadge";
import { ChartCapturePanel } from "./ChartCapturePanel";
import { MarketDataPanel } from "./MarketDataPanel";
import { AgentAnalysisPanel } from "./AgentAnalysisPanel";
import { ScoreBreakdown } from "./ScoreBreakdown";
import { AgentProposalPanel } from "./AgentProposalPanel";
import { ConfirmationAnalysisPanel } from "./ConfirmationAnalysisPanel";
import { GuardrailResultsPanel } from "./GuardrailResultsPanel";
import { ReviewPanel } from "./ReviewPanel";

/** Mirrors guardrails/rules.py's own SYNTHETIC_DATA check: a run is
 * demo-sourced if EITHER its capture or its market data came from DEMO
 * mode -- never inferred from just one of the two. */
function isDemoRun(run: RunDetail): boolean {
  return run.captures[0]?.capture_mode === "DEMO" || run.market_data[0]?.mode === "DEMO";
}

/** Milestone 12: backend/orchestrator.py writes a testing_scenario_forced
 * audit event as the very first thing it does whenever force_scenario
 * was used -- checking for it here is what makes a deliberately-forced
 * run unmistakable in the UI, not just in the raw API response. */
function forcedScenario(run: RunDetail): string | null {
  const event = run.audit_events.find((e) => e.event_type === "testing_scenario_forced");
  return event ? event.event_message : null;
}

interface RunDetailViewProps {
  run: RunDetail;
  onApprove: (comment: string) => void;
  onReject: (comment: string) => void;
  reviewBusy: boolean;
  onAcceptProposal: () => void;
  acceptingProposal: boolean;
  acceptProposalError: string | null;
  onSelectRun: (runId: string) => void;
}

export function RunDetailView({
  run,
  onApprove,
  onReject,
  reviewBusy,
  onAcceptProposal,
  acceptingProposal,
  acceptProposalError,
  onSelectRun,
}: RunDetailViewProps) {
  const demo = isDemoRun(run);
  const forced = forcedScenario(run);
  // 7A Iteration 2: a run's primary capture is always captures[0]
  // (database/models.py's Run.captures relationship guarantees primary
  // is persisted, and ordered, first) -- the confirmation capture, if
  // this run's timeframe had a rung above it on the ladder, is found by
  // role rather than assumed to be captures[1], since it may not exist
  // at all.
  const confirmationCapture = run.captures.find((c) => c.timeframe_role === "CONFIRMATION");
  const crossTimeframeCheck = run.guardrail_results.find(
    (g) => g.guardrail_name === "CROSS_TIMEFRAME_AGREEMENT",
  );

  return (
    <div className="flex flex-col gap-4">
      {forced && (
        <div className="rounded-md border-2 border-dashed border-amber-500 bg-amber-500/15 px-4 py-3">
          <p className="text-sm font-bold uppercase tracking-wide text-amber-400">
            Testing run — not a real analysis
          </p>
          <p className="mt-1 text-xs text-amber-300/90">{forced}</p>
        </div>
      )}

      {run.accepted_from_run_id && (
        <div className="rounded-md border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-xs text-sky-300">
          Created by accepting an agent-proposed trade level from{" "}
          <button
            type="button"
            onClick={() => onSelectRun(run.accepted_from_run_id as string)}
            className="font-semibold underline underline-offset-2 hover:text-sky-200"
          >
            run {run.accepted_from_run_id}
          </button>
          .
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold text-slate-100">
          {run.symbol} <span className="text-slate-500">{run.timeframe}</span>
        </h2>
        <StatusBadge status={run.status} />
        {demo && <SourceModeBadge mode="DEMO" />}
        <span className="text-xs text-slate-500">run {run.id}</span>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Chart capture" subtitle="Primary — the timeframe this run is actually about">
          <ChartCapturePanel runId={run.id} capture={run.captures[0]} role="PRIMARY" />
        </Card>
        <Card title="Market snapshot">
          <MarketDataPanel marketData={run.market_data[0]} />
        </Card>
      </div>

      <Card
        title="Confirmation chart"
        subtitle="One rung up the timeframe ladder — captured for cross-timeframe context, never scored"
      >
        <ChartCapturePanel runId={run.id} capture={confirmationCapture} role="CONFIRMATION" />
      </Card>

      <Card
        title="Cross-timeframe confirmation"
        subtitle="Derived by the orchestrator, never stated by the agent — see docs/architecture.md"
      >
        <ConfirmationAnalysisPanel
          confirmationAnalysis={run.confirmation_analysis}
          crossTimeframeCheck={crossTimeframeCheck}
        />
      </Card>

      <Card title="Agent analysis" subtitle="Prose for a human reviewer, plus the categories the rubric scores from">
        <AgentAnalysisPanel analysis={run.analyses[0]} />
      </Card>

      <Card
        title="Evaluation"
        subtitle="Each score shown next to the observation that produced it"
      >
        <ScoreBreakdown evaluation={run.evaluations[0]} analysis={run.analyses[0]} />
      </Card>

      <Card
        title="Agent's trade level proposal"
        subtitle="An alternative for comparison — never automatically scored"
      >
        <AgentProposalPanel
          proposal={run.proposal ?? undefined}
          userDirection={run.direction}
          userEntry={run.entry}
          userStop={run.stop}
          userTarget={run.target}
          agentReasoning={run.analyses[0]?.setup_assessment ?? null}
          onAccept={onAcceptProposal}
          accepting={acceptingProposal}
          acceptError={acceptProposalError}
        />
      </Card>

      <Card title="Guardrails" subtitle="All twelve checks, every time">
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
