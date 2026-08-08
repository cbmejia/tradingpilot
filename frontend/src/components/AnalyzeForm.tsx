import { useState } from "react";
import type { FormEvent } from "react";
import { ALLOWED_TIMEFRAMES } from "../api/types";
import type { RunCreateRequest } from "../api/types";
import { TestingControls } from "./TestingControls";

interface AnalyzeFormProps {
  onSubmit: (payload: RunCreateRequest, forceScenario?: string) => void;
  busy: boolean;
  error: string | null;
}

const DIRECTIONS = ["", "long", "short"];

export function AnalyzeForm({ onSubmit, busy, error }: AnalyzeFormProps) {
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("1h");
  const [direction, setDirection] = useState("");
  const [entry, setEntry] = useState("");
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");
  const [forceScenario, setForceScenario] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;

    const payload: RunCreateRequest = {
      symbol: symbol.trim().toUpperCase(),
      timeframe,
      direction: direction || null,
      entry: entry ? Number(entry) : null,
      stop: stop ? Number(stop) : null,
      target: target ? Number(target) : null,
    };
    onSubmit(payload, forceScenario || undefined);
  }

  const inputClass =
    "w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none disabled:opacity-50";
  const labelClass = "text-xs font-medium text-slate-400";

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Symbol</span>
          <input
            className={inputClass}
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="EURUSD"
            required
            disabled={busy}
            maxLength={20}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Timeframe</span>
          <select
            className={inputClass}
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            disabled={busy}
          >
            {ALLOWED_TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="flex flex-col gap-1">
        <span className={labelClass}>Direction (optional)</span>
        <select
          className={inputClass}
          value={direction}
          onChange={(e) => setDirection(e.target.value)}
          disabled={busy}
        >
          {DIRECTIONS.map((d) => (
            <option key={d} value={d}>
              {d === "" ? "not provided" : d}
            </option>
          ))}
        </select>
      </label>

      <div className="grid grid-cols-3 gap-3">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Entry</span>
          <input
            className={inputClass}
            type="number"
            step="any"
            min="0"
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
            placeholder="optional"
            disabled={busy}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Stop</span>
          <input
            className={inputClass}
            type="number"
            step="any"
            min="0"
            value={stop}
            onChange={(e) => setStop(e.target.value)}
            placeholder="optional"
            disabled={busy}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Target</span>
          <input
            className={inputClass}
            type="number"
            step="any"
            min="0"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="optional"
            disabled={busy}
          />
        </label>
      </div>

      <TestingControls value={forceScenario} onChange={setForceScenario} disabled={busy} />

      {error && (
        <p className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy}
        className={
          "mt-1 rounded-md px-4 py-2 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400 " +
          (forceScenario ? "bg-amber-600 hover:bg-amber-500" : "bg-sky-600 hover:bg-sky-500")
        }
      >
        {busy ? "Analyzing…" : forceScenario ? "Analyze (forcing a test scenario)" : "Analyze"}
      </button>
    </form>
  );
}
