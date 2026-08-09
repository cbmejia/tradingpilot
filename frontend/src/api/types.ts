// TradePilot AI — TypeScript shapes mirroring backend/schemas.py exactly.
//
// These are read-only response shapes from the API -- nothing here is
// computed on the frontend. If a field can be missing (a FAILED row, a
// run that hasn't been analyzed yet), it's typed as `| null`, matching
// the Optional[...] fields in the Python schemas, so the UI is forced to
// handle "no data yet" instead of assuming a value exists.

export type CaptureStatus = "SUCCESS" | "FAILED";
export type MarketDataStatus = "SUCCESS" | "FAILED";
export type AgentAnalysisStatus = "SUCCESS" | "FAILED";
export type EvaluationStatus = "SUCCESS" | "FAILED";
export type SourceMode = "LIVE" | "DEMO";
export type GuardrailOutcome = "BLOCKED" | "REQUIRES_REVIEW" | "READY_FOR_REVIEW";
export type ReviewDecision = "APPROVED" | "REJECTED";

// 7A Iteration 2: which of a run's (up to two) captures this is -- the
// timeframe the user actually intends to trade on ("PRIMARY", the only
// kind that existed before this iteration), or one rung up the fixed
// ladder captured purely for cross-timeframe context ("CONFIRMATION").
export type CaptureTimeframeRole = "PRIMARY" | "CONFIRMATION";

export interface CaptureOut {
  id: number;
  capture_mode: SourceMode | string;
  timeframe_role: CaptureTimeframeRole | string;
  symbol: string;
  timeframe: string;
  screenshot_path: string | null;
  captured_at: string | null;
  status: CaptureStatus | string;
  error_message: string | null;
}

export interface MarketDataOut {
  id: number;
  mode: SourceMode | string;
  symbol: string;
  price: number | null;
  timestamp: string | null;
  source: string;
  status: MarketDataStatus | string;
  error_message: string | null;
}

export interface AgentAnalysisOut {
  id: number;
  status: AgentAnalysisStatus | string;
  analysis_text: string | null;
  trend_assessment: string | null;
  structure_assessment: string | null;
  setup_assessment: string | null;
  uncertainty: string | null;
  trend_direction: string | null;
  trend_quality: string | null;
  structure_quality: string | null;
  setup_quality: string | null;
  context_risk: string | null;
  error_message: string | null;
  timestamp: string;
}

export interface EvaluationOut {
  id: number;
  status: EvaluationStatus | string;
  trend_score: number | null;
  structure_score: number | null;
  entry_score: number | null;
  risk_reward_score: number | null;
  timing_context_score: number | null;
  total_score: number | null;
  risk_reward_ratio: number | null;
  error_message: string | null;
  timestamp: string;
}

export interface GuardrailResultOut {
  id: number;
  guardrail_name: string;
  passed: boolean;
  reason: string | null;
  timestamp: string;
}

export interface HumanReviewOut {
  id: number;
  decision: ReviewDecision | string;
  decided_at: string;
  comment: string | null;
}

export interface AuditEventOut {
  id: number;
  event_type: string;
  event_message: string;
  timestamp: string;
}

// 7A Iteration 1. has_proposal=false means the agent was asked and
// declined -- direction/entry/stop/target/risk_reward_ratio/is_coherent/
// coherence_error are all null in that case, never a fabricated
// placeholder. has_proposal=true always has direction/entry/stop/target
// populated, and then either risk_reward_ratio (coherent) or
// coherence_error (incoherent) populated, never both. This is
// informational only -- it never appears anywhere the run's own
// evaluation or guardrail outcome reads from.
export interface AgentProposalOut {
  id: number;
  has_proposal: boolean;
  direction: string | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  risk_reward_ratio: number | null;
  is_coherent: boolean | null;
  coherence_error: string | null;
  timestamp: string;
}

// 7A Iteration 2. The confirmation call's own read of a run's
// confirmation-timeframe chart -- a SEPARATE Claude call from the
// primary AgentAnalysisOut above. No ConfirmationAnalysisOut on a
// RunDetail at all means the question was never reached (top of the
// ladder, or a Milestone 12 force_scenario run); status="FAILED" means
// it was reached and didn't succeed (a real reason in error_message
// either way). Never read by the run's own score or guardrail outcome
// except via the derived CROSS_TIMEFRAME_AGREEMENT guardrail result.
export interface ConfirmationAnalysisOut {
  id: number;
  status: AgentAnalysisStatus | string;
  visible_timeframe: string | null;
  trend_direction: string | null;
  trend_quality: string | null;
  error_message: string | null;
  timestamp: string;
}

