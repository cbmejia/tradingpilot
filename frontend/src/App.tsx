import { useCallback, useEffect, useRef, useState } from "react";
import { Card } from "./components/Card";
import { AnalyzeForm } from "./components/AnalyzeForm";
import { PipelineProgress } from "./components/PipelineProgress";
import { RunList } from "./components/RunList";
import type { RunListItem } from "./components/RunList";
import { RunDetailView } from "./components/RunDetailView";
import { EmptyState } from "./components/EmptyState";
import * as api from "./api/client";
import { ApiError } from "./api/client";
import type { ReviewDecision, RunCreateRequest, RunDetail } from "./api/types";

const POLL_INTERVAL_MS = 700;
const RUN_LIST_PAGE_SIZE = 10;

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something unexpected went wrong.";
}

function App() {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<RunDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const pollHandle = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadRunList = useCallback(async () => {
    try {
      const list = await api.listRuns(RUN_LIST_PAGE_SIZE, 0);
      setListError(null);
      setRuns(list.items);

      // RunSummary has no mode/guardrail-outcome field of its own -- only
      // GET /runs/{id} does (see components/RunList.tsx's docstring).
      // Fetching each visible row's detail is a small, bounded number of
      // follow-up requests (page size 10), done purely from the frontend
      // so the demo label can be unmistakable in the list too, with no
      // backend change.
      const enriched = await Promise.all(
        list.items.map(async (item) => {
          try {
            const detail = await api.getRun(item.id);
            const isDemo =
              detail.captures[0]?.capture_mode === "DEMO" ||
              detail.market_data[0]?.mode === "DEMO";
            return { ...item, isDemo };
          } catch {
            // A single row's enrichment failing shouldn't blank out the
            // whole list -- it just won't show a demo badge yet.
            return item as RunListItem;
          }
        }),
      );
      setRuns(enriched);
    } catch (err) {
      setListError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    loadRunList();
  }, [loadRunList]);

  const selectRun = useCallback(async (runId: string) => {
    setSelectedRunId(runId);
    setDetailError(null);
    setReviewError(null);
    try {
      const run = await api.getRun(runId);
      setSelectedRun(run);
    } catch (err) {
      setSelectedRun(null);
      setDetailError(errorMessage(err));
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollHandle.current !== null) {
      clearInterval(pollHandle.current);
      pollHandle.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  async function handleAnalyzeSubmit(payload: RunCreateRequest) {
    setFormError(null);
    setIsAnalyzing(true);
    setDetailError(null);
    setReviewError(null);

    let runId: string;
    try {
      const created = await api.createRun(payload);
      runId = created.id;
      setSelectedRunId(runId);
      setSelectedRun(await api.getRun(runId));
    } catch (err) {
      setFormError(errorMessage(err));
      setIsAnalyzing(false);
      return;
    }

    // Progress through the pipeline stages is driven by real polled
    // GET /runs/{id} responses while POST /runs/{id}/analyze is still in
    // flight -- the orchestrator commits each step's row as it happens,
    // so a concurrent poll can see them appear one at a time even though
    // /analyze itself is synchronous and won't resolve until every stage
    // is done.
    stopPolling();
    pollHandle.current = setInterval(async () => {
      try {
        const run = await api.getRun(runId);
        setSelectedRun(run);
      } catch {
        // A single missed poll tick isn't worth surfacing as an error --
        // the final /analyze response (or the next successful tick) is
        // what actually matters.
      }
    }, POLL_INTERVAL_MS);

    try {
      const finished = await api.analyzeRun(runId);
      setSelectedRun(finished);
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      stopPolling();
      setIsAnalyzing(false);
      loadRunList();
    }
  }

  async function handleReview(decision: ReviewDecision, comment: string) {
    if (!selectedRunId) return;
    setReviewBusy(true);
    setReviewError(null);
    try {
      await api.reviewRun(selectedRunId, { decision, comment: comment || null });
      setSelectedRun(await api.getRun(selectedRunId));
      loadRunList();
    } catch (err) {
      setReviewError(errorMessage(err));
    } finally {
      setReviewBusy(false);
    }
  }

  return (
    <div className="flex min-h-full flex-col bg-slate-950 text-slate-100">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-6 py-4">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-sky-500" />
          <span className="text-base font-semibold tracking-tight">TradePilot AI</span>
        </div>
        <p className="text-xs text-slate-500">
          Educational decision support. Never places, submits, or simulates a trade.
        </p>
      </header>

      <main className="grid flex-1 gap-4 p-6 lg:grid-cols-[320px_1fr]">
        <div className="flex flex-col gap-4">
          <Card title="Analyze" subtitle="Runs the full capture → market data → agent → evaluation → guardrails pipeline">
            <AnalyzeForm onSubmit={handleAnalyzeSubmit} busy={isAnalyzing} error={formError} />
          </Card>

          {(isAnalyzing || selectedRun) && (
            <Card title="Pipeline progress">
              <PipelineProgress run={selectedRun} isAnalyzing={isAnalyzing} />
            </Card>
          )}

          <Card title="Recent runs">
            <RunList items={runs} selectedId={selectedRunId} onSelect={selectRun} error={listError} />
          </Card>
        </div>

        <div>
          {detailError && (
            <p className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
              {detailError}
            </p>
          )}
          {reviewError && (
            <p className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
              {reviewError}
            </p>
          )}
          {selectedRun ? (
            <RunDetailView
              run={selectedRun}
              onApprove={(comment) => handleReview("APPROVED", comment)}
              onReject={(comment) => handleReview("REJECTED", comment)}
              reviewBusy={reviewBusy}
            />
          ) : (
            <Card title="No run selected">
              <EmptyState message="Analyze a symbol, or pick a run from the list, to see its full detail here." />
            </Card>
          )}
        </div>
      </main>

      <footer className="border-t border-slate-800 px-6 py-3 text-xs text-slate-600">
        TradePilot AI — Milestone 11: frontend wired to the backend.
      </footer>
    </div>
  );
}

export default App;
