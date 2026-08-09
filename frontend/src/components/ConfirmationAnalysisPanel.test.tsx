import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConfirmationAnalysisPanel } from "./ConfirmationAnalysisPanel";
import type { ConfirmationAnalysisOut, GuardrailResultOut } from "../api/types";

const SUCCESS_ANALYSIS: ConfirmationAnalysisOut = {
  id: 1,
  status: "SUCCESS",
  visible_timeframe: "4h",
  trend_direction: "UP",
  trend_quality: "MODERATE",
  error_message: null,
  timestamp: "2026-01-01T00:00:00Z",
};

function check(overrides: Partial<GuardrailResultOut> = {}): GuardrailResultOut {
  return {
    id: 1,
    guardrail_name: "CROSS_TIMEFRAME_AGREEMENT",
    passed: true,
    reason: "Primary trend (UP) and confirmation trend (UP) agree.",
    timestamp: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ConfirmationAnalysisPanel", () => {
  it("shows the guardrail's own N/A reason text when there is no confirmation_analysis row", () => {
    render(
      <ConfirmationAnalysisPanel
        confirmationAnalysis={null}
        crossTimeframeCheck={check({
          passed: true,
          reason: "N/A: primary at top of ladder -- the primary timeframe is already at the top of the fixed ladder; no confirmation timeframe exists to compare against.",
        })}
      />,
    );

    expect(screen.getByText(/N\/A: primary at top of ladder/i)).toBeInTheDocument();
  });

  it("shows a fallback message when there is no confirmation_analysis row and no guardrail check either", () => {
    render(<ConfirmationAnalysisPanel confirmationAnalysis={null} crossTimeframeCheck={undefined} />);

    expect(screen.getByText(/no confirmation timeframe applies/i)).toBeInTheDocument();
  });

  it("shows a real error message for a FAILED confirmation analysis", () => {
    render(
      <ConfirmationAnalysisPanel
        confirmationAnalysis={{
          ...SUCCESS_ANALYSIS,
          status: "FAILED",
          visible_timeframe: null,
          trend_direction: null,
          trend_quality: null,
          error_message: "Confirmation capture did not succeed.",
        }}
        crossTimeframeCheck={check({
          passed: false,
          reason: "Confirmation capture failed: No demo fixture for EURUSD 1d.",
        })}
      />,
    );

    expect(screen.getByText(/confirmation analysis failed/i)).toBeInTheDocument();
    expect(screen.getByText(/confirmation capture did not succeed/i)).toBeInTheDocument();
  });

  it("renders the confirmation read and an 'Agrees' badge when the guardrail passed", () => {
    render(
      <ConfirmationAnalysisPanel
        confirmationAnalysis={SUCCESS_ANALYSIS}
        crossTimeframeCheck={check({ passed: true })}
      />,
    );

    expect(screen.getByText("4h")).toBeInTheDocument();
    expect(screen.getByText("UP")).toBeInTheDocument();
    expect(screen.getByText("MODERATE")).toBeInTheDocument();
    expect(screen.getByTestId("cross-timeframe-badge")).toHaveTextContent(/agrees/i);
    expect(screen.getByTestId("cross-timeframe-result")).toHaveTextContent(/agree/i);
  });

  it("renders a 'Does not confirm' badge and the specific reason when the guardrail failed", () => {
    render(
      <ConfirmationAnalysisPanel
        confirmationAnalysis={{ ...SUCCESS_ANALYSIS, trend_direction: "DOWN" }}
        crossTimeframeCheck={check({
          passed: false,
          reason: "Primary trend (UP) and confirmation trend (DOWN) disagree.",
        })}
      />,
    );

    expect(screen.getByTestId("cross-timeframe-badge")).toHaveTextContent(/does not confirm/i);
    expect(screen.getByText(/disagree/i)).toBeInTheDocument();
  });
});
