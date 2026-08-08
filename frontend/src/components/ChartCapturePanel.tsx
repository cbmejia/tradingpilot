import { useState } from "react";
import type { CaptureOut } from "../api/types";
import { screenshotUrl } from "../api/client";
import { EmptyState } from "./EmptyState";
import { ErrorNotice } from "./ErrorNotice";
import { SourceModeBadge } from "./DemoBadge";

interface ChartCapturePanelProps {
  runId: string;
  capture: CaptureOut | undefined;
}

export function ChartCapturePanel({ runId, capture }: ChartCapturePanelProps) {
  const [imageFailedToLoad, setImageFailedToLoad] = useState(false);

  if (!capture) {
    return <EmptyState message="No chart has been captured yet." />;
  }

  if (capture.status !== "SUCCESS") {
    return <ErrorNotice title="Chart capture failed" message={capture.error_message} />;
  }

  if (imageFailedToLoad) {
    return (
      <ErrorNotice
        title="Chart image could not be loaded"
        message={`The capture succeeded but the image failed to load from ${screenshotUrl(runId)}.`}
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
        src={screenshotUrl(runId)}
        alt={`${capture.symbol} ${capture.timeframe} chart`}
        className="w-full rounded-lg border border-slate-800"
        onError={() => setImageFailedToLoad(true)}
      />
    </div>
  );
}
