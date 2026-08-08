// Milestone 12 — the one place this UI lets you deliberately force a
// pipeline stage to a synthetic result, so a guardrail can be
// demonstrated with a real, screenshottable run instead of only
// asserted in a test. Deliberately styled to look like nothing else in
// this app -- dashed amber border, explicit "TESTING ONLY" label -- so
// it can never be mistaken for a real control. It has no effect at all
// unless the backend was started with TESTING_CONTROLS_ENABLED=true; if
// it wasn't, choosing a scenario here just surfaces that real 403 in the
// normal error banner, the same as any other API error.

import { FORCE_SCENARIOS } from "../api/types";

interface TestingControlsProps {
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}

export function TestingControls({ value, onChange, disabled }: TestingControlsProps) {
  const selected = FORCE_SCENARIOS.find((s) => s.value === value);

  return (
    <div className="rounded-md border border-dashed border-amber-500/50 bg-amber-500/5 p-3">
      <p className="text-xs font-bold uppercase tracking-wide text-amber-400">
        Testing only — force a failure scenario
      </p>
      <p className="mt-1 text-xs text-amber-300/80">
        Substitutes a synthetic, clearly-labeled result for one pipeline stage so a
        guardrail can be proven. Has no effect unless the backend has
        TESTING_CONTROLS_ENABLED=true. See docs/failure_modes.md.
      </p>
      <select
        aria-label="Force a testing scenario"
        className="mt-2 w-full rounded-md border border-amber-500/40 bg-slate-950 px-2 py-1.5 text-sm text-amber-200 focus:border-amber-400 focus:outline-none disabled:opacity-50"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        <option value="">Off — run a real analysis</option>
        {FORCE_SCENARIOS.map((scenario) => (
          <option key={scenario.value} value={scenario.value}>
            {scenario.label}
          </option>
        ))}
      </select>
      {selected && <p className="mt-1 text-xs text-amber-300/70">{selected.description}</p>}
    </div>
  );
}
