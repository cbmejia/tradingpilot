# TradePilot AI -- repeatability harness (7A Iteration 3).
#
# In plain terms: this runs the existing pipeline N times against a fixed
# DEMO fixture, with nothing varied between runs, and reports how much the
# output moved. It exists because Iteration 2 found -- by hand, n=5 -- that
# identical DEMO input does not produce identical categorical output
# (trend_quality flipped MODERATE/WEAK, total_score moved 45<->55). This
# tool makes that measurement reproducible and cheap to re-run at a larger
# n, and adds a second question: does the agent's proposed risk/reward
# cluster on a user-supplied value, or float freely?
#
# READ-ONLY WITH RESPECT TO SCORING. This module never imports evals/ --
# it only calls backend.orchestrator.run_pipeline() (which internally uses
# evals/trade_evaluator.py to score each run, exactly as any other caller
# would) and reads back what got written via the ORM. It never computes,
# recomputes, or writes an evaluation itself. A source-grep test in
# tests/test_repeatability_harness.py proves this file contains no
# "import evals" / "from evals" line, and a behavioral test proves the
# evaluations this harness produces are byte-identical to calling
# run_pipeline() directly -- the harness adds repetition, nothing else.
#
# DEMO ONLY BY DEFAULT. CaptureManager/MarketDataManager (constructed
# inside run_pipeline) read CAPTURE_MODE/MARKET_DATA_MODE from .env
# themselves -- there is no per-call override -- so the only way to
# guarantee this never burns a LIVE Alpha Vantage quota by accident is to
# check those two settings before creating a single run, and refuse unless
# --allow-live is passed explicitly. See _live_guard() below.
#
# Usage:
#   python -m tools.repeatability_harness --fixture stability --trade-params none
#   python -m tools.repeatability_harness --fixture stability --trade-params levels
#   python -m tools.repeatability_harness --fixture proposals --trade-params levels
#   python -m tools.repeatability_harness --fixture stability --trade-params none --n 20

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend import config
from backend.orchestrator import run_pipeline
from database import crud
from database.database import SessionLocal

REPO_ROOT = Path(__file__).resolve().parent.parent
MEASUREMENTS_DIR = REPO_ROOT / "measurements"

PROMPT_FILES = [
    REPO_ROOT / "prompts" / "system_prompt.md",
    REPO_ROOT / "prompts" / "analysis_prompt.md",
    REPO_ROOT / "prompts" / "confirmation_system_prompt.md",
    REPO_ROOT / "prompts" / "confirmation_analysis_prompt.md",
]

# Measured directly from the Iteration 2 addendum's 5-run batch
# (created_at -> completed_at on c7ab7dd2.../9acb5fca.../... in
# database/tradepilot.db): ~11-12s per run, one primary + one
# confirmation Claude call, DEMO capture/quote are local/instant.
SECONDS_PER_RUN_ESTIMATE = 12

# LIVE mode is never the default and is deliberately hard-capped even with
# --allow-live -- protects the Alpha Vantage 25/day free-tier quota,
# already exhausted once during Iteration 1's live verification.
LIVE_MODE_HARD_CAP = 5

DEFAULT_N = 10

# The six fields that feed total_score (evals/trade_evaluator.py) --
# used for both the per-field distribution report and the attribution
# logic. confirmation_trend_direction/quality and the proposal fields are
# deliberately excluded: neither one drives total_score, so attributing a
# score change to them would be wrong on its face.
SCORED_FIELDS = [
    "trend_direction",
    "trend_quality",
    "structure_quality",
    "setup_quality",
    "context_risk",
    "uncertainty",
]

