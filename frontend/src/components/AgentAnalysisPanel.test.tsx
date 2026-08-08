import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentAnalysisPanel } from "./AgentAnalysisPanel";
import type { AgentAnalysisOut } from "../api/types";

const FAILED_ANALYSIS: AgentAnalysisOut = {
  id: 1,
  status: "FAILED",
  analysis_text: null,
  trend_assessment: null,
  structure_assessment: null,
  setup_assessment: null,
  uncertainty: null,
  trend_direction: null,
  trend_quality: null,
  structure_quality: null,
  setup_quality: null,
  context_risk: null,
  error_message: "ANTHROPIC_API_KEY is not set in .env.",
  timestamp: "2026-01-01T00:00:00Z",
};

describe("AgentAnalysisPanel", () => {
  it("shows an empty state when no analysis exists yet", () => {
    render(<AgentAnalysisPanel analysis={undefined} />);

    expect(screen.getByText(/no agent analysis yet/i)).toBeInTheDocument();
  });

  it("renders status FAILED and the real error message, not blank fields, for a failed analysis", () => {
    render(<AgentAnalysisPanel analysis={FAILED_ANALYSIS} />);

    expect(screen.getByText(/status: failed/i)).toBeInTheDocument();
    expect(screen.getByText(/anthropic_api_key is not set/i)).toBeInTheDocument();
    // None of the categorical pills or prose sections render for a
    // failed analysis -- there's nothing to show but the failure itself.
    expect(screen.queryByText(/trend direction/i)).not.toBeInTheDocument();
  });

  it("renders prose and all five categorical fields for a successful analysis", () => {
    const analysis: AgentAnalysisOut = {
      ...FAILED_ANALYSIS,
      status: "SUCCESS",
      analysis_text: "Clean pullback into a rising trendline.",
      trend_assessment: "Uptrend.",
      structure_assessment: "Stair-step.",
      setup_assessment: "Readable entry.",
      uncertainty: "MEDIUM",
      trend_direction: "UP",
      trend_quality: "STRONG",
      structure_quality: "CLEAN",
      setup_quality: "ACCEPTABLE",
      context_risk: "LOW",
      error_message: null,
    };

    render(<AgentAnalysisPanel analysis={analysis} />);

    expect(screen.getByText("Clean pullback into a rising trendline.")).toBeInTheDocument();
    expect(screen.getByText("UP")).toBeInTheDocument();
    expect(screen.getByText("STRONG")).toBeInTheDocument();
    expect(screen.getByText("CLEAN")).toBeInTheDocument();
    expect(screen.getByText("ACCEPTABLE")).toBeInTheDocument();
    expect(screen.getByText("LOW")).toBeInTheDocument();
    expect(screen.getByText("MEDIUM")).toBeInTheDocument();
  });
});
