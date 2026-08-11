# measurements/

Recorded measurements, not fixtures.

Every file here is the output of one `tools/repeatability_harness.py`
batch (7A Iteration 3): N repeated runs of the real pipeline against one
fixed DEMO fixture, with nothing else varied, reporting how much the
agent's output moved on identical input. Unlike `screenshots/demo/` (real
inputs the pipeline reads) or `tests/` fixtures (hand-built inputs for
deterministic tests), files in this directory are *observations* — a
record of what a real model actually did on a specific day, against a
specific commit, and are committed on purpose so the numbers behind
`docs/iterations.md`'s Iteration 3 entry can be checked directly rather
than taken on faith.

Each file is named `<fixture>_<trade-param-condition>_<UTC-timestamp>.json`
and carries its own metadata: fixture, `chart_variant`, N, the configured
and per-run-recorded model id, prompt file SHA-256 hashes (start and end
of the batch), the git commit the batch ran against, and a scope-limit
disclaimer stating plainly that a batch describes one fixture, one model,
one point in time — not a general claim about the model.

Not every invocation of the harness needs to be committed here — only the
ones kept as evidence, the same curation `docs/handoff.md` already
applies to which runs stay in the dev database.
