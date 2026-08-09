// TradePilot AI — 7A Iteration 2: the confirmation call's own read of a
// run's confirmation-timeframe chart, plus the CROSS_TIMEFRAME_AGREEMENT
// guardrail's verdict on whether it agrees with the primary read.
//
// The agent never states "agreement" itself -- confirmation_analysis only
// ever carries the confirmation call's OWN trend_direction/trend_quality
// (see agents/trade_agent.py's analyze_confirmation()); crossTimeframeCheck
// is guardrails/rules.py's _cross_timeframe_agreement() verdict, passed in
// separately so this panel never re-derives agreement on the frontend --
// it only ever displays what the backend already decided.

import type { ConfirmationAnalysisOut, GuardrailResultOut } from "../api/types";
import { EmptyState } from "./EmptyState";
import { ErrorNotice } from "./ErrorNotice";

interface ConfirmationAnalysisPanelProps {
  confirmationAnalysis: ConfirmationAnalysisOut | null | undefined;
  crossTimeframeCheck: GuardrailResultOut | undefined;
}

export function ConfirmationAnalysisPanel({
  confirmationAnalysis,
  crossTimeframeCheck,
}: ConfirmationAnalysisPanelProps) {
  // No confirmation_analysis row at all means the question was never
  // reached (top of the ladder, or a Milestone 12 force_scenario run) --
  // crossTimeframeCheck.reason already carries the exact, distinct reason
  // (see guardrails/rules.py's _cross_timeframe_agreement()), so this
  // panel reuses it rather than guessing which N/A applies.
  if (!confirmationAnalysis) {
    return (
      <EmptyState
        message={crossTimeframeCheck?.reason ?? "No confirmation timeframe applies to this run."}
      />
    );
  }

  if (confirmationAnalysis.status !== "SUCCESS") {
    return <ErrorNotice title="Confirmation analysis failed" message={confirmationAnalysis.error_message} />;
  }

  const agreementBadge = crossTimeframeCheck && (
    <span
      data-testid="cross-timeframe-badge"
      className={
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide " +
        (crossTimeframeCheck.passed
          ? "bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30"
          : "bg-red-500/15 text-red-400 ring-1 ring-red-500/30")
      }
    >
      {crossTimeframeCheck.passed ? "Agrees" : "Does not confirm"}
    </span>
  );

  return (
    <div className="flex flex-col gap-3">
      <dl className="grid grid-cols-3 gap-x-3 gap-y-1 text-sm text-slate-100">
        <div>
          <dt className="text-xs text-slate-500">Visible timeframe</dt>
          <dd>{confirmationAnalysis.visible_timeframe}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Trend direction</dt>
          <dd>{confirmationAnalysis.trend_direction}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Trend quality</dt>
          <dd>{confirmationAnalysis.trend_quality}</dd>
        </div>
      </dl>

      {crossTimeframeCheck && (
        <div
          data-testid="cross-timeframe-result"
          className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2"
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Cross-timeframe agreement
            </span>
            {agreementBadge}
          </div>
          <p className="mt-1 text-xs text-slate-400">{crossTimeframeCheck.reason}</p>
        </div>
      )}
    </div>
  );
}
