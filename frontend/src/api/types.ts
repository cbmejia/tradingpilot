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

export interface CaptureOut {
  id: number;
  capture_mode: SourceMode | string;
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
