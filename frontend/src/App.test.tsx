import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { RunDetail, RunListResponse } from "./api/types";

// The entire API client is mocked -- nothing in this file makes a real
// network call. This is what lets these tests exercise App.tsx's actual
// orchestration logic (create -> analyze -> poll -> render) without a
// backend running at all.
vi.mock("./api/client", async () => {
  const actual = await vi.importActual<typeof import("./api/client")>("./api/client");
  return {
    ...actual,
    createRun: vi.fn(),
    analyzeRun: vi.fn(),
    getRun: vi.fn(),
    listRuns: vi.fn(),
    reviewRun: vi.fn(),
    acceptProposal: vi.fn(),
    screenshotUrl: (runId: string) => `http://127.0.0.1:8000/runs/${runId}/screenshot`,
  };
});

import * as api from "./api/client";

const EMPTY_LIST: RunListResponse = { items: [], limit: 10, offset: 0, total: 0 };

function demoRun(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: "run-1",
    symbol: "EURUSD",
    timeframe: "1h",
    direction: "long",
    entry: 1.095,
    stop: 1.09,
    target: 1.105,
    status: "REQUIRES_REVIEW",
    created_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:05Z",
    accepted_from_run_id: null,
    captures: [
      {
        id: 1,
        capture_mode: "DEMO",
        timeframe_role: "PRIMARY",
        symbol: "EURUSD",
        timeframe: "1h",
        screenshot_path: "screenshots/demo/EURUSD_1h.png",
        captured_at: "2026-01-01T00:00:01Z",
        status: "SUCCESS",
        error_message: null,
      },
    ],
    market_data: [
      {
        id: 1,
        mode: "DEMO",
        symbol: "EURUSD",
        price: 1.0921,
        timestamp: "2026-01-01T00:00:02Z",
        source: "demo_fixture",
        status: "SUCCESS",
        error_message: null,
      },
    ],
    analyses: [
      {
        id: 1,
        status: "SUCCESS",
        analysis_text: "Clean pullback.",
        trend_assessment: "Up.",
        structure_assessment: "Clean.",
        setup_assessment: "Good.",
        uncertainty: "MEDIUM",
        trend_direction: "UP",
        trend_quality: "STRONG",
        structure_quality: "CLEAN",
        setup_quality: "ACCEPTABLE",
        context_risk: "LOW",
        error_message: null,
        timestamp: "2026-01-01T00:00:03Z",
      },
    ],
    evaluations: [
      {
        id: 1,
        status: "SUCCESS",
        trend_score: 14,
        structure_score: 14,
        entry_score: 14,
        risk_reward_score: 20,
        timing_context_score: 14,
        total_score: 76,
        risk_reward_ratio: 2.0,
        error_message: null,
        timestamp: "2026-01-01T00:00:04Z",
      },
    ],
    guardrail_results: [
      { id: 1, guardrail_name: "SYNTHETIC_DATA", passed: false, reason: "DEMO data.", timestamp: "2026-01-01T00:00:05Z" },
    ],
    human_review: null,
    audit_events: [],
    guardrail_outcome: "REQUIRES_REVIEW",
    proposal: null,
    confirmation_analysis: null,
    ...overrides,
  };
}