# Two fixture profiles, chosen for a specific reason each -- see "The two
# research questions" in the Iteration 3 design. Neither is a guess:
# both are the real, already-verified DEMO paths from Iteration 1/2.
FIXTURES = {
    "stability": {
        "symbol": "EURUSD",
        "timeframe": "1h",
        "chart_variant": "readable_chart",
        "description": (
            "EURUSD 1h primary / 4h confirmation, chart_variant=readable_chart -- "
            "the pairing Iteration 2 recorded as 'adopted going forward'. Exercises "
            "both real captures and both real Claude calls end to end. This fixture's "
            "setup_quality reads MARGINAL/NONE consistently -- it has never produced a "
            "proposal in this project's history, so it answers research question (a) "
            "(categorical stability) only; question (b) is reported N/A on this fixture, "
            "never fabricated from zero data points."
        ),
        # LONG 1.150/1.145/1.160 -- byte-identical to the trade params
        # Iteration 2's own 5-run categorical-stability batch used, so
        # this batch's numbers are directly comparable to that one.
        "levels": dict(direction="long", entry=1.1500, stop=1.1450, target=1.1600),
    },
    "proposals": {
        "symbol": "EURUSD",
        "timeframe": "4h",
        "chart_variant": "readable_chart",
        "description": (
            "EURUSD 4h primary only, chart_variant=readable_chart. Its confirmation "
            "timeframe (1d) has no committed DEMO fixture, so CROSS_TIMEFRAME_AGREEMENT "
            "fails closed with an honest 'no fixture' reason on every run -- expected, "
            "documented, not a harness defect, and orthogonal to proposals (which come "
            "from the primary call only). This is the only readable DEMO fixture known "
            "to produce agent proposals, so it's the one fixture that can answer "
            "research question (b), RR clustering."
        ),
        # LONG 1.156/1.146/1.176, RR=2.0 -- the same shape (and, not
        # coincidentally, close to the same price level) as the real LIVE
        # evidence run ed4e50b2... used against this exact chart in
        # Iteration 1's addendum.
        "levels": dict(direction="long", entry=1.1560, stop=1.1460, target=1.1760),
    },
}

SCOPE_LIMIT_TEMPLATE = (
    "SCOPE LIMIT: these numbers describe one fixture ({fixture}), one model "
    "({model}), one point in time ({timestamp}), n={n}. They are not a general "
    "claim about the model's reliability on real charts, other symbols or "
    "timeframes, or future calls -- n={n} on a single DEMO fixture is enough to "
    "show that variation exists, not enough to characterize its full distribution."
)


