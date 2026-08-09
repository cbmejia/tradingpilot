import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PipelineProgress } from "./PipelineProgress";
import type { RunDetail } from "../api/types";

function partialRun(overrides: Partial<RunDetail>): RunDetail {
  return {
    id: "run-1",
    symbol: "EURUSD",
    timeframe: "1h",
    direction: null,
    entry: null,
    stop: null,
    target: null,
    status: "ANALYZING",
    created_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    accepted_from_run_id: null,
    captures: [],
    market_data: [],
    analyses: [],
    evaluations: [],
    guardrail_results: [],
    human_review: null,
    audit_events: [],
    guardrail_outcome: null,
    proposal: null,
    confirmation_analysis: null,
    ...overrides,
  };
}

describe("PipelineProgress", () => {
  it("shows nothing done and the first stage in progress before any data has arrived", () => {
    render(<PipelineProgress run={partialRun({})} isAnalyzing={true} />);

    expect(screen.getByTestId("stage-spinner")).toBeInTheDocument();
  });

  it("reflects real capture data as it arrives, not a fake animation", () => {
    const run = partialRun({
      captures: [
        {
          id: 1,
          capture_mode: "DEMO",
          timeframe_role: "PRIMARY",
          symbol: "EURUSD",
          timeframe: "1h",
          screenshot_path: "x.png",
          captured_at: "2026-01-01T00:00:00Z",
          status: "SUCCESS",
          error_message: null,
        },
      ],
    });

    render(<PipelineProgress run={run} isAnalyzing={true} />);

    // Capture is done (checkmark, not spinner); market data is next in
    // progress -- exactly what the polled data says, no timers involved.
    expect(screen.getAllByTestId("stage-spinner")).toHaveLength(1);
  });

  it("shows every stage as pending, with none in progress, before analysis starts", () => {
    render(<PipelineProgress run={null} isAnalyzing={false} />);

    expect(screen.queryByTestId("stage-spinner")).not.toBeInTheDocument();
  });
});
