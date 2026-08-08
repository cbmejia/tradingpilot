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

## Roadmap

1. ~~Architecture~~
2. ~~Folder structure~~
3. Database schema
4. Backend API
5. Screenshot tool
6. Market-data tool
7. Agent loop
8. Evaluation
9. Guardrails
10. Human approval
11. UI (incl. Tailwind migration)
12. Testing
