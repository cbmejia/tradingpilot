import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RunList } from "./RunList";
import type { RunListItem } from "./RunList";

const BASE: RunListItem = {
  id: "run-1",
  symbol: "EURUSD",
  timeframe: "1h",
  direction: "long",
  entry: 1.095,
  stop: 1.09,
  target: 1.105,
  status: "REQUIRES_REVIEW",
  created_at: "2026-01-01T00:00:00Z",
  completed_at: "2026-01-01T00:00:01Z",
  accepted_from_run_id: null,
};

describe("RunList", () => {
  it("shows an empty state with no runs", () => {
    render(<RunList items={[]} selectedId={null} onSelect={() => {}} error={null} />);

    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
  });

  it("shows a clear error message instead of hanging when the list failed to load", () => {
    render(
      <RunList
        items={[]}
        selectedId={null}
        onSelect={() => {}}
        error="Could not reach the TradePilot backend at http://127.0.0.1:8000."
      />,
    );

    expect(screen.getByText(/could not reach the tradepilot backend/i)).toBeInTheDocument();
  });

  it("renders an unmistakable demo label for a demo-sourced run in the list", () => {
    render(
      <RunList
        items={[{ ...BASE, isDemo: true }]}
        selectedId={null}
        onSelect={() => {}}
        error={null}
      />,
    );

    expect(screen.getByText(/demo data/i)).toBeInTheDocument();
  });

  it("does not show a demo label for a live-sourced run", () => {
    render(
      <RunList
        items={[{ ...BASE, isDemo: false }]}
        selectedId={null}
        onSelect={() => {}}
        error={null}
      />,
    );

    expect(screen.queryByText(/demo data/i)).not.toBeInTheDocument();
  });
});
