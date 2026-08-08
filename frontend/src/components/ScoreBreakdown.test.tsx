import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScoreBreakdown } from "./ScoreBreakdown";
import type { AgentAnalysisOut, EvaluationOut } from "../api/types";

const ANALYSIS: AgentAnalysisOut = {
  id: 1,
  status: "SUCCESS",
  analysis_text: "x",
  trend_assessment: "x",
  structure_assessment: "x",
  setup_assessment: "x",
  uncertainty: "MEDIUM",
  trend_direction: "UP",
  trend_quality: "STRONG",
  structure_quality: "CLEAN",
  setup_quality: "ACCEPTABLE",
  context_risk: "LOW",
  error_message: null,
  timestamp: "2026-01-01T00:00:00Z",
};

const EVALUATION: EvaluationOut = {
  id: 1,
  status: "SUCCESS",
  trend_score: 14,
  structure_score: 14,
  entry_score: 14,
  risk_reward_score: 20,
  timing_context_score: 14,
  total_score: 76,
  risk_reward_ratio: 2.0000000000000444,
  error_message: null,
  timestamp: "2026-01-01T00:00:00Z",
};

describe("ScoreBreakdown", () => {
  it("shows an empty state when no evaluation exists yet", () => {
    render(<ScoreBreakdown evaluation={undefined} analysis={undefined} />);

    expect(screen.getByText(/no evaluation yet/i)).toBeInTheDocument();
  });

  it("renders status FAILED and the real error message, not blank scores, for a failed evaluation", () => {
    const failed: EvaluationOut = {
      ...EVALUATION,
      status: "FAILED",
      trend_score: null,
      structure_score: null,
      entry_score: null,
      risk_reward_score: null,
      timing_context_score: null,
      total_score: null,
      risk_reward_ratio: null,
      error_message: "Cannot compute risk/reward: missing trade parameter(s): entry, stop, target",
    };

    render(<ScoreBreakdown evaluation={failed} analysis={ANALYSIS} />);

    expect(screen.getByText(/status: failed/i)).toBeInTheDocument();
    expect(screen.getByText(/cannot compute risk\/reward/i)).toBeInTheDocument();
  });

  it("displays each component score directly next to the categorical evidence that produced it", () => {
    render(<ScoreBreakdown evaluation={EVALUATION} analysis={ANALYSIS} />);

    const trendRow = screen.getByTestId("score-row-trend");
    expect(within(trendRow).getByText("14")).toBeInTheDocument();
    expect(within(trendRow).getByText(/up/i)).toBeInTheDocument();
    expect(within(trendRow).getByText(/strong/i)).toBeInTheDocument();

    const structureRow = screen.getByTestId("score-row-structure");
    expect(within(structureRow).getByText("14")).toBeInTheDocument();
    expect(within(structureRow).getByText(/clean/i)).toBeInTheDocument();

    const entryRow = screen.getByTestId("score-row-entry");
    expect(within(entryRow).getByText("14")).toBeInTheDocument();
    expect(within(entryRow).getByText(/acceptable/i)).toBeInTheDocument();

    const contextRow = screen.getByTestId("score-row-timing-context");
    expect(within(contextRow).getByText("14")).toBeInTheDocument();
    expect(within(contextRow).getByText(/low/i)).toBeInTheDocument();

    // Risk/Reward's "evidence" is the raw ratio, formatted to 2 decimal
    // places -- the same traceability the categorical fields give the
    // other four rows, just for the one component whose evidence is a
    // number instead of a category word.
    const rrRow = screen.getByTestId("score-row-risk-reward");
    expect(within(rrRow).getByText("20")).toBeInTheDocument();
    expect(within(rrRow).getByText(/2\.00/)).toBeInTheDocument();

    expect(screen.getByText("76")).toBeInTheDocument();
  });
});
