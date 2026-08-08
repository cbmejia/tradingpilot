import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SourceModeBadge } from "./DemoBadge";

describe("SourceModeBadge", () => {
  it("renders an unmistakable demo label for DEMO", () => {
    render(<SourceModeBadge mode="DEMO" />);

    expect(screen.getByText(/demo data/i)).toBeInTheDocument();
    expect(screen.getByText(/not real/i)).toBeInTheDocument();
  });

  it("renders a distinct label for LIVE, never claiming demo", () => {
    render(<SourceModeBadge mode="LIVE" />);

    expect(screen.getByText(/^live$/i)).toBeInTheDocument();
    expect(screen.queryByText(/demo/i)).not.toBeInTheDocument();
  });
});
