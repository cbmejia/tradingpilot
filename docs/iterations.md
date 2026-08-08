# Iterations

Log of build milestones for TradePilot AI. Twelve planned milestones total —
see the roadmap at the bottom.

## Milestone 1 — Frontend UI shell

React + TypeScript (Vite) dashboard shell: header, six-card layout with
designed empty states for signal, chart capture, market snapshot, economic
calendar, guardrails, and history. No live data, no backend calls.

## Milestone 2 — Architecture and folder structure

Wrote `docs/architecture.md`: component responsibilities, the 12-step
workflow, the LIVE/DEMO screenshot capture design, data flow, and the
non-negotiable safety principles (no execution, agent never emits a score,
guardrails are deterministic, every run is fully audited). Added the
`backend/api/` sub-package (routers), `backend/orchestrator.py`,
`backend/schemas.py`, and package `__init__.py` files where missing. No
business logic yet — placeholders only.

**Deviation flagged:** Milestone 1 shipped the frontend shell with
hand-rolled CSS. The stack now specifies Tailwind. Rather than churn the
shell twice, Tailwind is added when the UI milestone (11) is built out.

## Milestone 3 — Database schema and audit trail

Built the SQLite database layer with SQLAlchemy:

- `database/database.py` — engine, session factory, `init_db()`. SQLite
  foreign-key enforcement turned on explicitly (off by default in SQLite).
- `database/models.py` — 8 tables: `Run` (parent row for one analysis) and
  seven child tables that each record one workflow step: `Capture`,
  `MarketData`, `AgentAnalysis`, `Evaluation`, `GuardrailResult`,
  `HumanReview`, `AuditEvent`. Every child table points back at its `Run`
  via `run_id`, so the full history of a run can always be reconstructed.
- `database/crud.py` — the only sanctioned functions for writing rows.
  `add_evaluation()` has no `total_score` parameter at all — it always
  computes the total as the sum of the five component scores, so nothing
  (including the future AI agent) has a path to writing the final score
  directly.
- `database/init_db.py` — run with `python -m database.init_db` to create
  `database/tradepilot.db` and print the tables it made.
- `tests/test_database.py` — 14 tests covering initialization and every
  table (create a run, save a capture success/failure, save market data
  success/failure, save an analysis, save an evaluation and confirm the
  total is computed, confirm `add_evaluation` has no `total_score`
  parameter, save a guardrail result, save a human review, save an audit
  event, and walk a full run's relationships).
- `pytest.ini` added at the repo root so `pytest` resolves `database.*`
  imports.
- `backend/requirements.txt` now pins `sqlalchemy`, `python-dotenv`,
  `pytest`.

All 14 tests pass. `python -m database.init_db` was run for real and
created `database/tradepilot.db` with all 8 tables and the `captures.run_id
-> runs.id` foreign key correctly in place (verified directly with
`sqlite3`).

No FastAPI routes, no orchestrator logic, no capture/market-data/agent/
eval/guardrail implementations, and no frontend changes were made — this
milestone is the database layer only.

## Roadmap

1. ~~Architecture~~
2. ~~Folder structure~~
3. ~~Database schema~~
4. Backend API
5. Screenshot tool
6. Market-data tool
7. Agent loop
8. Evaluation
9. Guardrails
10. Human approval
11. UI (incl. Tailwind migration)
12. Testing
