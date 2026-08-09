import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AgentProposalPanel } from "./AgentProposalPanel";
import type { AgentProposalOut } from "../api/types";

const COHERENT_PROPOSAL: AgentProposalOut = {
  id: 1,
  has_proposal: true,
  direction: "LONG",
  entry: 1.1,
  stop: 1.095,
  target: 1.11,
  risk_reward_ratio: 2.0,
  is_coherent: true,
  coherence_error: null,
  timestamp: "2026-01-01T00:00:00Z",
};

const DECLINED_PROPOSAL: AgentProposalOut = {
  id: 1,
  has_proposal: false,
  direction: null,
  entry: null,
  stop: null,
  target: null,
  risk_reward_ratio: null,
  is_coherent: null,
  coherence_error: null,
  timestamp: "2026-01-01T00:00:00Z",
};

const noop = () => {};

describe("AgentProposalPanel", () => {
  it("shows an empty state when no proposal exists yet", () => {
    render(
      <AgentProposalPanel
        proposal={undefined}
        userDirection={null}
        userEntry={null}
        userStop={null}
        userTarget={null}
        agentReasoning={null}
        onAccept={noop}
        accepting={false}
        acceptError={null}
      />,
    );

    expect(screen.getByText(/no trade level proposal yet/i)).toBeInTheDocument();
  });

  it("says plainly that the agent declined, rather than rendering an empty panel", () => {
    render(
      <AgentProposalPanel
        proposal={DECLINED_PROPOSAL}
        userDirection={null}
        userEntry={null}
        userStop={null}
        userTarget={null}
        agentReasoning={null}
        onAccept={noop}
        accepting={false}
        acceptError={null}
      />,
    );

    expect(screen.getByTestId("proposal-declined-notice")).toHaveTextContent(
      /did not propose alternative trade levels/i,
    );
    expect(screen.queryByRole("button", { name: /accept proposal/i })).not.toBeInTheDocument();
  });

  it("shows the agent's own stated reasoning alongside a decline, when available", () => {
    render(
      <AgentProposalPanel
        proposal={DECLINED_PROPOSAL}
        userDirection={null}
        userEntry={null}
        userStop={null}
        userTarget={null}
        agentReasoning="No distinct breakout, retest, or reversal level stands out clearly on this chart."
        onAccept={noop}
        accepting={false}
        acceptError={null}
      />,
    );

    expect(screen.getByTestId("proposal-declined-reasoning")).toHaveTextContent(
      /no distinct breakout/i,
    );
  });

  it("does not render a reasoning block when the agent's reasoning is unavailable", () => {
    render(
      <AgentProposalPanel
        proposal={DECLINED_PROPOSAL}
        userDirection={null}
        userEntry={null}
        userStop={null}
        userTarget={null}
        agentReasoning={null}
        onAccept={noop}
        accepting={false}
        acceptError={null}
      />,
    );

    expect(screen.queryByTestId("proposal-declined-reasoning")).not.toBeInTheDocument();
  });

  it("renders the proposal labelled unscored, with its risk/reward labelled informational only", () => {
    render(
      <AgentProposalPanel
        proposal={COHERENT_PROPOSAL}
        userDirection={null}
        userEntry={null}
        userStop={null}
        userTarget={null}
        agentReasoning={null}
        onAccept={noop}
        accepting={false}
        acceptError={null}
      />,
    );

    const agentLevels = screen.getByTestId("proposal-agent-levels");
    expect(within(agentLevels).getByText(/unscored/i)).toBeInTheDocument();
    expect(within(agentLevels).getByText("LONG")).toBeInTheDocument();
    expect(within(agentLevels).getByText("1.1")).toBeInTheDocument();

    expect(screen.getByTestId("proposal-ratio")).toHaveTextContent(/informational only/i);
    expect(screen.getByTestId("proposal-ratio")).toHaveTextContent(/not part of the score/i);
    // No user levels supplied -- side-by-side block must not render.
    expect(screen.queryByTestId("proposal-your-levels")).not.toBeInTheDocument();
  });

  it("renders the user's levels and the agent's proposal side by side when the user supplied levels", () => {
    render(
      <AgentProposalPanel
        proposal={COHERENT_PROPOSAL}
        userDirection="long"
        userEntry={1.095}
        userStop={1.09}
        userTarget={1.105}
        agentReasoning={null}
        onAccept={noop}
        accepting={false}
        acceptError={null}
      />,
    );

    const yourLevels = screen.getByTestId("proposal-your-levels");
    expect(within(yourLevels).getByText(/your levels/i)).toBeInTheDocument();
    expect(within(yourLevels).getByText("1.095")).toBeInTheDocument();

    const agentLevels = screen.getByTestId("proposal-agent-levels");
    expect(within(agentLevels).getByText("1.1")).toBeInTheDocument();

    // Both are present at once -- genuinely side by side, not one
    // replacing the other.
    expect(yourLevels).toBeInTheDocument();
    expect(agentLevels).toBeInTheDocument();
  });

  it("shows a plain decline message alongside the user's own levels when only the user supplied levels", () => {
    render(
      <AgentProposalPanel
        proposal={DECLINED_PROPOSAL}
        userDirection="long"
        userEntry={1.095}
        userStop={1.09}
        userTarget={1.105}
        agentReasoning={null}
        onAccept={noop}
        accepting={false}
        acceptError={null}
      />,
    );

    expect(screen.getByTestId("proposal-your-levels")).toBeInTheDocument();
    expect(screen.getByTestId("proposal-declined-notice")).toBeInTheDocument();
  });

  it("shows a coherence warning for an incoherent proposal, with no ratio", () => {
    const incoherent: AgentProposalOut = {
      ...COHERENT_PROPOSAL,
      is_coherent: false,
      risk_reward_ratio: null,
      coherence_error: "stop is on the wrong side of entry for a long trade",
    };

    render(
      <AgentProposalPanel
        proposal={incoherent}
        userDirection={null}
        userEntry={null}
        userStop={null}
        userTarget={null}
        agentReasoning={null}
        onAccept={noop}
        accepting={false}
        acceptError={null}
      />,
    );

    expect(screen.getByTestId("proposal-coherence-warning")).toHaveTextContent(/wrong side/i);
    expect(screen.getByTestId("proposal-ratio")).toHaveTextContent("—");
  });

  it("calls onAccept when the accept button is clicked", async () => {
    const onAccept = vi.fn();
    const user = userEvent.setup();

    render(
      <AgentProposalPanel
        proposal={COHERENT_PROPOSAL}
        userDirection={null}
        userEntry={null}
        userStop={null}
        userTarget={null}
        agentReasoning={null}
        onAccept={onAccept}
        accepting={false}
        acceptError={null}
      />,
    );

    await user.click(screen.getByRole("button", { name: /accept proposal/i }));

    expect(onAccept).toHaveBeenCalledTimes(1);
  });

  it("disables the accept button and shows a busy label while accepting", () => {
    render(
      <AgentProposalPanel
        proposal={COHERENT_PROPOSAL}
        userDirection={null}
        userEntry={null}
        userStop={null}
        userTarget={null}
        agentReasoning={null}
        onAccept={noop}
        accepting={true}
        acceptError={null}
      />,
    );

    expect(screen.getByRole("button", { name: /accepting/i })).toBeDisabled();
  });

  it("shows a real accept error message when accepting fails", () => {
    render(
      <AgentProposalPanel
        proposal={COHERENT_PROPOSAL}
        userDirection={null}
        userEntry={null}
        userStop={null}
        userTarget={null}
        agentReasoning={null}
        onAccept={noop}
        accepting={false}
        acceptError="Run run-1 has no agent-proposed trade levels to accept."
      />,
    );

    expect(screen.getByText(/no agent-proposed trade levels to accept/i)).toBeInTheDocument();
  });
});
