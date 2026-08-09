import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChartCapturePanel } from "./ChartCapturePanel";
import type { CaptureOut } from "../api/types";

const BASE_CAPTURE: CaptureOut = {
  id: 1,
  capture_mode: "DEMO",
  timeframe_role: "PRIMARY",
  symbol: "EURUSD",
  timeframe: "1h",
  screenshot_path: "screenshots/demo/EURUSD_1h.png",
  captured_at: "2026-01-01T00:00:00Z",
  status: "SUCCESS",
  error_message: null,
};

describe("ChartCapturePanel", () => {
  it("shows an empty state when no capture exists yet", () => {
    render(<ChartCapturePanel runId="run-1" capture={undefined} />);

    expect(screen.getByText(/no chart has been captured/i)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("renders the real error message for a failed capture, not an empty state or broken image", () => {
    const capture: CaptureOut = {
      ...BASE_CAPTURE,
      status: "FAILED",
      screenshot_path: null,
      captured_at: null,
      error_message: "No demo fixture for ZZZINVALID 1h. DEMO mode never substitutes a different pair's chart.",
    };

    render(<ChartCapturePanel runId="run-1" capture={capture} />);

    expect(screen.getByText(/chart capture failed/i)).toBeInTheDocument();
    expect(screen.getByText(/no demo fixture for zzzinvalid/i)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByText(/no chart has been captured/i)).not.toBeInTheDocument();
  });

  it("renders the chart image and a DEMO label for a successful demo capture", () => {
    render(<ChartCapturePanel runId="run-1" capture={BASE_CAPTURE} />);

    const image = screen.getByRole("img") as HTMLImageElement;
    expect(image.src).toContain("/runs/run-1/screenshot");
    expect(screen.getByText(/demo data/i)).toBeInTheDocument();
  });

  it("does not show a demo label for a successful LIVE capture", () => {
    render(<ChartCapturePanel runId="run-1" capture={{ ...BASE_CAPTURE, capture_mode: "LIVE" }} />);

    expect(screen.queryByText(/demo data/i)).not.toBeInTheDocument();
    expect(screen.getByText(/^live$/i)).toBeInTheDocument();
  });

  // --- 7A Iteration 2: role selection ---

  it("shows a confirmation-specific empty state when role=CONFIRMATION and no capture exists", () => {
    render(<ChartCapturePanel runId="run-1" capture={undefined} role="CONFIRMATION" />);

    expect(screen.getByText(/no confirmation chart has been captured/i)).toBeInTheDocument();
  });

  it("requests the confirmation image URL when role=CONFIRMATION", () => {
    const confirmationCapture: CaptureOut = { ...BASE_CAPTURE, id: 2, timeframe_role: "CONFIRMATION", timeframe: "4h" };
    render(<ChartCapturePanel runId="run-1" capture={confirmationCapture} role="CONFIRMATION" />);

    const image = screen.getByRole("img") as HTMLImageElement;
    expect(image.src).toContain("/runs/run-1/screenshot");
    expect(image.src).toContain("role=CONFIRMATION");
  });

  it("does not append a role query param for the default PRIMARY role", () => {
    render(<ChartCapturePanel runId="run-1" capture={BASE_CAPTURE} />);

    const image = screen.getByRole("img") as HTMLImageElement;
    expect(image.src).not.toContain("role=");
  });
});