describe("App", () => {
  beforeEach(() => {
    vi.mocked(api.listRuns).mockResolvedValue(EMPTY_LIST);
    vi.mocked(api.getRun).mockReset();
    vi.mocked(api.createRun).mockReset();
    vi.mocked(api.analyzeRun).mockReset();
    vi.mocked(api.reviewRun).mockReset();
    vi.mocked(api.acceptProposal).mockReset();
  });

  it("shows a clear message instead of hanging when the backend is unreachable", async () => {
    vi.mocked(api.listRuns).mockRejectedValue(
      new api.ApiError("Could not reach the TradePilot backend at http://127.0.0.1:8000."),
    );

    render(<App />);

    expect(await screen.findByText(/could not reach the tradepilot backend/i)).toBeInTheDocument();
  });

  it("runs a full analyze flow end to end and renders the finished run, including its demo label", async () => {
    const user = userEvent.setup();
    const finished = demoRun();

    vi.mocked(api.createRun).mockResolvedValue({ id: "run-1", status: "CREATED" });
    vi.mocked(api.getRun).mockResolvedValue(finished);
    vi.mocked(api.analyzeRun).mockResolvedValue(finished);

    render(<App />);

    await user.click(screen.getByRole("button", { name: /^analyze$/i }));

    await waitFor(() => expect(api.analyzeRun).toHaveBeenCalledWith("run-1", undefined));
    expect(api.createRun).toHaveBeenCalledTimes(1);

    // The finished run's evaluation, guardrail outcome, and demo label
    // all render from the real analyzeRun() response -- nothing here is
    // computed by the frontend itself.
    expect(await screen.findByText("76")).toBeInTheDocument();
    expect(screen.getAllByText(/demo data/i).length).toBeGreaterThan(0);
  });

  it("Milestone 12: choosing a testing scenario sends force_scenario and shows the unmistakable testing banner", async () => {
    const user = userEvent.setup();
    const forced = demoRun({
      status: "BLOCKED",
      guardrail_outcome: "BLOCKED",
      captures: [
        {
          id: 1,
          capture_mode: "DEMO",
          timeframe_role: "PRIMARY",
          symbol: "EURUSD",
          timeframe: "1h",
          screenshot_path: null,
          captured_at: null,
          status: "FAILED",
          error_message:
            "TESTING: capture deliberately forced to fail (force_scenario='capture_fails') for guardrail verification. This is not a real capture failure.",
        },
      ],
      analyses: [],
      evaluations: [],
      audit_events: [
        {
          id: 1,
          event_type: "testing_scenario_forced",
          event_message:
            "TESTING: this run's pipeline was deliberately altered to force scenario 'capture_fails' for guardrail verification. This is not a real analysis.",
          timestamp: "2026-01-01T00:00:00Z",
        },
      ],
    });

    vi.mocked(api.createRun).mockResolvedValue({ id: "run-1", status: "CREATED" });
    vi.mocked(api.getRun).mockResolvedValue(forced);
    vi.mocked(api.analyzeRun).mockResolvedValue(forced);

    render(<App />);

    await user.selectOptions(
      screen.getByRole("combobox", { name: /force a testing scenario/i }),
      "capture_fails",
    );
    await user.click(screen.getByRole("button", { name: /forcing a test scenario/i }));

    await waitFor(() =>
      expect(api.analyzeRun).toHaveBeenCalledWith("run-1", "capture_fails"),
    );
    expect(await screen.findByText(/testing run — not a real analysis/i)).toBeInTheDocument();
    expect(screen.getByText(/capture deliberately forced to fail/i)).toBeInTheDocument();
  });

  it("approving is disabled and rejecting works for a BLOCKED run reached via the run list", async () => {
    const user = userEvent.setup();
    const blocked = demoRun({
      status: "BLOCKED",
      guardrail_outcome: "BLOCKED",
      captures: [
        {
          id: 1,
          capture_mode: "DEMO",
          timeframe_role: "PRIMARY",
          symbol: "EURUSD",
          timeframe: "1h",
          screenshot_path: null,
          captured_at: null,
          status: "FAILED",
          error_message: "Chart element never appeared.",
        },
      ],
    });

    vi.mocked(api.listRuns).mockResolvedValue({
      items: [
        {
          id: "run-1",
          symbol: "EURUSD",
          timeframe: "1h",
          direction: "long",
          entry: 1.095,
          stop: 1.09,
          target: 1.105,
          status: "BLOCKED",
          created_at: "2026-01-01T00:00:00Z",
          completed_at: "2026-01-01T00:00:05Z",
          accepted_from_run_id: null,
        },
      ],
      limit: 10,
      offset: 0,
      total: 1,
    });
    vi.mocked(api.getRun).mockResolvedValue(blocked);
    vi.mocked(api.reviewRun).mockResolvedValue({
      run_id: "run-1",
      decision: "REJECTED",
      decided_at: "2026-01-01T00:00:06Z",
      comment: null,
      run_status: "REJECTED",
    });

    render(<App />);

    await user.click(await screen.findByText("EURUSD", { selector: "span" }));

    // The failed capture's real error shows where the chart would be.
    expect(await screen.findByText(/chart element never appeared/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /reject/i }));

    await waitFor(() =>
      expect(api.reviewRun).toHaveBeenCalledWith("run-1", { decision: "REJECTED", comment: null }),
    );
  });

  it("7A Iteration 1: accepting a proposal calls acceptProposal and navigates to the new run", async () => {
    const user = userEvent.setup();
    const sourceRun = demoRun({
      id: "run-1",
      proposal: {
        id: 1,
        has_proposal: true,
        direction: "LONG",
        entry: 1.1,
        stop: 1.095,
        target: 1.11,
        risk_reward_ratio: 2.0,
        is_coherent: true,
        coherence_error: null,
        timestamp: "2026-01-01T00:00:04Z",
      },
    });
    const newRun = demoRun({
      id: "run-2",
      status: "CREATED",
      guardrail_outcome: null,
      accepted_from_run_id: "run-1",
      direction: "LONG",
      entry: 1.1,
      stop: 1.095,
      target: 1.11,
      captures: [],
      market_data: [],
      analyses: [],
      evaluations: [],
      guardrail_results: [],
      audit_events: [],
      proposal: null,
    });

    vi.mocked(api.createRun).mockResolvedValue({ id: "run-1", status: "CREATED" });
    vi.mocked(api.analyzeRun).mockResolvedValue(sourceRun);
    vi.mocked(api.getRun).mockImplementation((runId: string) =>
      Promise.resolve(runId === "run-2" ? newRun : sourceRun),
    );
    vi.mocked(api.acceptProposal).mockResolvedValue({
      id: "run-2",
      accepted_from_run_id: "run-1",
      symbol: "EURUSD",
      timeframe: "1h",
      direction: "LONG",
      entry: 1.1,
      stop: 1.095,
      target: 1.11,
      status: "CREATED",
    });

    render(<App />);

    await user.click(screen.getByRole("button", { name: /^analyze$/i }));
    await waitFor(() => expect(api.analyzeRun).toHaveBeenCalled());

    await user.click(await screen.findByRole("button", { name: /accept proposal/i }));

    await waitFor(() => expect(api.acceptProposal).toHaveBeenCalledWith("run-1"));
    // "Navigates" to the new run the same way selecting a run from the
    // list already does -- api.getRun is called for the new run's id,
    // and its own provenance (accepted_from_run_id) is now on screen.
    await waitFor(() => expect(api.getRun).toHaveBeenCalledWith("run-2"));
    expect(await screen.findByText(/accepting an agent-proposed trade level from/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run run-1/i })).toBeInTheDocument();
  });
});
