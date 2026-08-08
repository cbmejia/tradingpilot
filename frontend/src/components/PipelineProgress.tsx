import type { RunDetail } from "../api/types";

type StageStatus = "pending" | "in_progress" | "success" | "failed";

interface Stage {
  key: string;
  label: string;
  status: StageStatus;
}

/**
 * Derives each of the five pipeline stages' status entirely from what
 * GET /runs/{id} actually returned -- a stage is "success"/"failed" only
 * once its real row exists, "in_progress" only while analysis is still
 * running and no later stage has appeared yet, and "pending" otherwise.
 * Nothing here is a timer or an animation standing in for real progress.
 */
function deriveStages(run: RunDetail | null, isAnalyzing: boolean): Stage[] {
  const capture = run?.captures[0];
  const marketData = run?.market_data[0];
  const analysis = run?.analyses[0];
  const evaluation = run?.evaluations[0];
  const guardrailsDone = (run?.guardrail_results.length ?? 0) > 0;

  const definitions: Array<{ key: string; label: string; present: boolean; ok: boolean }> = [
    { key: "capture", label: "Chart capture", present: !!capture, ok: capture?.status === "SUCCESS" },
    {
      key: "market_data",
      label: "Market data",
      present: !!marketData,
      ok: marketData?.status === "SUCCESS",
    },
    { key: "analysis", label: "Agent analysis", present: !!analysis, ok: analysis?.status === "SUCCESS" },
    {
      key: "evaluation",
      label: "Evaluation",
      present: !!evaluation,
      ok: evaluation?.status === "SUCCESS",
    },
    { key: "guardrails", label: "Guardrails", present: guardrailsDone, ok: guardrailsDone },
  ];

  let cursorAssigned = false;
  return definitions.map((stage) => {
    if (stage.present) {
      return { key: stage.key, label: stage.label, status: stage.ok ? "success" : "failed" };
    }
    if (isAnalyzing && !cursorAssigned) {
      cursorAssigned = true;
      return { key: stage.key, label: stage.label, status: "in_progress" };
    }
    return { key: stage.key, label: stage.label, status: "pending" };
  });
}

function StageIcon({ status }: { status: StageStatus }) {
  if (status === "success") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500 text-[11px] font-bold text-slate-950">
        ✓
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-[11px] font-bold text-slate-950">
        ✕
      </span>
    );
  }
  if (status === "in_progress") {
    return (
      <span
        data-testid="stage-spinner"
        className="h-5 w-5 animate-spin rounded-full border-2 border-sky-500 border-t-transparent"
      />
    );
  }
  return <span className="h-5 w-5 rounded-full border-2 border-slate-700" />;
}

interface PipelineProgressProps {
  run: RunDetail | null;
  isAnalyzing: boolean;
}

export function PipelineProgress({ run, isAnalyzing }: PipelineProgressProps) {
  const stages = deriveStages(run, isAnalyzing);

  return (
    <ol className="flex flex-col gap-2">
      {stages.map((stage) => (
        <li key={stage.key} className="flex items-center gap-3">
          <StageIcon status={stage.status} />
          <span
            className={
              stage.status === "pending" ? "text-sm text-slate-500" : "text-sm text-slate-200"
            }
          >
            {stage.label}
          </span>
        </li>
      ))}
    </ol>
  );
}