export interface RunSummary {
  id: string;
  symbol: string;
  timeframe: string;
  direction: string | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  status: string;
  created_at: string;
  completed_at: string | null;
  // 7A Iteration 1: set only on a run created via
  // POST /runs/{run_id}/accept-proposal -- the id of the run whose
  // agent-proposed levels became this run's own entry/stop/target. Null
  // for every ordinary, hand-entered run.
  accepted_from_run_id: string | null;
}

export interface RunDetail extends RunSummary {
  captures: CaptureOut[];
  market_data: MarketDataOut[];
  analyses: AgentAnalysisOut[];
  evaluations: EvaluationOut[];
  guardrail_results: GuardrailResultOut[];
  human_review: HumanReviewOut | null;
  audit_events: AuditEventOut[];
  guardrail_outcome: GuardrailOutcome | null;
  // 7A Iteration 1: null if the agent analysis never succeeded (the
  // question of a proposal was never reached) -- see AgentProposalOut for
  // the has_proposal=false vs. absent distinction.
  proposal: AgentProposalOut | null;
  // 7A Iteration 2: null if there was no confirmation timeframe to
  // attempt at all (top of the ladder, or force_scenario active) -- see
  // ConfirmationAnalysisOut's own docstring for the absent-vs-FAILED
  // distinction.
  confirmation_analysis: ConfirmationAnalysisOut | null;
}

export interface RunListResponse {
  items: RunSummary[];
  limit: number;
  offset: number;
  total: number;
}

export interface RunCreateRequest {
  symbol: string;
  timeframe: string;
  direction?: string | null;
  entry?: number | null;
  stop?: number | null;
  target?: number | null;
}

export interface RunCreateResponse {
  id: string;
  status: string;
}

export interface HumanReviewRequest {
  decision: ReviewDecision;
  comment?: string | null;
}

export interface HumanReviewResponse {
  run_id: string;
  decision: ReviewDecision;
  decided_at: string;
  comment: string | null;
  run_status: string;
}

// 7A Iteration 1. What POST /runs/{run_id}/accept-proposal sends back:
// the brand-new run it just created (not the source run). This never
// touches the source run's own score or guardrail outcome.
export interface AcceptProposalResponse {
  id: string;
  accepted_from_run_id: string;
  symbol: string;
  timeframe: string;
  direction: string;
  entry: number;
  stop: number;
  target: number;
  status: string;
}

// The eight timeframes backend/schemas.py's ALLOWED_TIMEFRAMES accepts.
// Duplicated here (not fetched from the API) since it's a fixed,
// documented set -- same tradeoff as database/models.py's
// AGENT_CATEGORICAL_FIELDS duplicating agents/trade_agent.py's allowed
// values rather than adding a runtime dependency for a handful of
// constants.
export const ALLOWED_TIMEFRAMES: readonly string[] = [
  "1m",
  "5m",
  "15m",
  "30m",
  "1h",
  "4h",
  "1d",
  "1w",
];

// Milestone 12 — mirrors backend/orchestrator.py's FORCE_SCENARIOS
// exactly. Each value deliberately substitutes a synthetic result for
// one pipeline stage so a guardrail can be demonstrated with a real,
// reproducible run -- see components/TestingControls.tsx and
// docs/failure_modes.md. The backend refuses all of these outright
// unless TESTING_CONTROLS_ENABLED=true is set on the server; this list
// only controls what the dropdown offers, not whether it does anything.
export interface ForceScenarioOption {
  value: string;
  label: string;
  description: string;
}

export const FORCE_SCENARIOS: readonly ForceScenarioOption[] = [
  { value: "capture_fails", label: "Capture fails", description: "Expect: BLOCKED, no chart, agent never called." },
  { value: "capture_stale", label: "Capture stale", description: "Expect: BLOCKED on CAPTURE_FRESH." },
  { value: "market_data_fails", label: "Market data fails", description: "Expect: BLOCKED, no invented price." },
  { value: "market_data_stale", label: "Market data stale", description: "Expect: BLOCKED on MARKET_DATA_FRESH." },
  { value: "agent_fails", label: "Agent fails", description: "Expect: FAILED analysis, no evaluation score, BLOCKED." },
  { value: "high_uncertainty", label: "High agent uncertainty", description: "Expect: can never reach READY_FOR_REVIEW." },
  { value: "perfect_demo_score", label: "Perfect demo score", description: "Expect: REQUIRES_REVIEW on SYNTHETIC_DATA, never READY_FOR_REVIEW." },
];