def _sha256_file(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _hash_prompt_files() -> dict[str, Optional[str]]:
    return {p.relative_to(REPO_ROOT).as_posix(): _sha256_file(p) for p in PROMPT_FILES}


def _git_commit_hash() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _live_guard(allow_live: bool, requested_n: int) -> tuple[bool, int]:
    """
    Returns (proceed, effective_n). Refuses (proceed=False) if either mode
    isn't demo and --allow-live wasn't passed. If --allow-live was passed,
    N is hard-capped at LIVE_MODE_HARD_CAP regardless of what was
    requested -- the flag only lifts the refusal, it never changes what N
    means.
    """
    capture_mode = str(getattr(config, "CAPTURE_MODE", "demo")).strip().lower()
    market_mode = str(getattr(config, "MARKET_DATA_MODE", "demo")).strip().lower()
    is_live = capture_mode != "demo" or market_mode != "demo"

    if not is_live:
        return True, requested_n

    if not allow_live:
        print(
            f"REFUSED: CAPTURE_MODE={capture_mode!r} MARKET_DATA_MODE={market_mode!r} -- "
            f"this harness only runs against DEMO by default, to protect the LIVE Alpha "
            f"Vantage quota. Pass --allow-live to acknowledge and proceed (N will be "
            f"capped at {LIVE_MODE_HARD_CAP} regardless of --n).",
            file=sys.stderr,
        )
        return False, requested_n

    effective_n = min(requested_n, LIVE_MODE_HARD_CAP)
    print(
        f"*** LIVE MODE ACKNOWLEDGED (--allow-live) *** "
        f"CAPTURE_MODE={capture_mode!r} MARKET_DATA_MODE={market_mode!r}. "
        f"Every run below makes a real Alpha Vantage call. N capped at "
        f"{LIVE_MODE_HARD_CAP} (requested {requested_n})."
    )
    return True, effective_n


def _extract_record(run) -> dict:
    analysis = run.analyses[0] if run.analyses else None
    evaluation = run.evaluations[0] if run.evaluations else None
    confirmation = run.confirmation_analysis
    proposal = run.proposal
    ctf = next(
        (g for g in run.guardrail_results if g.guardrail_name == "CROSS_TIMEFRAME_AGREEMENT"),
        None,
    )
    return {
        "run_id": run.id,
        "harness_status": "COMPLETED",
        "final_status": run.status,
        "agent_analysis_status": analysis.status if analysis else None,
        "trend_direction": analysis.trend_direction if analysis else None,
        "trend_quality": analysis.trend_quality if analysis else None,
        "structure_quality": analysis.structure_quality if analysis else None,
        "setup_quality": analysis.setup_quality if analysis else None,
        "context_risk": analysis.context_risk if analysis else None,
        "uncertainty": analysis.uncertainty if analysis else None,
        "model": analysis.model if analysis else None,
        "confirmation_status": confirmation.status if confirmation else "NO_ROW",
        "confirmation_trend_direction": confirmation.trend_direction if confirmation else None,
        "confirmation_trend_quality": confirmation.trend_quality if confirmation else None,
        "cross_timeframe_agreement_passed": ctf.passed if ctf else None,
        "cross_timeframe_agreement_reason": ctf.reason if ctf else None,
        "evaluation_status": evaluation.status if evaluation else None,
        "total_score": evaluation.total_score if evaluation else None,
        "trend_score": evaluation.trend_score if evaluation else None,
        "structure_score": evaluation.structure_score if evaluation else None,
        "entry_score": evaluation.entry_score if evaluation else None,
        "risk_reward_score": evaluation.risk_reward_score if evaluation else None,
        "timing_context_score": evaluation.timing_context_score if evaluation else None,
        "proposal_row_exists": proposal is not None,
        "has_proposal": proposal.has_proposal if proposal else None,
        "proposal_direction": proposal.direction if proposal else None,
        "proposal_entry": proposal.entry if proposal else None,
        "proposal_stop": proposal.stop if proposal else None,
        "proposal_target": proposal.target if proposal else None,
        "proposal_risk_reward_ratio": proposal.risk_reward_ratio if proposal else None,
        "proposal_is_coherent": proposal.is_coherent if proposal else None,
    }


def _field_distribution(records: list[dict], field: str) -> Counter:
    completed = [r for r in records if r["harness_status"] == "COMPLETED"]
    return Counter(r.get(field) for r in completed)


def _attribution_notes(records: list[dict]) -> list[str]:
    """
    For each scored run whose total_score differs from the batch's modal
    (most common) field vector, report which single SCORED_FIELDS field
    differs -- only when EXACTLY one differs. More than one differing
    field means the driver can't be isolated from this batch alone, and
    that's reported plainly rather than guessed.
    """
    scored = [
        r
        for r in records
        if r["harness_status"] == "COMPLETED" and r["total_score"] is not None
    ]
    if len(scored) < 2:
        return []

    vectors = [tuple(r[f] for f in SCORED_FIELDS) for r in scored]
    modal_vector, _ = Counter(vectors).most_common(1)[0]
    modal_scores = Counter(
        r["total_score"]
        for r, v in zip(scored, vectors)
        if v == modal_vector
    )
    modal_score = modal_scores.most_common(1)[0][0]

    notes = []
    for r, v in zip(scored, vectors):
        if v == modal_vector:
            continue
        diffs = [f for f, mv, rv in zip(SCORED_FIELDS, modal_vector, v) if mv != rv]
        delta = r["total_score"] - modal_score
        short_id = r["run_id"][:12]
        if len(diffs) == 1:
            f = diffs[0]
            mv = modal_vector[SCORED_FIELDS.index(f)]
            rv = r[f]
            notes.append(
                f"run {short_id}...: {f} {mv} -> {rv} drove total_score "
                f"{modal_score} -> {r['total_score']} (delta={delta:+d})"
            )
        else:
            notes.append(
                f"run {short_id}...: NOT cleanly attributable -- {len(diffs)} fields "
                f"differed simultaneously ({', '.join(diffs)}); total_score "
                f"{modal_score} -> {r['total_score']} (delta={delta:+d})"
            )
    return notes


def _rr_clustering(records: list[dict], supplied_rr: Optional[float]) -> dict:
    completed = [r for r in records if r["harness_status"] == "COMPLETED"]
    proposals = [r for r in completed if r["has_proposal"]]
    if not proposals:
        return {
            "applicable": False,
            "note": f"N/A -- 0/{len(completed)} completed runs produced a proposal on this fixture.",
        }
    ratios = [
        r["proposal_risk_reward_ratio"]
        for r in proposals
        if r["proposal_risk_reward_ratio"] is not None
    ]
    return {
        "applicable": True,
        "n_proposals": len(proposals),
        "n_completed": len(completed),
        "supplied_rr": supplied_rr,
        "ratios": ratios,
        "min": min(ratios) if ratios else None,
        "max": max(ratios) if ratios else None,
        "distinct_ratios": len(set(ratios)),
    }


def _print_distribution(label: str, counter: Counter, total: int) -> None:
    if total == 0:
        print(f"  {label}: no completed runs")
        return
    parts = ", ".join(f"{value!r} x{count}" for value, count in counter.most_common())
    print(f"  {label}: {len(counter)} distinct -- {parts}")


def run_batch(
    fixture_name: str,
    trade_param_condition: str,
    n: int,
    allow_live: bool,
) -> Path:
    if fixture_name not in FIXTURES:
        raise ValueError(f"fixture must be one of {sorted(FIXTURES)}, got {fixture_name!r}")
    if trade_param_condition not in ("levels", "none"):
        raise ValueError(f"trade_param_condition must be 'levels' or 'none', got {trade_param_condition!r}")

    fixture = FIXTURES[fixture_name]

    proceed, effective_n = _live_guard(allow_live, n)
    if not proceed:
        sys.exit(1)

    est_seconds = effective_n * SECONDS_PER_RUN_ESTIMATE
    print(
        f"Fixture: {fixture_name} ({fixture['symbol']} {fixture['timeframe']}, "
        f"chart_variant={fixture['chart_variant']})"
    )
    print(f"Trade params: {trade_param_condition}")
    print(
        f"N={effective_n} -- estimated wall-clock ~{est_seconds // 60}m{est_seconds % 60:02d}s "
        f"(~{SECONDS_PER_RUN_ESTIMATE}s/run, measured from Iteration 2's 5-run batch)"
    )

    trade_kwargs = fixture["levels"] if trade_param_condition == "levels" else {}
    supplied_rr = None
    if trade_param_condition == "levels":
        d = fixture["levels"]
        risk = abs(d["entry"] - d["stop"])
        reward = abs(d["target"] - d["entry"])
        supplied_rr = reward / risk if risk else None

    prompt_hashes_start = _hash_prompt_files()
    git_commit = _git_commit_hash()
    batch_started_at = datetime.now(timezone.utc)
    batch_id = (
        f"{fixture_name}_{trade_param_condition}_"
        f"{batch_started_at.strftime('%Y%m%dT%H%M%SZ')}"
    )

    session = SessionLocal()
    records: list[dict] = []
    try:
        for i in range(1, effective_n + 1):
            run = crud.create_run(
                session,
                symbol=fixture["symbol"],
                timeframe=fixture["timeframe"],
                status="pending",
                **trade_kwargs,
            )
            crud.add_audit_event(
                session,
                run_id=run.id,
                event_type="repeatability_harness_run",
                event_message=(
                    f"7A Iteration 3 repeatability harness. batch={batch_id!r}, "
                    f"fixture={fixture_name!r}, trade_params={trade_param_condition!r}, "
                    f"index={i}/{effective_n}. This run exists purely to measure "
                    f"run-to-run variation on identical input -- it is not a real trade "
                    f"analysis request."
                ),
            )
            try:
                updated = run_pipeline(session, run.id, chart_variant=fixture["chart_variant"])
                record = _extract_record(updated)
            except Exception as exc:  # noqa: BLE001 -- deliberately broad, see module docstring
                record = {
                    "run_id": run.id,
                    "harness_status": "HARNESS_FAILURE",
                    "harness_error": f"{type(exc).__name__}: {exc}",
                }
            records.append(record)
            status_word = record.get("final_status") or record.get("harness_status")
            score = record.get("total_score")
            print(f"  [{i}/{effective_n}] run {run.id[:12]}... -> {status_word} (total_score={score})")
    finally:
        session.close()

    prompt_hashes_end = _hash_prompt_files()
    prompt_files_stable = prompt_hashes_start == prompt_hashes_end
    if not prompt_files_stable:
        print(
            "*** WARNING: prompt file hashes changed during this batch -- "
            "'nothing varied between runs' does NOT hold for this result set. ***"
        )

    completed = [r for r in records if r["harness_status"] == "COMPLETED"]
    failed = [r for r in records if r["harness_status"] != "COMPLETED"]

    models_seen = {r["model"] for r in completed if r.get("model")}
    if not models_seen:
        print(
            "*** WARNING: model identifier unavailable on every completed run -- "
            "these numbers are not attributable to a specific model. ***"
        )
    elif config.CLAUDE_MODEL not in models_seen:
        print(
            f"*** WARNING: configured CLAUDE_MODEL={config.CLAUDE_MODEL!r} does not match "
            f"the model(s) actually recorded per-run: {sorted(models_seen)}. ***"
        )

    disclaimer = SCOPE_LIMIT_TEMPLATE.format(
        fixture=fixture_name,
        model=config.CLAUDE_MODEL,
        timestamp=batch_started_at.isoformat(),
        n=effective_n,
    )

    print()
    print(f"=== {len(completed)}/{effective_n} runs completed, {len(failed)} failed ===")
    if failed:
        for r in failed:
            print(f"  FAILED run {r['run_id'][:12]}...: {r.get('harness_error')}")
    print()
    print("Per-field distribution (completed runs only):")
    for field in SCORED_FIELDS:
        _print_distribution(field, _field_distribution(completed, field), len(completed))
    _print_distribution(
        "confirmation_trend_direction", _field_distribution(completed, "confirmation_trend_direction"), len(completed)
    )
    _print_distribution(
        "confirmation_trend_quality", _field_distribution(completed, "confirmation_trend_quality"), len(completed)
    )
    _print_distribution(
        "cross_timeframe_agreement_passed",
        _field_distribution(completed, "cross_timeframe_agreement_passed"),
        len(completed),
    )
    _print_distribution("final_status", _field_distribution(completed, "final_status"), len(completed))

    scores = [r["total_score"] for r in completed if r["total_score"] is not None]
    print()
    if scores:
        print(
            f"total_score: min={min(scores)} max={max(scores)} spread={max(scores) - min(scores)} "
            f"({len(scores)}/{len(completed)} runs scored)"
        )
        _print_distribution("total_score", Counter(scores), len(scores))
    else:
        print(f"total_score: no runs scored (0/{len(completed)})")

    attribution = _attribution_notes(completed)
    print()
    print("Attribution (only where exactly one field differs from the modal run):")
    if attribution:
        for note in attribution:
            print(f"  {note}")
    else:
        print("  none -- either every completed run matched the modal field vector, or scores never differed")

    rr = _rr_clustering(completed, supplied_rr)
    print()
    print("RR clustering (research question b):")
    if not rr["applicable"]:
        print(f"  {rr['note']}")
    else:
        print(
            f"  {rr['n_proposals']}/{rr['n_completed']} completed runs proposed. "
            f"ratios={rr['ratios']} (min={rr['min']}, max={rr['max']}, "
            f"{rr['distinct_ratios']} distinct values). supplied_rr={rr['supplied_rr']}"
        )

    print()
    print(disclaimer)

    MEASUREMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = MEASUREMENTS_DIR / f"{batch_id}.json"
    payload = {
        "batch_id": batch_id,
        "fixture": fixture_name,
        "fixture_description": fixture["description"],
        "symbol": fixture["symbol"],
        "timeframe": fixture["timeframe"],
        "chart_variant": fixture["chart_variant"],
        "trade_param_condition": trade_param_condition,
        "trade_params": trade_kwargs or None,
        "supplied_risk_reward_ratio": supplied_rr,
        "n_requested": n,
        "n_effective": effective_n,
        "n_completed": len(completed),
        "n_failed": len(failed),
        "started_at_utc": batch_started_at.isoformat(),
        "configured_model": config.CLAUDE_MODEL,
        "models_recorded_per_run": sorted(models_seen),
        "prompt_file_hashes_start": prompt_hashes_start,
        "prompt_file_hashes_end": prompt_hashes_end,
        "prompt_files_stable": prompt_files_stable,
        "git_commit": git_commit,
        "capture_mode": config.CAPTURE_MODE,
        "market_data_mode": config.MARKET_DATA_MODE,
        "scope_limit_disclaimer": disclaimer,
        "records": records,
        "summary": {
            "field_distributions": {
                field: dict(_field_distribution(completed, field)) for field in SCORED_FIELDS
            },
            "confirmation_trend_direction": dict(_field_distribution(completed, "confirmation_trend_direction")),
            "confirmation_trend_quality": dict(_field_distribution(completed, "confirmation_trend_quality")),
            "cross_timeframe_agreement_passed": dict(
                _field_distribution(completed, "cross_timeframe_agreement_passed")
            ),
            "final_status": dict(_field_distribution(completed, "final_status")),
            "total_score": {
                "min": min(scores) if scores else None,
                "max": max(scores) if scores else None,
                "spread": (max(scores) - min(scores)) if scores else None,
                "distribution": dict(Counter(scores)),
            },
            "attribution": attribution,
            "rr_clustering": rr,
        },
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print()
    try:
        display_path = out_path.relative_to(REPO_ROOT)
    except ValueError:
        # Not under REPO_ROOT -- e.g. a test pointed MEASUREMENTS_DIR at a
        # tmp_path. Fall back to the absolute path rather than crashing a
        # batch after all N runs already completed and were written.
        display_path = out_path
    print(f"Written: {display_path}")
    return out_path


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "7A Iteration 3 repeatability harness -- runs the existing pipeline N times "
            "against a fixed DEMO fixture and reports how much the output moved. "
            "DEMO only by default; see --allow-live."
        )
    )
    parser.add_argument(
        "--fixture",
        required=True,
        choices=sorted(FIXTURES),
        help="Which committed DEMO fixture profile to use.",
    )
    parser.add_argument(
        "--trade-params",
        required=True,
        choices=["levels", "none"],
        dest="trade_params",
        help="'levels' supplies a fixed user trade (see FIXTURES); 'none' supplies nothing.",
    )
    parser.add_argument("--n", type=int, default=DEFAULT_N, help=f"Number of runs (default {DEFAULT_N}).")
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Acknowledge CAPTURE_MODE/MARKET_DATA_MODE is not demo and proceed anyway (N capped at 5).",
    )
    args = parser.parse_args(argv)

    run_batch(args.fixture, args.trade_params, args.n, args.allow_live)
    return 0


if __name__ == "__main__":
    sys.exit(main())
