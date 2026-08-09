import { useState } from "react";
import type { CaptureOut } from "../api/types";
import { screenshotUrl } from "../api/client";
import { EmptyState } from "./EmptyState";
import { ErrorNotice } from "./ErrorNotice";
import { SourceModeBadge } from "./DemoBadge";

interface ChartCapturePanelProps {
  runId: string;
  capture: CaptureOut | undefined;
  // 7A Iteration 2: which capture to fetch the image for -- "PRIMARY"
  // (the default, unchanged from before this iteration) or
  // "CONFIRMATION". Must match `capture`'s own timeframe_role; the caller
  // is responsible for passing the right pair (RunDetailView does).
  role?: "PRIMARY" | "CONFIRMATION";
}

export function ChartCapturePanel({ runId, capture, role = "PRIMARY" }: ChartCapturePanelProps) {
  const [imageFailedToLoad, setImageFailedToLoad] = useState(false);

  if (!capture) {
    return (
      <EmptyState
        message={
          role === "PRIMARY"
            ? "No chart has been captured yet."
            : "No confirmation chart has been captured yet."
        }
      />
    );
  }

  if (capture.status !== "SUCCESS") {
    return <ErrorNotice title="Chart capture failed" message={capture.error_message} />;
  }

  if (imageFailedToLoad) {
    return (
      <ErrorNotice
        title="Chart image could not be loaded"
        message={`The capture succeeded but the image failed to load from ${screenshotUrl(runId, role)}.`}
      />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <SourceModeBadge mode={capture.capture_mode} />
        {capture.captured_at && (
          <span className="text-xs text-slate-500">
            captured {new Date(capture.captured_at).toLocaleString()}
          </span>
        )}
      </div>
      <img
        src={screenshotUrl(runId, role)}
        alt={`${capture.symbol} ${capture.timeframe} chart (${role.toLowerCase()})`}
        className="w-full rounded-lg border border-slate-800"
        onError={() => setImageFailedToLoad(true)}
      />
    </div>
  );
}
