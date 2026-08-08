import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TestingControls } from "./TestingControls";

describe("TestingControls", () => {
  it("is unmistakably labeled as a testing affordance", () => {
    render(<TestingControls value="" onChange={() => {}} disabled={false} />);

    expect(screen.getByText(/testing only/i)).toBeInTheDocument();
    expect(screen.getByText(/TESTING_CONTROLS_ENABLED/)).toBeInTheDocument();
  });

  it("defaults to off -- a real analysis, not a forced one", () => {
    render(<TestingControls value="" onChange={() => {}} disabled={false} />);

    expect(screen.getByRole("combobox")).toHaveValue("");
    expect(screen.getByText(/off — run a real analysis/i)).toBeInTheDocument();
  });

  it("calls onChange with the chosen scenario", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<TestingControls value="" onChange={onChange} disabled={false} />);

    await user.selectOptions(screen.getByRole("combobox"), "capture_fails");

    expect(onChange).toHaveBeenCalledWith("capture_fails");
  });

  it("shows the expected outcome for the selected scenario", () => {
    render(<TestingControls value="agent_fails" onChange={() => {}} disabled={false} />);

    expect(screen.getByText(/no evaluation score/i)).toBeInTheDocument();
  });
});
