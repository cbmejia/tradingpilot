// TradePilot AI — the only place this frontend talks to the backend.
//
// In plain terms: every HTTP call the UI makes goes through one of the
// functions below. That way there's exactly one place that builds a
// request URL, one place that turns a non-2xx response into an error the
// UI can show, and one place that turns "the backend didn't respond at
// all" (network failure, backend not running) into a clear message
// instead of a request that silently hangs forever.

import type {
  AcceptProposalResponse,
  HumanReviewRequest,
  HumanReviewResponse,
  RunCreateRequest,
  RunCreateResponse,
  RunDetail,
  RunListResponse,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

/** Raised for both "the backend answered with an error" and "the backend
 * never answered at all" -- the UI only needs one error type to catch. */
export class ApiError extends Error {
  status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    // fetch() only throws for network-level failures: the backend isn't
    // running, the wrong port, no network at all, etc. -- never for a
    // non-2xx HTTP response, which is handled below instead.
    throw new ApiError(
      `Could not reach the TradePilot backend at ${API_BASE_URL}. Is it running? ` +
        `(uvicorn backend.main:app --reload)`,
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Response body wasn't JSON (or was empty) -- fall back to the
      // HTTP status text rather than guessing at a reason.
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function createRun(payload: RunCreateRequest): Promise<RunCreateResponse> {
  return request<RunCreateResponse>("/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * forceScenario (Milestone 12, testing only): deliberately forces one
 * pipeline stage to a synthetic result so a guardrail's behavior can be
 * proven with a real run -- see components/TestingControls.tsx and
 * docs/failure_modes.md. Omit for every real analysis; the backend
 * refuses it outright unless TESTING_CONTROLS_ENABLED=true is set on
 * the server, so passing it has zero effect against a normal backend.
 */
export function analyzeRun(runId: string, forceScenario?: string): Promise<RunDetail> {
  const query = forceScenario ? `?force_scenario=${encodeURIComponent(forceScenario)}` : "";
  return request<RunDetail>(`/runs/${encodeURIComponent(runId)}/analyze${query}`, {
    method: "POST",
  });
}

export function getRun(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/runs/${encodeURIComponent(runId)}`);
}

export function listRuns(limit = 10, offset = 0): Promise<RunListResponse> {
  return request<RunListResponse>(`/runs?limit=${limit}&offset=${offset}`);
}

export function reviewRun(
  runId: string,
  payload: HumanReviewRequest,
): Promise<HumanReviewResponse> {
  return request<HumanReviewResponse>(`/runs/${encodeURIComponent(runId)}/review`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * 7A Iteration 1. Never rescores or re-analyzes runId -- it creates a
 * brand-new run seeded with the agent's proposed levels, returned here.
 * The caller still has to POST /runs/{newRunId}/analyze like any other
 * run; accepting is not itself an analysis.
 */
export function acceptProposal(runId: string): Promise<AcceptProposalResponse> {
  return request<AcceptProposalResponse>(`/runs/${encodeURIComponent(runId)}/accept-proposal`, {
    method: "POST",
  });
}

/** The URL for a run's captured chart image (GET /runs/{id}/screenshot).
 * Not fetched through request() above -- it's used directly as an <img>
 * src, so the browser makes this request itself.
 *
 * role (7A Iteration 2): "PRIMARY" (the default, reproducing the exact
 * original single-capture URL) or "CONFIRMATION", selecting which of a
 * run's up to two captures to fetch. */
export function screenshotUrl(runId: string, role: "PRIMARY" | "CONFIRMATION" = "PRIMARY"): string {
  const base = `${API_BASE_URL}/runs/${encodeURIComponent(runId)}/screenshot`;
  return role === "PRIMARY" ? base : `${base}?role=${encodeURIComponent(role)}`;
}

export { API_BASE_URL };
