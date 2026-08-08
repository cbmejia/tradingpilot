import { useState } from "react";
import type { GuardrailOutcome, HumanReviewOut } from "../api/types";
import { SourceModeBadge } from "./DemoBadge";

interface ReviewPanelProps {
  guardrailOutcome: GuardrailOutcome | null;
  humanReview: HumanReviewOut | null;
  onApprove: (comment: string) => void;
  onReject: (comment: string) => void;
  busy: boolean;
  isDemo: boolean;
}

function approveDisabledReason(
  guardrailOutcome: GuardrailOutcome | null,
  humanReview: HumanReviewOut | null,
): string | null {
  if (humanReview) {
    return `A decision has already been recorded for this run (${humanReview.decision}). Decisions are final.`;
  }
  if (guardrailOutcome === "BLOCKED") {
    return "Guardrails BLOCKED this run — see the guardrail results below for the failing rule. Only REJECT is available.";
  }
  if (guardrailOutcome === null) {
    return "This run hasn't finished analysis yet, so there's nothing to approve. Only REJECT is available.";
  }
  return null;
}

export function ReviewPanel({
  guardrailOutcome,
  humanReview,
  onApprove,
  onReject,
  busy,
  isDemo,
}: ReviewPanelProps) {
  const [comment, setComment] = useState("");

  const disabledReason = approveDisabledReason(guardrailOutcome, humanReview);
  const approveDisabled = disabledReason !== null || busy;
  const rejectDisabled = humanReview !== null || busy;

  return (
    <div className="flex flex-col gap-3">
      {isDemo && (
        <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2">
          <SourceModeBadge mode="DEMO" />
          <span className="text-xs text-amber-300">
            This run used sample data. It can never be treated as a validated live signal.
          </span>
        </div>
      )}

      {humanReview ? (
        <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
          <p className="text-sm font-semibold text-slate-100">
            Decision: {humanReview.decision}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            recorded {new Date(humanReview.decided_at).toLocaleString()}
          </p>
          {humanReview.comment && (
            <p className="mt-2 text-sm text-slate-300">“{humanReview.comment}”</p>
          )}
        </div>
      ) : (
        <textarea
          className="min-h-16 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none disabled:opacity-50"
          placeholder="Comment (optional)"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          disabled={busy || humanReview !== null}
        />
      )}

      {disabledReason && !humanReview && (
        <p className="text-xs text-amber-400">{disabledReason}</p>
      )}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => onApprove(comment)}
          disabled={approveDisabled}
          className="flex-1 rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
        >
          Approve
        </button>
        <button
          type="button"
          onClick={() => onReject(comment)}
          disabled={rejectDisabled}
          className="flex-1 rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
        >
          Reject
        </button>
      </div>
    </div>
  );
}
