import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReviewPanel } from "./ReviewPanel";
import type { HumanReviewOut } from "../api/types";

const noop = () => {};

describe("ReviewPanel", () => {
  it("disables APPROVE and enables REJECT when the guardrail outcome is BLOCKED", () => {
    render(
      <ReviewPanel
        guardrailOutcome="BLOCKED"
        humanReview={null}
        onApprove={noop}
        onReject={noop}
        busy={false}
        isDemo={false}
      />,
    );

    expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reject/i })).toBeEnabled();
    expect(screen.getByText(/blocked this run/i)).toBeInTheDocument();
  });

  it("enables APPROVE when the guardrail outcome is READY_FOR_REVIEW and no decision exists", () => {
    render(
      <ReviewPanel
        guardrailOutcome="READY_FOR_REVIEW"
        humanReview={null}
        onApprove={noop}
        onReject={noop}
        busy={false}
        isDemo={false}
      />,
    );

    expect(screen.getByRole("button", { name: /approve/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /reject/i })).toBeEnabled();
  });

  it("disables APPROVE when a decision already exists, and shows the existing decision", () => {
    const humanReview: HumanReviewOut = {
      id: 1,
      decision: "REJECTED",
      decided_at: "2026-01-01T00:00:00Z",
      comment: "Not confident enough.",
    };

    render(
      <ReviewPanel
        guardrailOutcome="REQUIRES_REVIEW"
        humanReview={humanReview}
        onApprove={noop}
        onReject={noop}
        busy={false}
        isDemo={false}
      />,
    );

    expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reject/i })).toBeDisabled();
    expect(screen.getByText(/decision: rejected/i)).toBeInTheDocument();
    expect(screen.getByText(/not confident enough/i)).toBeInTheDocument();
  });

  it("shows an unmistakable demo label when the run is demo-sourced", () => {
    render(
      <ReviewPanel
        guardrailOutcome="REQUIRES_REVIEW"
        humanReview={null}
        onApprove={noop}
        onReject={noop}
        busy={false}
        isDemo={true}
      />,
    );

    expect(screen.getByText(/demo data/i)).toBeInTheDocument();
    expect(screen.getByText(/sample data/i)).toBeInTheDocument();
  });

  it("calls onApprove/onReject with the comment when clicked", async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();

    render(
      <ReviewPanel
        guardrailOutcome="READY_FOR_REVIEW"
        humanReview={null}
        onApprove={onApprove}
        onReject={onReject}
        busy={false}
        isDemo={false}
      />,
    );

    await user.type(screen.getByPlaceholderText(/comment/i), "Looks good");
    await user.click(screen.getByRole("button", { name: /approve/i }));

    expect(onApprove).toHaveBeenCalledWith("Looks good");
    expect(onReject).not.toHaveBeenCalled();
  });
});
