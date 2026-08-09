// TradePilot AI — 7A Iteration 1: the agent's proposed trade levels.
//
// This panel is deliberately visually distinct from both the user's own
// levels and the scored result above it (ScoreBreakdown) -- a dashed
// border and a different accent color, the same "this is not a normal
// part of the app" treatment components/TestingControls.tsx already uses
// for a different reason. The risk/reward ratio shown here is the
// proposal's own, computed once by backend/orchestrator.py -- it is
// never the same number as evaluation.risk_reward_ratio, and this panel
// never claims otherwise.

import type { AgentProposalOut } from "../api/types";
import { EmptyState } from "./EmptyState";

interface AgentProposalPanelProps {
  proposal: AgentProposalOut | undefined;
  userDirection: string | null;
  userEntry: number | null;
  userStop: number | null;
  userTarget: number | null;
  // The agent's own setup_assessment prose -- the closest thing to a
  // stated reason for declining, since there is no dedicated "why
  // declined" field. Only ever shown alongside a decline, never
  // presented as a rejection reason for anything else.
  agentReasoning: string | null;
  onAccept: () => void;
  accepting: boolean;
  acceptError: string | null;
}

const DASH = "—";

function LevelRow({
  testId,
  label,
  direction,
  entry,
  stop,
  target,
  tone,
}: {
  testId: string;
  label: string;
  direction: string | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  tone: "neutral" | "proposal";
}) {
  const wrapperClass =
    tone === "proposal"
      ? "rounded-md border-2 border-dashed border-sky-500/50 bg-sky-500/10 px-3 py-2"
      : "rounded-md border border-slate-800 bg-slate-950 px-3 py-2";
  const labelClass =
    tone === "proposal"
      ? "text-xs font-bold uppercase tracking-wide text-sky-400"
      : "text-xs font-semibold uppercase tracking-wide text-slate-500";
  const dtClass = tone === "proposal" ? "text-xs text-sky-300/80" : "text-xs text-slate-500";

  return (
    <div data-testid={testId} className={wrapperClass}>
      <p className={labelClass}>{label}</p>
      <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-sm text-slate-100 sm:grid-cols-4">
        <div>
          <dt className={dtClass}>Direction</dt>
          <dd>{direction ?? DASH}</dd>
        </div>
        <div>
          <dt className={dtClass}>Entry</dt>
          <dd>{entry ?? DASH}</dd>
        </div>
        <div>
          <dt className={dtClass}>Stop</dt>
          <dd>{stop ?? DASH}</dd>
        </div>
        <div>
          <dt className={dtClass}>Target</dt>
          <dd>{target ?? DASH}</dd>
        </div>
      </dl>
    </div>
  );
}

export function AgentProposalPanel({
  proposal,
  userDirection,
  userEntry,
  userStop,
  userTarget,
  agentReasoning,
  onAccept,
  accepting,
  acceptError,
}: AgentProposalPanelProps) {
  const userHasLevels = userEntry !== null && userStop !== null && userTarget !== null;

  if (!proposal) {
    return <EmptyState message="No trade level proposal yet." />;
  }

  if (!proposal.has_proposal) {
    return (
      <div className="flex flex-col gap-2">
        {userHasLevels && (
          <LevelRow
            testId="proposal-your-levels"
            label="Your levels"
            direction={userDirection}
            entry={userEntry}
            stop={userStop}
            target={userTarget}
            tone="neutral"
          />
        )}
        <p data-testid="proposal-declined-notice" className="text-sm leading-relaxed text-slate-500">
          The agent did not propose alternative trade levels for this setup.
        </p>
        {agentReasoning && (
          <p data-testid="proposal-declined-reasoning" className="text-xs italic leading-relaxed text-slate-600">
            “{agentReasoning}”
          </p>
        )}
      </div>
    );
  }

  const ratioText = proposal.risk_reward_ratio === null ? DASH : proposal.risk_reward_ratio.toFixed(2);

  return (
    <div className="flex flex-col gap-3">
      <div className={userHasLevels ? "grid gap-3 sm:grid-cols-2" : ""}>
        {userHasLevels && (
          <LevelRow
            testId="proposal-your-levels"
            label="Your levels"
            direction={userDirection}
            entry={userEntry}
            stop={userStop}
            target={userTarget}
            tone="neutral"
          />
        )}
        <div>
          <LevelRow
            testId="proposal-agent-levels"
            label="Agent proposal — unscored"
            direction={proposal.direction}
            entry={proposal.entry}
            stop={proposal.stop}
            target={proposal.target}
            tone="proposal"
          />
          <p data-testid="proposal-ratio" className="mt-1 text-xs text-sky-300/80">
            Risk/reward {ratioText} — informational only, not part of the score.
          </p>
          {proposal.is_coherent === false && (
            <p data-testid="proposal-coherence-warning" className="mt-1 text-xs text-amber-400">
              Not coherent: {proposal.coherence_error}
            </p>
          )}
        </div>
      </div>

      {acceptError && (
        <p className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {acceptError}
        </p>
      )}

      <button
        type="button"
        onClick={onAccept}
        disabled={accepting}
        className="self-start rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
      >
        {accepting ? "Accepting…" : "Accept proposal & create new run"}
      </button>
    </div>
  );
}
